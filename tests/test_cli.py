from __future__ import annotations

import json
from pathlib import Path

import pytest

from vlm_ocr import cli
from vlm_ocr.types import LayoutBlock, PageInput

EXAMPLE = {"cliente": "ACME", "total": 1.5}


def _contract_file(tmp_path: Path, payload: dict) -> Path:
    path = tmp_path / "contrato.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _mock_pipeline(monkeypatch, blocks: list[LayoutBlock] | None = None) -> None:
    fixed = blocks or [LayoutBlock(0, "texto de prueba", 1.0, (0.0, 0.0, 1.0, 1.0))]
    monkeypatch.setattr(cli, "ingest", lambda path, dpi=200: [PageInput(0, "texto de prueba", None)])
    monkeypatch.setattr(cli, "ocr_pages", lambda pages, lang="default": fixed)


def test_help_exits_zero_and_mentions_contract_kind(capsys) -> None:
    with pytest.raises(SystemExit) as exc:
        cli.main(["--help"])

    assert exc.value.code == 0
    assert "--contract-kind" in capsys.readouterr().out


def test_markdown_is_default(monkeypatch, tmp_path: Path, capsys) -> None:
    _mock_pipeline(monkeypatch)
    source = tmp_path / "doc.pdf"
    source.write_bytes(b"")

    code = cli.main([str(source)])

    assert code == 0
    assert "texto de prueba" in capsys.readouterr().out


def test_json_without_model_returns_2(monkeypatch, tmp_path: Path, capsys) -> None:
    _mock_pipeline(monkeypatch)
    source = tmp_path / "doc.pdf"
    source.write_bytes(b"")
    contract = _contract_file(tmp_path, EXAMPLE)

    code = cli.main([str(source), "--format", "json", "--contract", str(contract)])

    assert code == 2
    assert "model" in capsys.readouterr().err


def test_json_without_contract_returns_text(monkeypatch, tmp_path: Path, capsys) -> None:
    _mock_pipeline(monkeypatch)
    source = tmp_path / "doc.pdf"
    source.write_bytes(b"")

    code = cli.main([str(source), "--format", "json"])

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {"text": "texto de prueba"}


def test_json_without_contract_with_layout(monkeypatch, tmp_path: Path, capsys) -> None:
    _mock_pipeline(monkeypatch)
    source = tmp_path / "doc.pdf"
    source.write_bytes(b"")

    code = cli.main([str(source), "--format", "json", "--with-layout"])

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["text"] == "texto de prueba"
    assert payload["layout"][0]["text"] == "texto de prueba"


def test_json_without_contract_does_not_need_model(monkeypatch, tmp_path: Path, capsys) -> None:
    _mock_pipeline(monkeypatch)
    source = tmp_path / "doc.pdf"
    source.write_bytes(b"")

    code = cli.main([str(source), "--format", "json"])

    assert code == 0
    assert "model" not in capsys.readouterr().err


def test_json_success_emits_contract_shaped_payload(monkeypatch, tmp_path: Path, capsys) -> None:
    _mock_pipeline(monkeypatch)
    monkeypatch.setattr(cli, "infer_contract", lambda *a, **k: {"cliente": "ACME", "total": 2})
    source = tmp_path / "doc.pdf"
    source.write_bytes(b"")
    contract = _contract_file(tmp_path, EXAMPLE)

    code = cli.main(
        [str(source), "--format", "json", "--contract", str(contract), "--model", "m.gguf"]
    )

    assert code == 0
    assert json.loads(capsys.readouterr().out) == {"cliente": "ACME", "total": 2}


def test_with_layout_wraps_data_and_layout(monkeypatch, tmp_path: Path, capsys) -> None:
    _mock_pipeline(monkeypatch)
    monkeypatch.setattr(cli, "infer_contract", lambda *a, **k: {"cliente": "ACME", "total": 2})
    source = tmp_path / "doc.pdf"
    source.write_bytes(b"")
    contract = _contract_file(tmp_path, EXAMPLE)

    code = cli.main(
        [
            str(source),
            "--format",
            "json",
            "--contract",
            str(contract),
            "--model",
            "m.gguf",
            "--with-layout",
        ]
    )

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["data"] == {"cliente": "ACME", "total": 2}
    assert payload["layout"][0]["text"] == "texto de prueba"


def test_dpi_and_lang_are_forwarded(monkeypatch, tmp_path: Path) -> None:
    seen: dict[str, object] = {}

    def fake_ingest(path, dpi=200):
        seen["dpi"] = dpi
        return [PageInput(0, "texto", None)]

    def fake_ocr(pages, lang="default"):
        seen["lang"] = lang
        return [LayoutBlock(0, "texto", 1.0, (0.0, 0.0, 0.0, 0.0))]

    monkeypatch.setattr(cli, "ingest", fake_ingest)
    monkeypatch.setattr(cli, "ocr_pages", fake_ocr)
    source = tmp_path / "doc.pdf"
    source.write_bytes(b"")

    cli.main([str(source), "--dpi", "150", "--lang", "es"])

    assert seen == {"dpi": 150, "lang": "es"}


