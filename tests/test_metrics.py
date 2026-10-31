from __future__ import annotations

import json
from pathlib import Path

import pytest

from vlm_ocr import cli, metrics
from vlm_ocr.errors import ContractError, InputError
from vlm_ocr.types import LayoutBlock, PageInput

EXAMPLE = {"cliente": "ACME"}


def _block(page: int, text: str, confidence: float = 1.0) -> LayoutBlock:
    return LayoutBlock(page, text, confidence, (0.0, 0.0, 1.0, 1.0))


def _mock_pipeline(monkeypatch, pages: list[PageInput] | None = None) -> None:
    pages = pages or [PageInput(0, "texto de prueba", None)]
    monkeypatch.setattr(cli, "ingest", lambda path, dpi=200: pages)
    monkeypatch.setattr(
        cli,
        "ocr_pages",
        lambda items, lang="default": [_block(page.index, "texto de prueba") for page in items],
    )


def _source(tmp_path: Path, size: int = 10) -> Path:
    path = tmp_path / "doc.pdf"
    path.write_bytes(b"x" * size)
    return path


def test_empty_report_has_stable_shape() -> None:
    report = metrics.empty_report()

    assert report["llm"]["enabled"] is False
    assert report["llm"]["model"] is None
    assert report["file"]["pages"] is None
    assert report["llm"]["finish_reason"] is None
    assert report["error"] is None
    assert report["extract"] == {
        "deterministic": None,
        "llm": False,
        "unmatched": None,
        "pending": None,
        "coverage": None,
    }
    assert report["verify"] == {"errors": []}
    assert set(report) == {
        "file",
        "ingest",
        "ocr",
        "llm",
        "output",
        "extract",
        "verify",
        "total",
        "error",
    }


def test_mean_confidence_ignores_native_blocks() -> None:
    blocks = [_block(0, "nativo"), _block(1, "a", 0.9), _block(1, "b", 0.7)]

    assert metrics.mean_confidence(blocks, {1}) == pytest.approx(0.8)
    assert metrics.mean_confidence(blocks, set()) is None


def test_emit_writes_file(tmp_path: Path) -> None:
    out = tmp_path / "metrics.json"

    metrics.emit({"a": 1}, to_stderr=False, out=out)

    assert json.loads(out.read_text(encoding="utf-8")) == {"a": 1}


def test_no_flags_keep_stderr_clean(monkeypatch, tmp_path: Path, capsys) -> None:
    _mock_pipeline(monkeypatch)

    code = cli.main([str(_source(tmp_path))])

    assert code == 0
    assert capsys.readouterr().err == ""


def test_metrics_flag_writes_json_to_stderr(monkeypatch, tmp_path: Path, capsys) -> None:
    _mock_pipeline(monkeypatch)

    code = cli.main([str(_source(tmp_path)), "--metrics"])

    assert code == 0
    captured = capsys.readouterr()
    assert captured.out.strip() == "texto de prueba"
    report = json.loads(captured.err)
    assert report["file"] == {
        "path": str(_source(tmp_path)),
        "size_bytes": 10,
        "format": "pdf",
        "pages": 1,
    }
    assert report["ingest"]["native_pages"] == 1
    assert report["ingest"]["rasterized_pages"] == 0
    assert report["ingest"]["dpi"] == 200
    assert report["ocr"]["blocks"] == 1
    assert report["ocr"]["mean_confidence"] is None
    assert report["llm"]["enabled"] is False
    assert report["llm"]["model"] is None
    assert report["output"]["format"] == "md"
    assert report["total"]["time_ms"] >= 0


def test_metrics_out_writes_file_without_stderr(monkeypatch, tmp_path: Path, capsys) -> None:
    _mock_pipeline(monkeypatch)
    out = tmp_path / "metrics.json"

    code = cli.main([str(_source(tmp_path)), "--metrics-out", str(out)])

    assert code == 0
    assert capsys.readouterr().err == ""
    assert json.loads(out.read_text(encoding="utf-8"))["file"]["pages"] == 1


def test_rasterized_pages_report_confidence(monkeypatch, tmp_path: Path, capsys) -> None:
    _mock_pipeline(monkeypatch, pages=[PageInput(0, None, b"png")])
    monkeypatch.setattr(
        cli, "ocr_pages", lambda items, lang="default": [_block(0, "ocr", 0.9)]
    )

    cli.main([str(_source(tmp_path)), "--metrics"])

    report = json.loads(capsys.readouterr().err)
    assert report["ingest"]["native_pages"] == 0
    assert report["ingest"]["rasterized_pages"] == 1
    assert report["ocr"]["mean_confidence"] == pytest.approx(0.9)


