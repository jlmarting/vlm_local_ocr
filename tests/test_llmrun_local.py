from __future__ import annotations

from pathlib import Path

import pytest

from vlm_ocr import llmrun
from vlm_ocr.errors import ContractError
from vlm_ocr.llmrun import BuiltPrompt, LocalRunner


def _model(tmp_path: Path) -> Path:
    path = tmp_path / "m.gguf"
    path.write_bytes(b"")
    return path


def test_missing_backend_raises(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(llmrun, "Llama", None)

    with pytest.raises(ContractError, match="llama-cpp-python"):
        LocalRunner(_model(tmp_path))


def test_missing_model_raises(monkeypatch, tmp_path: Path) -> None:
    class FakeLlama:
        def __init__(self, *args, **kwargs) -> None:
            pass

    monkeypatch.setattr(llmrun, "Llama", FakeLlama)

    with pytest.raises(ContractError, match="no existe el modelo"):
        LocalRunner(tmp_path / "nada.gguf")


def test_estimate_tokens_falls_back_to_chars(monkeypatch, tmp_path: Path) -> None:
    class FakeLlama:
        def __init__(self, *args, **kwargs) -> None:
            pass

    monkeypatch.setattr(llmrun, "Llama", FakeLlama)
    runner = LocalRunner(_model(tmp_path))

    assert runner.estimate_tokens(BuiltPrompt(messages=[{"role": "user", "content": "12345678"}])) == 2


def test_complete_uses_chat_completion_for_messages(monkeypatch, tmp_path: Path) -> None:
    calls: list[dict] = []

    class FakeLlama:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def create_chat_completion(self, messages, **kwargs):
            calls.append({"messages": messages, **kwargs})
            return {
                "choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            }

    monkeypatch.setattr(llmrun, "Llama", FakeLlama)
    runner = LocalRunner(_model(tmp_path))

    content, usage, finish = runner.complete(
        BuiltPrompt(messages=[{"role": "user", "content": "hola"}], response_format={"type": "json_object"}),
        64,
    )

    assert content == "{}"
    assert usage["total_tokens"] == 2
    assert finish == "stop"
    assert calls[0]["temperature"] == 0
    assert calls[0]["response_format"] == {"type": "json_object"}


def test_complete_uses_completion_for_raw(monkeypatch, tmp_path: Path) -> None:
    calls: list[dict] = []

    class FakeLlama:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def create_completion(self, prompt, **kwargs):
            calls.append({"prompt": prompt, **kwargs})
            return {"choices": [{"text": '{"a": 1}', "finish_reason": "stop"}]}

    monkeypatch.setattr(llmrun, "Llama", FakeLlama)
    runner = LocalRunner(_model(tmp_path))

    content, usage, finish = runner.complete(BuiltPrompt(raw="<|input|>"), 32)

    assert content == '{"a": 1}'
    assert usage is None
    assert finish == "stop"
    assert calls[0]["prompt"] == "<|input|>"
    assert "messages" not in calls[0]
