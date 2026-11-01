from __future__ import annotations

import json
from pathlib import Path

import pytest

from vlm_ocr import cli
from vlm_ocr.types import LayoutBlock, PageInput

EXAMPLE = {"cliente": "ACME", "total": 1.5}


def _model(tmp_path: Path) -> str:
    path = tmp_path / "m.gguf"
    path.write_bytes(b"")
    return str(path)


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


def test_json_without_model_uses_default(monkeypatch, tmp_path: Path, capsys) -> None:
    _mock_pipeline(monkeypatch)
    default = tmp_path / "default.gguf"
    default.write_bytes(b"")
    monkeypatch.setattr(cli, "default_model_path", lambda: default)
    monkeypatch.setattr(cli, "infer_contract", lambda *a, **k: {"cliente": "ACME", "total": 2})
    source = tmp_path / "doc.pdf"
    source.write_bytes(b"")
    contract = _contract_file(tmp_path, EXAMPLE)

    code = cli.main([str(source), "--format", "json", "--contract", str(contract)])

    assert code == 0
    assert json.loads(capsys.readouterr().out) == {"cliente": "ACME", "total": 2}


def test_json_without_model_and_without_default_returns_2(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    _mock_pipeline(monkeypatch)
    monkeypatch.setattr(cli, "default_model_path", lambda: None)
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
        [str(source), "--format", "json", "--contract", str(contract), "--model", _model(tmp_path)]
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
            _model(tmp_path),
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
            _model(tmp_path),
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
            _model(tmp_path),
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
        [str(source), "--format", "json", "--contract", str(contract), "--model", _model(tmp_path)]
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
            _model(tmp_path),
            "--instructions",
            str(explicit),
        ]
    )

    assert code == 0
    assert seen["instructions"] == "EXPLICITO"


def test_malformed_contract_returns_2(monkeypatch, tmp_path: Path, capsys) -> None:
    _mock_pipeline(monkeypatch)
    source = tmp_path / "doc.pdf"
    source.write_bytes(b"")
    bad = tmp_path / "bad.json"
    bad.write_text("{ malformado", encoding="utf-8")

    code = cli.main(
        [str(source), "--format", "json", "--contract", str(bad), "--model", _model(tmp_path)]
    )

    assert code == 2
    assert "contrato" in capsys.readouterr().err


def test_missing_contract_returns_2(monkeypatch, tmp_path: Path, capsys) -> None:
    _mock_pipeline(monkeypatch)
    source = tmp_path / "doc.pdf"
    source.write_bytes(b"")

    code = cli.main(
        [
            str(source),
            "--format",
            "json",
            "--contract",
            str(tmp_path / "no-existe.json"),
            "--model",
            _model(tmp_path),
        ]
    )

    assert code == 2
    assert "contrato" in capsys.readouterr().err


def test_missing_explicit_model_returns_2(monkeypatch, tmp_path: Path, capsys) -> None:
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
            str(tmp_path / "no-existe.gguf"),
        ]
    )

    assert code == 2
    assert "modelo" in capsys.readouterr().err


def test_invalid_schema_returns_2(monkeypatch, tmp_path: Path, capsys) -> None:
    _mock_pipeline(monkeypatch)
    source = tmp_path / "doc.pdf"
    source.write_bytes(b"")
    schema = tmp_path / "schema.json"
    schema.write_text(
        json.dumps({"$schema": "https://json-schema.org/draft/2020-12/schema", "type": 123}),
        encoding="utf-8",
    )

    code = cli.main(
        [str(source), "--format", "json", "--contract", str(schema), "--model", _model(tmp_path)]
    )

    assert code == 2
    assert "schema" in capsys.readouterr().err.lower()


def test_corrupt_pdf_returns_1_without_traceback(tmp_path: Path, capsys) -> None:
    source = tmp_path / "corrupto.pdf"
    source.write_bytes(b"no es un pdf")

    code = cli.main([str(source)])

    assert code == 1
    err = capsys.readouterr().err
    assert "error" in err
    assert "Traceback" not in err


def test_contract_flags_without_json_format_return_2(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    def boom(*args, **kwargs):
        raise AssertionError("no debe procesar el fichero")

    monkeypatch.setattr(cli, "ingest", boom)
    source = tmp_path / "doc.pdf"
    source.write_bytes(b"")
    contract = _contract_file(tmp_path, EXAMPLE)
    model = tmp_path / "m.gguf"
    model.write_bytes(b"")

    code = cli.main([str(source), "--contract", str(contract)])
    assert code == 2
    assert "--format json" in capsys.readouterr().err

    code = cli.main([str(source), "--model", str(model)])
    assert code == 2
    assert "--format json" in capsys.readouterr().err


ROWS_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "nomina": {
            "type": "object",
            "properties": {
                "devengos": {
                    "type": "object",
                    "properties": {
                        "salario_base": {
                            "type": ["number", "null"],
                            "x-labels": ["SALARIO BASE"],
                            "x-source": "devengado",
                        }
                    },
                }
            },
        }
    },
}

