from __future__ import annotations

import json
from pathlib import Path

from vlm_ocr import cli
from vlm_ocr.types import LayoutBlock, PageInput

CONTRACT = {"cliente": "", "total": 0.0}


def _block(text: str, x: float, y: float) -> LayoutBlock:
    return LayoutBlock(0, text, 1.0, (x, y, x + 80.0, y + 10.0))


def _blocks() -> list[LayoutBlock]:
    return [
        _block("CLIENTE", 10, 0),
        _block("ACME", 100, 0),
        _block("TOTAL", 10, 12),
        _block("9,99", 100, 12),
    ]


def _reordered_blocks() -> list[LayoutBlock]:
    return [
        _block("TOTAL", 10, 0),
        _block("9,99", 400, 0),
        _block("CLIENTE", 10, 12),
        _block("ACME", 400, 12),
    ]


def _mock(monkeypatch, blocks: list[LayoutBlock]) -> None:
    monkeypatch.setattr(cli, "ingest", lambda path, dpi=200: [PageInput(0, "texto", None)])
    monkeypatch.setattr(cli, "ocr_pages", lambda pages, lang="default": blocks)
    monkeypatch.setattr(cli, "native_blocks", lambda path: blocks)


def _contract(tmp_path: Path, payload: dict | None = None) -> Path:
    path = tmp_path / "contrato.json"
    path.write_text(json.dumps(payload or CONTRACT), encoding="utf-8")
    return path


def _model(tmp_path: Path) -> Path:
    path = tmp_path / "m.gguf"
    path.write_bytes(b"")
    return path


def _source(tmp_path: Path) -> Path:
    path = tmp_path / "doc.pdf"
    path.write_bytes(b"")
    return path


def _last_report(captured) -> dict:
    return json.loads(captured.err.strip().splitlines()[-1])


def test_homologate_then_a_zero_token_run(monkeypatch, tmp_path: Path, capsys) -> None:
    _mock(monkeypatch, _blocks())
    contract = _contract(tmp_path)
    templates_dir = tmp_path / "templates"
    monkeypatch.setattr(
        cli, "infer_contract", lambda *args, **kwargs: {"cliente": "ACME", "total": 9.99}
    )
    source = _source(tmp_path)
    model = _model(tmp_path)

    code = cli.main(
        [
            str(source),
            "--format",
            "json",
            "--contract",
            str(contract),
            "--model",
            str(model),
            "--homologate",
            "--templates-dir",
            str(templates_dir),
            "--metrics",
        ]
    )
    assert code == 0
    first = _last_report(capsys.readouterr())
    assert first["template"]["homologated"] is True
    assert first["extract"]["llm"] is True

    def boom(*args, **kwargs):
        raise AssertionError("la variante debe evitar el LLM")

    monkeypatch.setattr(cli, "infer_contract", boom)
    code = cli.main(
        [
            str(source),
            "--format",
            "json",
            "--contract",
            str(contract),
            "--no-llm",
            "--templates-dir",
            str(templates_dir),
            "--metrics",
        ]
    )

    assert code == 0
    captured = capsys.readouterr()
    assert json.loads(captured.out) == {"cliente": "ACME", "total": 9.99}
    report = _last_report(captured)
    assert report["template"]["found"] is True
    assert report["extract"]["llm"] is False


def test_unlocated_fields_use_a_subcontract(monkeypatch, tmp_path: Path, capsys) -> None:
    duplicated = _blocks() + [_block("9,99", 300, 12)]
    _mock(monkeypatch, duplicated)
    contract = _contract(
        tmp_path,
        {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {
                "cliente": {"type": ["string", "null"]},
                "total": {"type": ["number", "null"]},
            },
        },
    )
    templates_dir = tmp_path / "templates"
    source = _source(tmp_path)
    model = _model(tmp_path)
    monkeypatch.setattr(
        cli, "infer_contract", lambda *args, **kwargs: {"cliente": "ACME", "total": 9.99}
    )
    cli.main(
        [
            str(source),
            "--format",
            "json",
            "--contract",
            str(contract),
            "--model",
            str(model),
            "--homologate",
            "--templates-dir",
            str(templates_dir),
        ]
    )
    capsys.readouterr()

    seen: list[dict] = []

    def infer(text, prompt_contract, *args, **kwargs):
        seen.append(prompt_contract)
        return {"total": 9.99}

    monkeypatch.setattr(cli, "infer_contract", infer)
    code = cli.main(
        [
            str(source),
            "--format",
            "json",
            "--contract",
            str(contract),
            "--model",
            str(model),
            "--templates-dir",
            str(templates_dir),
            "--metrics",
        ]
    )

    assert code == 0
    captured = capsys.readouterr()
    assert json.loads(captured.out) == {"cliente": "ACME", "total": 9.99}
    assert list(seen[0]["properties"]) == ["total"]
    report = _last_report(captured)
    assert report["template"]["found"] is True
    assert report["extract"]["llm"] is True


