from __future__ import annotations

import io
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw

from vlm_ocr import cli
from vlm_ocr.types import LayoutBlock, PageInput

EXAMPLE = {"cliente": "ACME", "total": 1.5}
SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {"total": {"type": ["number", "null"], "x-labels": ["TOTAL"]}},
    "required": ["total"],
}


def _png_bytes() -> bytes:
    image = Image.new("RGB", (120, 60), "white")
    ImageDraw.Draw(image).text((10, 20), "STDIN", fill="black")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _model(tmp_path: Path) -> str:
    path = tmp_path / "m.gguf"
    path.write_bytes(b"")
    return str(path)


def _contract_file(tmp_path: Path, payload: dict) -> Path:
    path = tmp_path / "contrato.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _block(text: str, x0: float = 0.0, x1: float = 10.0) -> LayoutBlock:
    return LayoutBlock(0, text, 1.0, (x0, 0.0, x1, 10.0))


def _pipe(monkeypatch, raw: bytes) -> None:
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(raw)))


def _mock_file_pipeline(monkeypatch, blocks: list[LayoutBlock] | None = None) -> None:
    fixed = blocks or [_block("texto de prueba")]
    monkeypatch.setattr(
        cli, "ingest", lambda path, dpi=200: [PageInput(0, "texto de prueba", None)]
    )
    monkeypatch.setattr(cli, "ocr_pages", lambda pages, lang="default": fixed)


def test_two_stdin_inputs_return_2(capsys) -> None:
    code = cli.main(["-", "--format", "json", "--contract", "-"])

    assert code == 2
    assert "solo una entrada puede ser '-'" in capsys.readouterr().err


def test_stdin_tty_returns_2(monkeypatch, capsys) -> None:
    monkeypatch.setattr(cli.inputs, "stdin_is_tty", lambda: True)

    code = cli.main(["-"])

    assert code == 2
    assert "terminal" in capsys.readouterr().err


def test_stdin_png_markdown(monkeypatch, capsys) -> None:
    _pipe(monkeypatch, _png_bytes())
    monkeypatch.setattr(cli, "ocr_pages", lambda pages, lang="default": [_block("texto")])

    code = cli.main(["-"])

    assert code == 0
    assert "texto" in capsys.readouterr().out


def test_stdin_empty_returns_1(monkeypatch, capsys) -> None:
    _pipe(monkeypatch, b"")

    code = cli.main(["-"])

    assert code == 1
    assert "vacío" in capsys.readouterr().err


def test_stdin_unknown_kind_returns_1(monkeypatch, capsys) -> None:
    _pipe(monkeypatch, b"no soy un documento")

    code = cli.main(["-"])

    assert code == 1
    assert "--input-format" in capsys.readouterr().err


def test_input_format_rescues_unknown_bytes(monkeypatch, capsys) -> None:
    _pipe(monkeypatch, b"no soy un documento")
    monkeypatch.setattr(cli, "ocr_pages", lambda pages, lang="default": [_block("texto")])

    code = cli.main(["-", "--format", "json", "--input-format", "png"])

    assert code == 0
    assert json.loads(capsys.readouterr().out)["text"].strip() == "texto"


def test_input_format_ignored_for_file_warns(monkeypatch, tmp_path: Path, capsys) -> None:
    _mock_file_pipeline(monkeypatch)
    source = tmp_path / "captura.png"
    source.write_bytes(_png_bytes())

    code = cli.main([str(source), "--input-format", "png"])

    assert code == 0
    assert "se ignora" in capsys.readouterr().err


def test_contract_from_stdin(monkeypatch, tmp_path: Path, capsys) -> None:
    _mock_file_pipeline(monkeypatch)
    monkeypatch.setattr(
        cli, "infer_contract", lambda *a, **k: {"cliente": "ACME", "total": 2}
    )
    source = tmp_path / "doc.pdf"
    source.write_bytes(b"")
    _pipe(monkeypatch, b'{"cliente": "ACME", "total": 1.5}')

    code = cli.main(
        [
            str(source),
            "--format",
            "json",
            "--contract",
            "-",
            "--model",
            _model(tmp_path),
        ]
    )

    assert code == 0
    assert json.loads(capsys.readouterr().out) == {"cliente": "ACME", "total": 2}


def test_instructions_from_stdin_reach_the_llm(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    _mock_file_pipeline(monkeypatch)
    seen: dict[str, object] = {}

    def fake_infer(text, contract, kind, model_path, **kwargs):
        seen["instructions"] = kwargs.get("instructions")
        return {"cliente": "ACME", "total": 2}

    monkeypatch.setattr(cli, "infer_contract", fake_infer)
    source = tmp_path / "doc.pdf"
    source.write_bytes(b"")
    contract = _contract_file(tmp_path, EXAMPLE)
    _pipe(monkeypatch, b"usa TOTAL")

    code = cli.main(
        [
            str(source),
            "--format",
            "json",
            "--contract",
            str(contract),
            "--instructions",
            "-",
            "--model",
            _model(tmp_path),
        ]
    )

    assert code == 0
    assert seen["instructions"] == "usa TOTAL"


def test_stdin_contract_without_instructions_has_no_sidecar(
    monkeypatch, tmp_path: Path
) -> None:
    _mock_file_pipeline(monkeypatch)
    seen: dict[str, object] = {}

    def fake_infer(text, contract, kind, model_path, **kwargs):
        seen["instructions"] = kwargs.get("instructions")
        return {"cliente": "ACME", "total": 2}

    monkeypatch.setattr(cli, "infer_contract", fake_infer)
    source = tmp_path / "doc.pdf"
    source.write_bytes(b"")
    _pipe(monkeypatch, b'{"cliente": "ACME", "total": 1.5}')

    code = cli.main(
        [str(source), "--format", "json", "--contract", "-", "--model", _model(tmp_path)]
    )

    assert code == 0
    assert seen["instructions"] is None


def test_stdin_pdf_annotated_rows_without_llm(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    seen: dict[str, object] = {}

    def fake_ingest(path, dpi=200, *, data=None, kind=None):
        seen["data"] = data
        seen["kind"] = kind
        return [PageInput(0, "ignorado", None)]

    def fake_native_blocks(path, *, data=None):
        seen["native_data"] = data
        return [_block("TOTAL", 0.0, 40.0), _block("29.35", 200.0, 250.0)]

    monkeypatch.setattr(cli, "ingest", fake_ingest)
    monkeypatch.setattr(cli, "native_blocks", fake_native_blocks)
    monkeypatch.setattr(
        cli, "ocr_pages", lambda pages, lang="default": [_block("ignorado")]
    )
    contract = _contract_file(tmp_path, SCHEMA)
    _pipe(monkeypatch, b"%PDF-1.7\nresto")

    code = cli.main(
        [
            "-",
            "--format",
            "json",
            "--contract",
            str(contract),
            "--contract-kind",
            "schema",
            "--no-llm",
        ]
    )

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["total"] == 29.35
    assert seen["kind"] == "pdf"
    assert seen["data"] == b"%PDF-1.7\nresto"
    assert seen["native_data"] == b"%PDF-1.7\nresto"


def test_stdin_metrics(monkeypatch, tmp_path: Path) -> None:
    raw = _png_bytes()
    _pipe(monkeypatch, raw)
    monkeypatch.setattr(cli, "ocr_pages", lambda pages, lang="default": [_block("texto")])
    out = tmp_path / "metrics.json"

    code = cli.main(["-", "--metrics-out", str(out)])

    assert code == 0
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["file"]["path"] == "-"
    assert report["file"]["size_bytes"] == len(raw)
    assert report["file"]["format"] == "png"
