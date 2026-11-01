from __future__ import annotations

import io
import json
import sys
from pathlib import Path

from vlm_ocr import cli

TEXT = "cafe 1,20€ coockie 2,2€ total 3,40€\n"


def _model(tmp_path: Path) -> str:
    path = tmp_path / "m.gguf"
    path.write_bytes(b"")
    return str(path)


def _doc(tmp_path: Path) -> Path:
    path = tmp_path / "nota.txt"
    path.write_text(TEXT, encoding="utf-8")
    return path


def _pipe(monkeypatch, raw: bytes) -> None:
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(raw)))


def _fake_answer(monkeypatch, answer: str = "RESPUESTA") -> dict[str, object]:
    seen: dict[str, object] = {}

    def fake_infer(
        text,
        task,
        model,
        *,
        n_ctx=4096,
        max_ocr_tokens=1500,
        max_output_tokens=None,
        usage_out=None,
    ):
        seen["text"] = text
        seen["task"] = task
        seen["model"] = model
        if usage_out is not None:
            usage_out.update(
                {
                    "load_time_ms": 1.0,
                    "attempts": 1,
                    "prompt_tokens": 3,
                    "completion_tokens": 2,
                    "total_tokens": 5,
                    "tokens_per_second": 10.0,
                    "finish_reason": "stop",
                    "max_tokens": 100,
                }
            )
        return answer

    monkeypatch.setattr(cli, "infer_answer", fake_infer)
    return seen


def test_prompt_without_model_returns_2(tmp_path: Path, capsys) -> None:
    code = cli.main([str(_doc(tmp_path)), "--prompt", "resume"])

    assert code == 2
    assert "--prompt requiere --model" in capsys.readouterr().err


def test_prompt_with_contract_returns_2(tmp_path: Path, capsys) -> None:
    contract = tmp_path / "c.json"
    contract.write_text("{}", encoding="utf-8")

    code = cli.main(
        [
            str(_doc(tmp_path)),
            "--format",
            "json",
            "--prompt",
            "resume",
            "--contract",
            str(contract),
            "--model",
            _model(tmp_path),
        ]
    )

    assert code == 2
    assert "no se combina" in capsys.readouterr().err


def test_prompt_with_no_llm_returns_2(tmp_path: Path, capsys) -> None:
    code = cli.main(
        [str(_doc(tmp_path)), "--prompt", "resume", "--model", _model(tmp_path), "--no-llm"]
    )

    assert code == 2
    assert "--no-llm" in capsys.readouterr().err


def test_document_and_prompt_stdin_returns_2(tmp_path: Path, capsys) -> None:
    code = cli.main(["-", "--prompt", "-", "--model", _model(tmp_path)])

    assert code == 2
    assert "solo una entrada puede ser '-'" in capsys.readouterr().err


def test_prompt_markdown_prints_answer(monkeypatch, tmp_path: Path, capsys) -> None:
    _fake_answer(monkeypatch)

    code = cli.main(
        [str(_doc(tmp_path)), "--prompt", "resume", "--model", _model(tmp_path)]
    )

    assert code == 0
    assert capsys.readouterr().out.strip() == "RESPUESTA"


def test_prompt_json_wraps_text_and_answer(monkeypatch, tmp_path: Path, capsys) -> None:
    _fake_answer(monkeypatch)

    code = cli.main(
        [
            str(_doc(tmp_path)),
            "--format",
            "json",
            "--prompt",
            "resume",
            "--model",
            _model(tmp_path),
        ]
    )

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["answer"] == "RESPUESTA"
    assert "total 3,40€" in payload["text"]


def test_prompt_from_stdin_reaches_infer(monkeypatch, tmp_path: Path) -> None:
    seen = _fake_answer(monkeypatch)
    _pipe(monkeypatch, b"resume el ticket")

    code = cli.main(
        [str(_doc(tmp_path)), "--prompt", "-", "--model", _model(tmp_path)]
    )

    assert code == 0
    assert seen["task"] == "resume el ticket"


def test_empty_prompt_returns_2(tmp_path: Path, capsys) -> None:
    code = cli.main(
        [str(_doc(tmp_path)), "--prompt", "   ", "--model", _model(tmp_path)]
    )

    assert code == 2
    assert "vacío" in capsys.readouterr().err


def test_prompt_metrics_mark_llm_enabled(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    _fake_answer(monkeypatch)
    out = tmp_path / "metrics.json"

    code = cli.main(
        [
            str(_doc(tmp_path)),
            "--prompt",
            "resume",
            "--model",
            _model(tmp_path),
            "--metrics-out",
            str(out),
        ]
    )

    assert code == 0
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["llm"]["enabled"] is True
    assert report["llm"]["model"]
    assert report["llm"]["total_tokens"] == 5


def test_remote_prompt_warns_about_privacy(monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.setenv("OLLAMA_API_KEY", "test-key")
    _fake_answer(monkeypatch)

    code = cli.main(
        [
            str(_doc(tmp_path)),
            "--prompt",
            "resume",
            "--model",
            "cloud-deepseek",
        ]
    )

    assert code == 0
    assert "se enviarán" in capsys.readouterr().err