PARTIAL_SCHEMA = {
    **ROWS_SCHEMA,
    "properties": {
        "nomina": {
            "type": "object",
            "properties": {
                "devengos": {
                    "type": "object",
                    "properties": {
                        **ROWS_SCHEMA["properties"]["nomina"]["properties"]["devengos"]["properties"],
                        "horas_extras": {
                            "type": ["number", "null"],
                            "x-labels": ["HORAS EXTRAS"],
                            "x-source": "devengado",
                        },
                    },
                }
            },
        }
    },
}


def _row_blocks() -> list[LayoutBlock]:
    return [
        LayoutBlock(0, "Concepto", 1.0, (10.0, 10.0, 60.0, 20.0)),
        LayoutBlock(0, "Unidades", 1.0, (100.0, 10.0, 140.0, 20.0)),
        LayoutBlock(0, "Importe", 1.0, (160.0, 10.0, 200.0, 20.0)),
        LayoutBlock(0, "Devengado", 1.0, (220.0, 10.0, 280.0, 20.0)),
        LayoutBlock(0, "SALARIO BASE", 1.0, (10.0, 30.0, 90.0, 40.0)),
        LayoutBlock(0, "30,00", 1.0, (100.0, 30.0, 130.0, 40.0)),
        LayoutBlock(0, "80,2297", 1.0, (160.0, 30.0, 200.0, 40.0)),
        LayoutBlock(0, "2.406,89", 1.0, (220.0, 30.0, 280.0, 40.0)),
    ]


def _annotated(monkeypatch, tmp_path: Path, schema: dict | None = None) -> Path:
    chosen = schema or ROWS_SCHEMA
    _mock_pipeline(monkeypatch)
    monkeypatch.setattr(cli, "native_blocks", lambda path: _row_blocks())
    monkeypatch.setattr(cli, "load_contract", lambda path: (chosen, "schema"))
    monkeypatch.setattr(cli, "load_instructions", lambda *args, **kwargs: None)
    return _contract_file(tmp_path, chosen)