def test_out_writes_file_instead_of_stdout(monkeypatch, tmp_path: Path, capsys) -> None:
    _mock_pipeline(monkeypatch)
    source = tmp_path / "doc.pdf"
    source.write_bytes(b"")
    target = tmp_path / "salida.md"

    code = cli.main([str(source), "--out", str(target)])

    assert code == 0
    assert target.read_text(encoding="utf-8") == "texto de prueba"
    assert capsys.readouterr().out == ""


def test_contract_kind_schema_overrides_detection(monkeypatch, tmp_path: Path) -> None:
    _mock_pipeline(monkeypatch)
    seen: dict[str, object] = {}

    def fake_infer(text, contract, kind, model_path, **kwargs):
        seen["kind"] = kind
        return {"cliente": "ACME", "total": 2}

    monkeypatch.setattr(cli, "infer_contract", fake_infer)
    source = tmp_path / "doc.pdf"
    source.write_bytes(b"")
    schema_without_marker = {
        "type": "object",
        "properties": {"cliente": {"type": "string"}, "total": {"type": "number"}},
        "required": ["cliente", "total"],
    }
    contract = _contract_file(tmp_path, schema_without_marker)

    code = cli.main(
        [
            str(source),
            "--format",
            "json",
            "--contract",
            str(contract),
            "--model",
            "m.gguf",
            "--contract-kind",
            "schema",
        ]
    )

    assert code == 0
    assert seen["kind"] == "schema"


def test_missing_file_returns_1(tmp_path: Path, capsys) -> None:
    code = cli.main([str(tmp_path / "no-existe.pdf")])

    assert code == 1
    assert capsys.readouterr().err


def test_instructions_without_contract_returns_2(monkeypatch, tmp_path: Path, capsys) -> None:
    _mock_pipeline(monkeypatch)
    source = tmp_path / "doc.pdf"
    source.write_bytes(b"")

    code = cli.main([str(source), "--format", "json", "--instructions", "x.md"])

    assert code == 2
    assert "contract" in capsys.readouterr().err


def test_missing_explicit_instructions_returns_2(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    _mock_pipeline(monkeypatch)
    source = tmp_path / "doc.pdf"
    source.write_bytes(b"")
    contract = _contract_file(tmp_path, EXAMPLE)

    code = cli.main(
        [
            str(source),
            "--format",
            "json",
            "--contract",
            str(contract),
            "--model",
            "m.gguf",
            "--instructions",
            str(tmp_path / "no-existe.md"),
        ]
    )

    assert code == 2
    assert "no existe" in capsys.readouterr().err


def test_auto_sidecar_is_forwarded(monkeypatch, tmp_path: Path, capsys) -> None:
    _mock_pipeline(monkeypatch)
    seen: dict[str, object] = {}

    def fake_infer(text, contract, kind, model_path, **kwargs):
        seen["instructions"] = kwargs.get("instructions")
        return {"cliente": "ACME", "total": 2}

    monkeypatch.setattr(cli, "infer_contract", fake_infer)
    source = tmp_path / "doc.pdf"
    source.write_bytes(b"")
    contract = _contract_file(tmp_path, EXAMPLE)
    (tmp_path / "contrato.prompt.md").write_text("AJUSTE AUTO", encoding="utf-8")

    code = cli.main(
        [str(source), "--format", "json", "--contract", str(contract), "--model", "m.gguf"]
    )

    assert code == 0
    assert seen["instructions"] == "AJUSTE AUTO"


def test_explicit_instructions_override_sidecar(monkeypatch, tmp_path: Path) -> None:
    _mock_pipeline(monkeypatch)
    seen: dict[str, object] = {}

    def fake_infer(text, contract, kind, model_path, **kwargs):
        seen["instructions"] = kwargs.get("instructions")
        return {"cliente": "ACME", "total": 2}

    monkeypatch.setattr(cli, "infer_contract", fake_infer)
    source = tmp_path / "doc.pdf"
    source.write_bytes(b"")
    contract = _contract_file(tmp_path, EXAMPLE)
    (tmp_path / "contrato.prompt.md").write_text("AUTO", encoding="utf-8")
    explicit = tmp_path / "otro.md"
    explicit.write_text("EXPLICITO", encoding="utf-8")

    code = cli.main(
        [
            str(source),
            "--format",
            "json",
            "--contract",
            str(contract),
            "--model",
            "m.gguf",
            "--instructions",
            str(explicit),
        ]
    )

    assert code == 0
    assert seen["instructions"] == "EXPLICITO"