def test_two_variants_of_the_same_contract_do_not_overwrite(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    contract = _contract(tmp_path)
    templates_dir = tmp_path / "templates"
    source = _source(tmp_path)
    model = _model(tmp_path)

    def homologate(blocks: list[LayoutBlock]) -> str:
        _mock(monkeypatch, blocks)
        monkeypatch.setattr(
            cli, "infer_contract", lambda *args, **kwargs: {"cliente": "ACME", "total": 9.99}
        )
        code = cli.main(
            [
                str(source),
                "--format",
                "json",
                "--contract",
                str(contract),
                "--model",
                str(model),
                "--homologate",
                "--templates-dir",
                str(templates_dir),
                "--metrics",
            ]
        )
        assert code == 0
        return _last_report(capsys.readouterr())["template"]["digest"]

    digest_one = homologate(_blocks())
    digest_two = homologate(_reordered_blocks())
    assert digest_one != digest_two

    def digest_for(blocks: list[LayoutBlock]) -> str:
        _mock(monkeypatch, blocks)
        code = cli.main(
            [
                str(source),
                "--format",
                "json",
                "--contract",
                str(contract),
                "--no-llm",
                "--templates-dir",
                str(templates_dir),
                "--metrics",
            ]
        )
        assert code == 0
        return _last_report(capsys.readouterr())["template"]["digest"]

    assert digest_for(_blocks()) == digest_one
    assert digest_for(_reordered_blocks()) == digest_two


def test_drift_falls_back_to_the_llm(monkeypatch, tmp_path: Path, capsys) -> None:
    contract = _contract(tmp_path)
    templates_dir = tmp_path / "templates"
    source = _source(tmp_path)
    model = _model(tmp_path)
    _mock(monkeypatch, _blocks())
    monkeypatch.setattr(
        cli, "infer_contract", lambda *args, **kwargs: {"cliente": "ACME", "total": 9.99}
    )
    cli.main(
        [
            str(source),
            "--format",
            "json",
            "--contract",
            str(contract),
            "--model",
            str(model),
            "--homologate",
            "--templates-dir",
            str(templates_dir),
        ]
    )
    capsys.readouterr()

    missing_value = [block for block in _blocks() if block.text != "9,99"]
    _mock(monkeypatch, missing_value)
    monkeypatch.setattr(
        cli, "infer_contract", lambda *args, **kwargs: {"cliente": "ACME", "total": 9.99}
    )
    code = cli.main(
        [
            str(source),
            "--format",
            "json",
            "--contract",
            str(contract),
            "--model",
            str(model),
            "--templates-dir",
            str(templates_dir),
            "--metrics",
        ]
    )

    assert code == 0
    captured = capsys.readouterr()
    assert "ya no cubre" in captured.err
    report = _last_report(captured)
    assert report["template"]["drift"] is True
    assert report["extract"]["llm"] is True


def test_without_homologate_nothing_is_written(monkeypatch, tmp_path: Path, capsys) -> None:
    _mock(monkeypatch, _blocks())
    contract = _contract(tmp_path)
    templates_dir = tmp_path / "templates"
    monkeypatch.setattr(
        cli, "infer_contract", lambda *args, **kwargs: {"cliente": "ACME", "total": 9.99}
    )

    code = cli.main(
        [
            str(_source(tmp_path)),
            "--format",
            "json",
            "--contract",
            str(contract),
            "--model",
            str(_model(tmp_path)),
            "--templates-dir",
            str(templates_dir),
        ]
    )

    assert code == 0
    assert not templates_dir.exists()


def test_no_template_disables_variants(monkeypatch, tmp_path: Path, capsys) -> None:
    contract = _contract(tmp_path)
    templates_dir = tmp_path / "templates"
    source = _source(tmp_path)
    model = _model(tmp_path)
    _mock(monkeypatch, _blocks())
    monkeypatch.setattr(
        cli, "infer_contract", lambda *args, **kwargs: {"cliente": "ACME", "total": 9.99}
    )
    cli.main(
        [
            str(source),
            "--format",
            "json",
            "--contract",
            str(contract),
            "--model",
            str(model),
            "--homologate",
            "--templates-dir",
            str(templates_dir),
        ]
    )
    capsys.readouterr()

    def infer(*args, **kwargs):
        return {"cliente": "ACME", "total": 9.99}

    monkeypatch.setattr(cli, "infer_contract", infer)
    code = cli.main(
        [
            str(source),
            "--format",
            "json",
            "--contract",
            str(contract),
            "--model",
            str(model),
            "--no-template",
            "--templates-dir",
            str(templates_dir),
            "--metrics",
        ]
    )

    assert code == 0
    report = _last_report(capsys.readouterr())
    assert report["template"]["found"] is False
    assert report["extract"]["llm"] is True


ANNOTATED = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "cliente": {"type": ["string", "null"], "x-labels": ["CLIENTE"]},
        "total": {"type": ["number", "null"], "x-labels": ["TOTAL"]},
    },
}