def test_annotated_contract_uses_rows_and_skips_the_llm(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    contract = _annotated(monkeypatch, tmp_path)

    def boom(*args, **kwargs):
        raise AssertionError("no debe llamarse al LLM")

    monkeypatch.setattr(cli, "infer_contract", boom)
    source = tmp_path / "doc.pdf"
    source.write_bytes(b"")

    code = cli.main(
        [str(source), "--format", "json", "--contract", str(contract), "--metrics"]
    )

    assert code == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["nomina"]["devengos"]["salario_base"] == 2406.89
    report = json.loads(captured.err)
    assert report["extract"]["deterministic"] == 1
    assert report["extract"]["unmatched"] == 0
    assert report["extract"]["llm"] is False
    assert report["verify"]["errors"] == []


def test_no_llm_does_not_require_a_model(monkeypatch, tmp_path: Path, capsys) -> None:
    contract = _annotated(monkeypatch, tmp_path, PARTIAL_SCHEMA)
    monkeypatch.setattr(cli, "default_model_path", lambda: None)
    source = tmp_path / "doc.pdf"
    source.write_bytes(b"")

    code = cli.main(
        [str(source), "--format", "json", "--contract", str(contract), "--no-llm", "--metrics"]
    )

    assert code == 0
    captured = capsys.readouterr()
    report = json.loads(captured.err.strip().splitlines()[-1])
    assert report["llm"]["enabled"] is False
    assert report["extract"]["llm"] is False


def test_strict_fails_when_a_value_is_not_in_the_text(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    _mock_pipeline(monkeypatch, blocks=[LayoutBlock(0, "sin cifras", 1.0, (0.0, 0.0, 1.0, 1.0))])
    monkeypatch.setattr(cli, "infer_contract", lambda *args, **kwargs: {"cliente": "ACME", "total": 1e15})
    source = tmp_path / "doc.pdf"
    source.write_bytes(b"")

    code = cli.main(
        [
            str(source),
            "--format",
            "json",
            "--contract",
            str(_contract_file(tmp_path, EXAMPLE)),
            "--model",
            _model(tmp_path),
            "--strict",
        ]
    )

    assert code == 2
    assert "no aparecen en el texto" in capsys.readouterr().err


def test_without_strict_a_literal_mismatch_only_warns(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    _mock_pipeline(monkeypatch, blocks=[LayoutBlock(0, "sin cifras", 1.0, (0.0, 0.0, 1.0, 1.0))])
    monkeypatch.setattr(cli, "infer_contract", lambda *args, **kwargs: {"cliente": "ACME", "total": 1e15})
    source = tmp_path / "doc.pdf"
    source.write_bytes(b"")

    code = cli.main(
        [
            str(source),
            "--format",
            "json",
            "--contract",
            str(_contract_file(tmp_path, EXAMPLE)),
            "--model",
            _model(tmp_path),
        ]
    )

    assert code == 0
    assert "aviso:" in capsys.readouterr().err


def test_absent_fields_do_not_trigger_the_llm(monkeypatch, tmp_path: Path, capsys) -> None:
    contract = _annotated(monkeypatch, tmp_path, PARTIAL_SCHEMA)

    def boom(*args, **kwargs):
        raise AssertionError("no debe llamarse al LLM por campos ausentes")

    monkeypatch.setattr(cli, "infer_contract", boom)
    monkeypatch.setattr(cli, "default_model_path", lambda: tmp_path / "nada.gguf")
    source = tmp_path / "doc.pdf"
    source.write_bytes(b"")

    code = cli.main(
        [str(source), "--format", "json", "--contract", str(contract), "--metrics"]
    )

    assert code == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["nomina"]["devengos"]["horas_extras"] is None
    report = json.loads(captured.err.strip().splitlines()[-1])
    assert report["extract"]["llm"] is False


def test_low_coverage_warns(monkeypatch, tmp_path: Path, capsys) -> None:
    _mock_pipeline(monkeypatch)
    monkeypatch.setattr(cli, "native_blocks", lambda path: _row_blocks())
    monkeypatch.setattr(cli, "load_contract", lambda path: (PARTIAL_SCHEMA, "schema"))
    monkeypatch.setattr(cli, "load_instructions", lambda *args, **kwargs: None)
    monkeypatch.setattr(cli, "default_model_path", lambda: None)
    source = tmp_path / "doc.pdf"
    source.write_bytes(b"")
    contract = _contract_file(tmp_path, PARTIAL_SCHEMA)

    code = cli.main(
        [str(source), "--format", "json", "--contract", str(contract), "--no-llm", "--metrics"]
    )

    assert code == 0
    captured = capsys.readouterr()
    assert "cobertura baja: 1/2" in captured.err
    assert json.loads(captured.err.strip().splitlines()[-1])["extract"]["coverage"] == 0.5


def test_low_coverage_fails_with_strict(monkeypatch, tmp_path: Path, capsys) -> None:
    _mock_pipeline(monkeypatch)
    monkeypatch.setattr(cli, "native_blocks", lambda path: _row_blocks())
    monkeypatch.setattr(cli, "load_contract", lambda path: (PARTIAL_SCHEMA, "schema"))
    monkeypatch.setattr(cli, "load_instructions", lambda *args, **kwargs: None)
    source = tmp_path / "doc.pdf"
    source.write_bytes(b"")
    contract = _contract_file(tmp_path, PARTIAL_SCHEMA)

    code = cli.main(
        [
            str(source),
            "--format",
            "json",
            "--contract",
            str(contract),
            "--no-llm",
            "--strict",
        ]
    )

    assert code == 2
    assert "cobertura baja" in capsys.readouterr().err


def test_strict_fails_on_an_invented_string(monkeypatch, tmp_path: Path, capsys) -> None:
    _mock_pipeline(monkeypatch, blocks=[LayoutBlock(0, "sin nombres", 1.0, (0.0, 0.0, 1.0, 1.0))])
    monkeypatch.setattr(cli, "infer_contract", lambda *args, **kwargs: {"cliente": "ACME", "total": 2})
    source = tmp_path / "doc.pdf"
    source.write_bytes(b"")

    code = cli.main(
        [str(source), "--format", "json", "--contract",
         str(_contract_file(tmp_path, EXAMPLE)), "--model", _model(tmp_path), "--strict"]
    )

    assert code == 2
    assert "no aparecen en el texto" in capsys.readouterr().err


def test_without_strict_an_invented_string_only_warns(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    _mock_pipeline(monkeypatch, blocks=[LayoutBlock(0, "sin nombres", 1.0, (0.0, 0.0, 1.0, 1.0))])
    monkeypatch.setattr(cli, "infer_contract", lambda *args, **kwargs: {"cliente": "ACME", "total": 2})
    source = tmp_path / "doc.pdf"
    source.write_bytes(b"")

    code = cli.main(
        [str(source), "--format", "json", "--contract",
         str(_contract_file(tmp_path, EXAMPLE)), "--model", _model(tmp_path)]
    )

    assert code == 0
    err = capsys.readouterr().err
    assert "aviso: cliente:" in err
    assert "ACME" in err
