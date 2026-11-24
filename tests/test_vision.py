from __future__ import annotations

import base64
from pathlib import Path

import pytest

from vlm_ocr import catalog, llmrun, vision
from vlm_ocr.types import PageInput


class FakeRunner:
    load_time_ms = 0.0

    def __init__(self, answers: list[str] | None = None) -> None:
        self.answers = list(answers or ["Línea A\n\nLínea B"])
        self.calls: list[llmrun.BuiltPrompt] = []

    def complete(self, prompt, max_tokens):
        self.calls.append(prompt)
        return self.answers.pop(0) if self.answers else "", None, "stop"

    def estimate_tokens(self, prompt) -> int:
        return 1


def test_transcribe_pages_returns_line_blocks() -> None:
    runner = FakeRunner()
    pages = [PageInput(2, None, b"png")]

    blocks = vision.transcribe_pages(pages, runner, max_tokens=64)

    assert [block.text for block in blocks] == ["Línea A", "Línea B"]
    assert all(block.page == 2 for block in blocks)
    assert all(block.confidence == 0.0 for block in blocks)
    assert all(block.box == (0.0, 0.0, 0.0, 0.0) for block in blocks)
    assert len(runner.calls) == 1
    assert runner.calls[0].images == (b"png",)


def test_transcribe_pages_skips_native_text() -> None:
    runner = FakeRunner()
    pages = [PageInput(0, "texto nativo", None), PageInput(1, None, b"png")]

    blocks = vision.transcribe_pages(pages, runner, max_tokens=64)

    assert len(runner.calls) == 1
    assert all(block.page == 1 for block in blocks)


def test_transcribe_pages_empty_page_warns(capsys) -> None:
    runner = FakeRunner(["  \n\n", "algo"])
    pages = [PageInput(0, None, b"png"), PageInput(1, None, b"png")]

    blocks = vision.transcribe_pages(pages, runner, max_tokens=64)

    assert [block.text for block in blocks] == ["algo"]
    assert "página 0" in capsys.readouterr().err


def test_transcribe_pages_all_empty_raises() -> None:
    runner = FakeRunner(["", ""])
    pages = [PageInput(0, None, b"png"), PageInput(1, None, b"png")]

    with pytest.raises(Exception, match="no devolvió texto"):
        vision.transcribe_pages(pages, runner, max_tokens=64)


def test_transcribe_pages_without_raster_returns_empty() -> None:
    runner = FakeRunner()
    pages = [PageInput(0, "solo texto", None)]

    assert vision.transcribe_pages(pages, runner, max_tokens=64) == []
    assert runner.calls == []


def _ref(tmp_path: Path, *, with_mmproj: bool = True) -> catalog.ModelRef:
    entry = catalog.ModelEntry(
        alias="v",
        name="Vision",
        kind="gguf",
        license="LFM",
        file="m.gguf",
        vision=True,
        mmproj_file="mm.gguf",
        mmproj_sha256="b" * 64,
    )
    model = tmp_path / "m.gguf"
    model.write_bytes(b"")
    mmproj = None
    if with_mmproj:
        mmproj = tmp_path / "mm.gguf"
        mmproj.write_bytes(b"")
    return catalog.ModelRef(entry, model, mmproj)


def test_vision_runner_requires_mmproj(tmp_path: Path) -> None:
    ref = _ref(tmp_path, with_mmproj=False)

    with pytest.raises(catalog.CatalogError, match="mmproj"):
        llmrun.VisionRunner(ref)


def test_vision_runner_requires_modern_llama_cpp(monkeypatch) -> None:
    from llama_cpp import llama_chat_format

    monkeypatch.delattr(llama_chat_format, "MTMDChatHandler", raising=False)

    with pytest.raises(Exception, match="0.3.38"):
        llmrun._mtmd_handler()


def test_vision_runner_wires_handler_and_images(tmp_path: Path, monkeypatch) -> None:
    captured: dict = {}

    class FakeHandler:
        def __init__(self, **kwargs):
            captured["handler_kwargs"] = kwargs

    class FakeLlama:
        def __init__(self, **kwargs):
            captured["llama_kwargs"] = kwargs

        def create_chat_completion(self, messages, **kwargs):
            captured["messages"] = messages
            captured["completion_kwargs"] = kwargs
            return {
                "choices": [{"message": {"content": "hola"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            }

    monkeypatch.setattr(llmrun, "Llama", FakeLlama)
    monkeypatch.setattr(llmrun, "_mtmd_handler", lambda: FakeHandler)
    ref = _ref(tmp_path)

    runner = llmrun.VisionRunner(ref, n_ctx=2048)
    text, _usage, finish = runner.complete(vision.build_prompt(b"PNG"), max_tokens=32)

    assert text == "hola"
    assert finish == "stop"
    assert captured["handler_kwargs"]["clip_model_path"] == str(ref.mmproj_path)
    assert captured["llama_kwargs"]["model_path"] == str(ref.path)
    assert captured["llama_kwargs"]["n_ctx"] == 2048
    content = captured["messages"][0]["content"]
    image_part = content[0]
    assert image_part["type"] == "image_url"
    assert image_part["image_url"]["url"] == (
        "data:image/png;base64," + base64.b64encode(b"PNG").decode("ascii")
    )
    assert captured["completion_kwargs"]["temperature"] == 0


def test_vision_prompt_is_literal() -> None:
    prompt = vision.build_prompt(b"PNG")

    assert "No traduzcas" in vision.VISION_PROMPT
    assert prompt.text_for_tokens == vision.VISION_PROMPT


def test_vision_runner_sends_plain_text_without_images(tmp_path: Path, monkeypatch) -> None:
    captured: dict = {}

    class FakeLlama:
        def __init__(self, **kwargs):
            pass

        def create_chat_completion(self, messages, **kwargs):
            captured["messages"] = messages
            return {
                "choices": [{"message": {"content": '{"a": 1}'}, "finish_reason": "stop"}],
                "usage": {},
            }

    monkeypatch.setattr(llmrun, "Llama", FakeLlama)
    class FakeHandler:
        def __init__(self, **kwargs):
            pass

    monkeypatch.setattr(llmrun, "_mtmd_handler", lambda: FakeHandler)
    ref = _ref(tmp_path)
    runner = llmrun.VisionRunner(ref)

    runner.complete(llmrun.BuiltPrompt(messages=[{"role": "user", "content": "hola"}]), max_tokens=8)

    assert captured["messages"] == [{"role": "user", "content": "hola"}]
