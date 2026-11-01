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
            "--homologate-partial",
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
            "--homologate-partial",
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


def _homologate_argv(tmp_path: Path, templates_dir: Path, *extra: str) -> list[str]:
    return [
        str(_source(tmp_path)),
        "--format", "json",
        "--contract", str(_contract(tmp_path)),
        "--model", str(_model(tmp_path)),
        "--templates-dir", str(templates_dir),
        *extra,
        "--metrics",
    ]


def _variant_files(templates_dir: Path) -> list[Path]:
    return sorted(templates_dir.glob("*/*.json")) if templates_dir.is_dir() else []


def test_homologate_blocked_when_fields_remain_unlocated(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    _mock(monkeypatch, _blocks())
    templates_dir = tmp_path / "templates"
    monkeypatch.setattr(
        cli, "infer_contract", lambda *args, **kwargs: {"cliente": "Inventado", "total": 9.99}
    )

    code = cli.main(_homologate_argv(tmp_path, templates_dir, "--homologate"))

    assert code == 0
    captured = capsys.readouterr()
    assert "--homologate-partial" in captured.err
    report = _last_report(captured)
    assert report["template"]["blocked"] is True
    assert report["template"]["homologated"] is False
    assert _variant_files(templates_dir) == []


def test_homologate_partial_saves_only_located_fields(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    _mock(monkeypatch, _blocks())
    templates_dir = tmp_path / "templates"
    monkeypatch.setattr(
        cli, "infer_contract", lambda *args, **kwargs: {"cliente": "Inventado", "total": 9.99}
    )

    code = cli.main(
        _homologate_argv(tmp_path, templates_dir, "--homologate", "--homologate-partial")
    )

    assert code == 0
    report = _last_report(capsys.readouterr())
    assert report["template"]["homologated"] is True
    assert report["template"]["fields_mapped"] == 1
    assert report["template"]["fields_unlocated"] >= 1
    files = _variant_files(templates_dir)
    assert len(files) == 1
    saved = json.loads(files[0].read_text(encoding="utf-8"))
    assert "total" in saved["map"]
    assert "cliente" not in saved["map"]


def test_homologate_report_writes_without_saving(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    _mock(monkeypatch, _blocks())
    templates_dir = tmp_path / "templates"
    report_path = tmp_path / "mapa.json"
    monkeypatch.setattr(
        cli, "infer_contract", lambda *args, **kwargs: {"cliente": "ACME", "total": 9.99}
    )

    code = cli.main(
        _homologate_argv(tmp_path, templates_dir, "--homologate-report", str(report_path))
    )

    assert code == 0
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["digest"]
    assert payload["map"]["total"]["labels"] == ["TOTAL"]
    assert payload["blocked"] is False
    assert payload["saved"] is False
    assert _variant_files(templates_dir) == []


def test_homologate_report_with_save(monkeypatch, tmp_path: Path, capsys) -> None:
    _mock(monkeypatch, _blocks())
    templates_dir = tmp_path / "templates"
    report_path = tmp_path / "mapa.json"
    monkeypatch.setattr(
        cli, "infer_contract", lambda *args, **kwargs: {"cliente": "ACME", "total": 9.99}
    )

    code = cli.main(
        _homologate_argv(
            tmp_path, templates_dir, "--homologate", "--homologate-report", str(report_path)
        )
    )

    assert code == 0
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["saved"] is True
    assert len(_variant_files(templates_dir)) == 1


def test_report_includes_contract_coverage(monkeypatch, tmp_path: Path, capsys) -> None:
    _mock(monkeypatch, _blocks())
    monkeypatch.setattr(
        cli, "infer_contract", lambda *args, **kwargs: {"cliente": "ACME", "total": 9.99}
    )

    code = cli.main(
        [
            str(_source(tmp_path)),
            "--format", "json",
            "--contract", str(_contract(tmp_path)),
            "--model", str(_model(tmp_path)),
            "--metrics",
        ]
    )

    assert code == 0
    report = _last_report(capsys.readouterr())
    assert report["extract"]["fields_total"] == 2
    assert report["extract"]["fields_filled"] == 2
    assert report["extract"]["coverage_contract"] == 1.0


def _saved_variant(templates_dir: Path, contract_hash: str = "c" * 64):
    from vlm_ocr import templates

    fingerprint = templates.signature(_blocks(), ["CLIENTE", "TOTAL"])
    assert fingerprint is not None
    template = templates.Template(
        contract_hash=contract_hash,
        fingerprint=fingerprint,
        map={
            "cliente": templates.FieldMap(labels=("CLIENTE",)),
            "total": templates.FieldMap(labels=("TOTAL",), source="devengado"),
        },
        unlocated=("hora",),
    )
    return templates.save_template(fingerprint, template, directory=templates_dir)


def test_templates_list_prints_the_variant(capsys, tmp_path: Path) -> None:
    saved = _saved_variant(tmp_path / "t")

    assert cli.main(["templates", "list", "--templates-dir", str(tmp_path / "t")]) == 0

    out = capsys.readouterr().out
    assert saved.digest[:12] in out
    assert "CONTRATO" in out


def test_templates_list_json(capsys, tmp_path: Path) -> None:
    saved = _saved_variant(tmp_path / "t")

    assert cli.main(
        ["templates", "list", "--json", "--templates-dir", str(tmp_path / "t")]
    ) == 0

    rows = json.loads(capsys.readouterr().out)
    assert len(rows) == 1
    assert rows[0]["digest"] == saved.digest
    assert rows[0]["fields_mapped"] == 2
    assert rows[0]["fields_unlocated"] == 1


def test_templates_show_by_prefix(capsys, tmp_path: Path) -> None:
    saved = _saved_variant(tmp_path / "t")

    assert cli.main(
        ["templates", "show", saved.digest[:8], "--templates-dir", str(tmp_path / "t")]
    ) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["digest"] == saved.digest
    assert "total" in payload["map"]


def test_templates_show_unknown_prefix(capsys, tmp_path: Path) -> None:
    _saved_variant(tmp_path / "t")

    assert cli.main(["templates", "show", "zzzz", "--templates-dir", str(tmp_path / "t")]) == 2
    assert "no hay variante" in capsys.readouterr().err


def test_templates_drop_requires_yes(capsys, tmp_path: Path) -> None:
    saved = _saved_variant(tmp_path / "t")
    path = tmp_path / "t" / saved.contract_hash / f"{saved.digest}.json"

    assert cli.main(
        ["templates", "drop", saved.digest[:8], "--templates-dir", str(tmp_path / "t")]
    ) == 2
    assert path.is_file()
    assert "--yes" in capsys.readouterr().err


def test_templates_drop_removes_variant_and_keeps_history(capsys, tmp_path: Path) -> None:
    first = _saved_variant(tmp_path / "t")
    _saved_variant(tmp_path / "t")
    folder = tmp_path / "t" / first.contract_hash
    history = folder / "history" / f"{first.digest}.v1.json"

    assert cli.main(
        [
            "templates", "drop", first.digest[:8], "--yes",
            "--templates-dir", str(tmp_path / "t"),
        ]
    ) == 0

    assert not (folder / f"{first.digest}.json").exists()
    assert history.is_file()
    assert "variante eliminada" in capsys.readouterr().out


def test_templates_without_command_shows_help(capsys) -> None:
    assert cli.main(["templates"]) == 2
    assert "list" in capsys.readouterr().err


def test_ticket_regression_does_not_homologate_a_doubtful_map(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    blocks = [
        _block("TRANS #:", 10, 0),
        _block("064 2 1404 2022", 200, 0),
        _block("AMOUNT DUE", 10, 12),
        _block("29,35", 200, 12),
    ]
    _mock(monkeypatch, blocks)
    contract = tmp_path / "ticket.json"
    contract.write_text(
        json.dumps(
            {
                "fecha": "",
                "hora": "",
                "pedido": [{"producto": "", "observaciones": "", "precio": 0.0}],
                "total": 0.0,
            }
        ),
        encoding="utf-8",
    )
    templates_dir = tmp_path / "templates"
    monkeypatch.setattr(
        cli,
        "infer_contract",
        lambda *args, **kwargs: {
            "fecha": "2022",
            "hora": None,
            "pedido": [{"producto": "Hamburger", "observaciones": None, "precio": 3.6}],
            "total": 29.35,
        },
    )

    code = cli.main(
        [
            str(_source(tmp_path)),
            "--format", "json",
            "--contract", str(contract),
            "--model", str(_model(tmp_path)),
            "--homologate",
            "--templates-dir", str(templates_dir),
            "--metrics",
        ]
    )

    assert code == 0
    report = _last_report(capsys.readouterr())
    assert report["template"]["blocked"] is True
    assert report["template"]["homologated"] is False
    assert _variant_files(templates_dir) == []


ITEM_CONTRACT = {
    "type": "object",
    "properties": {
        "pedido": {
            "type": ["array", "null"],
            "items": {
                "type": "object",
                "properties": {
                    "producto": {"type": "string"},
                    "cantidad": {"type": ["integer", "null"]},
                    "precio": {"type": ["number", "null"]},
                    "observaciones": {"type": ["string", "null"]},
                },
            },
        },
        "total": {"type": ["number", "null"]},
    },
}


def _item_block(text: str, x: float, y: float) -> LayoutBlock:
    return LayoutBlock(0, text, 1.0, (x, y, x + 90.0, y + 10.0))


def _item_blocks() -> list[LayoutBlock]:
    return [
        _item_block("1 Burger", 10, 0),
        _item_block("5.00", 200, 0),
        _item_block("- Pickle", 20, 12),
        _item_block("2 Fries", 10, 24),
        _item_block("4.00", 200, 24),
        _item_block("COUNTER", 10, 36),
        _item_block("9.00", 200, 36),
    ]


def _item_data() -> dict:
    return {
        "pedido": [
            {
                "producto": "Burger",
                "cantidad": 1,
                "precio": 5.0,
                "observaciones": "- Pickle",
            },
            {
                "producto": "Fries",
                "cantidad": 2,
                "precio": 4.0,
                "observaciones": None,
            },
        ],
        "total": 9.0,
    }


def test_homologate_items_then_zero_token_run(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    blocks = _item_blocks()
    _mock(monkeypatch, blocks)
    contract = tmp_path / "ticket.json"
    contract.write_text(json.dumps(ITEM_CONTRACT), encoding="utf-8")
    templates_dir = tmp_path / "templates"
    monkeypatch.setattr(cli, "infer_contract", lambda *a, **k: _item_data())
    source = _source(tmp_path)
    model = _model(tmp_path)

    code = cli.main(
        [
            str(source),
            "--format", "json",
            "--contract", str(contract),
            "--contract-kind", "schema",
            "--model", str(model),
            "--templates-dir", str(templates_dir),
            "--homologate",
            "--metrics",
        ]
    )

    assert code == 0
    report = _last_report(capsys.readouterr())
    assert report["template"]["homologated"] is True
    assert report["template"]["items_mapped"] == 1

    code = cli.main(
        [
            str(source),
            "--format", "json",
            "--contract", str(contract),
            "--contract-kind", "schema",
            "--templates-dir", str(templates_dir),
            "--no-llm",
            "--metrics",
        ]
    )

    assert code == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["pedido"][0]["producto"] == "Burger"
    assert payload["pedido"][1]["cantidad"] == 2
    assert payload["total"] == 9.0
    report = _last_report(captured)
    assert report["template"]["found"] is True
    assert report["extract"]["llm"] is False