def test_annotations_fill_what_the_variant_does_not_cover(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    contract = _contract(tmp_path, ANNOTATED)
    templates_dir = tmp_path / "templates"
    source = _source(tmp_path)
    only_client = [_block("CLIENTE", 10, 0), _block("ACME", 100, 0)]
    _mock(monkeypatch, only_client)

    code = cli.main(
        [
            str(source),
            "--format",
            "json",
            "--contract",
            str(contract),
            "--homologate",
            "--templates-dir",
            str(templates_dir),
            "--metrics",
        ]
    )
    assert code == 0
    first = _last_report(capsys.readouterr())
    assert first["template"]["homologated"] is True
    assert first["extract"]["llm"] is False

    _mock(monkeypatch, _blocks())

    def boom(*args, **kwargs):
        raise AssertionError("las anotaciones deben rellenar el hueco")

    monkeypatch.setattr(cli, "infer_contract", boom)
    code = cli.main(
        [
            str(source),
            "--format",
            "json",
            "--contract",
            str(contract),
            "--no-llm",
            "--templates-dir",
            str(templates_dir),
            "--metrics",
        ]
    )

    assert code == 0
    captured = capsys.readouterr()
    assert json.loads(captured.out) == {"cliente": "ACME", "total": 9.99}
    report = _last_report(captured)
    assert report["template"]["found"] is True
    assert report["extract"]["llm"] is False


def test_irrelevant_rows_do_not_break_the_variant(monkeypatch, tmp_path: Path, capsys) -> None:
    contract = _contract(tmp_path)
    templates_dir = tmp_path / "templates"
    source = _source(tmp_path)
    _mock(monkeypatch, _blocks())
    monkeypatch.setattr(
        cli, "infer_contract", lambda *args, **kwargs: {"cliente": "ACME", "total": 9.99}
    )
    cli.main(
        [
            str(source),
            "--format",
            "json",
            "--contract",
            str(contract),
            "--model",
            str(_model(tmp_path)),
            "--homologate",
            "--templates-dir",
            str(templates_dir),
            "--metrics",
        ]
    )
    digest = _last_report(capsys.readouterr())["template"]["digest"]

    noisy = _blocks() + [
        _block("ACME PEDIDOS S.L.", 10, -30),
        _block("OBSERVACIONES", 10, 40),
        _block("entregar antes de las 18 h", 100, 40),
    ]
    _mock(monkeypatch, noisy)

    def boom(*args, **kwargs):
        raise AssertionError("el ruido irrelevante no debe alterar la variante")

    monkeypatch.setattr(cli, "infer_contract", boom)
    code = cli.main(
        [
            str(source),
            "--format",
            "json",
            "--contract",
            str(contract),
            "--no-llm",
            "--templates-dir",
            str(templates_dir),
            "--metrics",
        ]
    )

    assert code == 0
    captured = capsys.readouterr()
    assert json.loads(captured.out) == {"cliente": "ACME", "total": 9.99}
    report = _last_report(captured)
    assert report["template"]["found"] is True
    assert report["template"]["digest"] == digest


def test_homologate_excludes_non_literal_fields(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    _mock(monkeypatch, _blocks())
    contract = _contract(tmp_path)
    templates_dir = tmp_path / "templates"
    source = _source(tmp_path)
    monkeypatch.setattr(
        cli, "infer_contract", lambda *args, **kwargs: {"cliente": "ACME", "total": 12345.0}
    )
    code = cli.main(
        [
            str(source),
            "--format",
            "json",
            "--contract",
            str(contract),
            "--model",
            str(_model(tmp_path)),
            "--homologate",
            "--templates-dir",
            str(templates_dir),
            "--metrics",
        ]
    )
    assert code == 0
    first = _last_report(capsys.readouterr())
    assert first["template"]["homologated"] is True

    def boom(*args, **kwargs):
        raise AssertionError("el campo excluido no debe disparar el LLM con --no-llm")

    monkeypatch.setattr(cli, "infer_contract", boom)
    code = cli.main(
        [
            str(source),
            "--format",
            "json",
            "--contract",
            str(contract),
            "--no-llm",
            "--templates-dir",
            str(templates_dir),
            "--metrics",
        ]
    )

    assert code == 0
    captured = capsys.readouterr()
    assert json.loads(captured.out) == {"cliente": "ACME", "total": None}
    report = _last_report(captured)
    assert report["template"]["found"] is True
    assert report["extract"]["llm"] is False