def test_contract_mode_reports_model_and_tokens(monkeypatch, tmp_path: Path, capsys) -> None:
    _mock_pipeline(monkeypatch)
    model = tmp_path / "m.gguf"
    model.write_bytes(b"")
    contract = tmp_path / "c.json"
    contract.write_text(json.dumps(EXAMPLE), encoding="utf-8")
    monkeypatch.setattr(cli, "load_contract", lambda path: (EXAMPLE, "example"))
    monkeypatch.setattr(cli, "load_instructions", lambda *args, **kwargs: None)

    def fake_infer(text, shape, kind, model_path, **kwargs):
        usage_out = kwargs["usage_out"]
        assert usage_out is not None
        usage_out.update(
            {
                "load_time_ms": 5.0,
                "attempts": 2,
                "prompt_tokens": 30,
                "completion_tokens": 6,
                "total_tokens": 36,
                "tokens_per_second": 12.0,
            }
        )
        return {"cliente": "ACME"}

    monkeypatch.setattr(cli, "infer_contract", fake_infer)

    code = cli.main(
        [
            str(_source(tmp_path)),
            "--format",
            "json",
            "--contract",
            str(contract),
            "--model",
            str(model),
            "--metrics",
        ]
    )

    assert code == 0
    report = json.loads(capsys.readouterr().err)
    assert report["llm"]["enabled"] is True
    assert report["llm"]["model"] == "m.gguf"
    assert report["llm"]["attempts"] == 2
    assert report["llm"]["total_tokens"] == 36


def test_report_on_error(monkeypatch, tmp_path: Path, capsys) -> None:
    def boom(*args, **kwargs):
        raise InputError("boom")

    monkeypatch.setattr(cli, "ingest", boom)

    code = cli.main([str(_source(tmp_path)), "--metrics"])

    assert code == 1
    lines = capsys.readouterr().err.strip().splitlines()
    assert lines[0] == "error: boom"
    report = json.loads(lines[-1])
    assert report["error"] == {"kind": "input", "message": "boom"}
    assert report["total"]["time_ms"] >= 0


def test_report_on_contract_error_keeps_usage(monkeypatch, tmp_path: Path, capsys) -> None:
    _mock_pipeline(monkeypatch)
    model = tmp_path / "m.gguf"
    model.write_bytes(b"")
    contract = tmp_path / "c.json"
    contract.write_text(json.dumps(EXAMPLE), encoding="utf-8")
    monkeypatch.setattr(cli, "load_contract", lambda path: (EXAMPLE, "example"))
    monkeypatch.setattr(cli, "load_instructions", lambda *args, **kwargs: None)

    def boom(text, shape, kind, model_path, **kwargs):
        kwargs["usage_out"].update(
            {
                "load_time_ms": 1.0,
                "attempts": 2,
                "prompt_tokens": 10,
                "completion_tokens": 4,
                "total_tokens": 14,
                "tokens_per_second": 2.0,
                "finish_reason": "length",
            }
        )
        raise ContractError("respuesta truncada")

    monkeypatch.setattr(cli, "infer_contract", boom)

    code = cli.main(
        [
            str(_source(tmp_path)),
            "--format",
            "json",
            "--contract",
            str(contract),
            "--model",
            str(model),
            "--metrics",
        ]
    )

    assert code == 2
    lines = capsys.readouterr().err.strip().splitlines()
    assert lines[0] == "error: respuesta truncada"
    report = json.loads(lines[-1])
    assert report["error"] == {"kind": "contract", "message": "respuesta truncada"}
    assert report["llm"]["attempts"] == 2
    assert report["llm"]["finish_reason"] == "length"
    assert report["llm"]["time_ms"] >= 0


def test_interrupt_reports_and_exits_130(monkeypatch, tmp_path: Path, capsys) -> None:
    def boom(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "ingest", boom)
    out = tmp_path / "metrics.json"

    code = cli.main(
        [str(_source(tmp_path)), "--metrics", "--metrics-out", str(out)]
    )

    assert code == 130
    err = capsys.readouterr().err
    assert "Traceback" not in err
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["error"]["kind"] == "interrupted"
