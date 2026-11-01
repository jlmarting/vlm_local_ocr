from __future__ import annotations

import json
from pathlib import Path

from vlm_ocr import bench, catalog, cli, llmrun

EXAMPLE = {"cliente": "ACME", "total": 1.5}


def _model(tmp_path: Path) -> Path:
    path = tmp_path / "m.gguf"
    path.write_bytes(b"")
    return path


def _contract(tmp_path: Path) -> Path:
    path = tmp_path / "c.json"
    path.write_text(json.dumps(EXAMPLE), encoding="utf-8")
    return path


def _fake(monkeypatch, replies: list[str], calls: list[dict]) -> None:
    class FakeLlama:
        def __init__(self, *args, **kwargs) -> None:
            self.load = kwargs

        def create_chat_completion(self, messages, **kwargs):
            calls.append({"messages": messages, **kwargs})
            return {
                "choices": [{"message": {"content": replies.pop(0)}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 4, "completion_tokens": 2, "total_tokens": 6},
            }

        def create_completion(self, prompt, **kwargs):
            calls.append({"prompt": prompt, **kwargs})
            return {"choices": [{"text": replies.pop(0), "finish_reason": "stop"}]}

    monkeypatch.setattr(llmrun, "Llama", FakeLlama)


def test_run_bench_returns_record(tmp_path: Path, monkeypatch) -> None:
    calls: list[dict] = []
    _fake(monkeypatch, [json.dumps({"cliente": "ACME", "total": 2})], calls)
    text = tmp_path / "texto.txt"
    text.write_text("Cliente: ACME", encoding="utf-8")
    ref = catalog.ad_hoc(_model(tmp_path))

    record = bench.run_bench(
        ref, doc=tmp_path / "doc.pdf", contract_path=_contract(tmp_path), text=text
    )

    assert record["model"] == "m.gguf"
    assert record["valid_json"] is True
    assert record["data"] == {"cliente": "ACME", "total": 2}
    assert record["mode"] == "grammar"
    assert record["tokens_per_second"] is not None
    assert calls[0]["response_format"]["schema"]["type"] == "object"


def test_run_bench_without_grammar_sends_json_only(tmp_path: Path, monkeypatch) -> None:
    calls: list[dict] = []
    _fake(monkeypatch, [json.dumps({"cliente": "ACME", "total": 2})], calls)
    text = tmp_path / "texto.txt"
    text.write_text("Cliente: ACME", encoding="utf-8")

    bench.run_bench(
        catalog.ad_hoc(_model(tmp_path)),
        doc=tmp_path / "doc.pdf",
        contract_path=_contract(tmp_path),
        text=text,
        grammar=False,
    )

    assert calls[0]["response_format"] == {"type": "json_object"}


def test_models_bench_rejects_unknown_alias(tmp_path: Path, capsys) -> None:
    code = cli.main(
        ["models", "bench", "noexiste", "--doc", str(tmp_path / "d.pdf"),
         "--contract", str(_contract(tmp_path))]
    )

    assert code == 2
    assert "alias desconocido" in capsys.readouterr().err


def test_run_bench_nuextract_reports_json_mode(tmp_path: Path, monkeypatch) -> None:
    from vlm_ocr.catalog import ModelEntry, ModelRef

    calls: list[dict] = []
    _fake(monkeypatch, ['{"cliente": "ACME", "total": 2}'], calls)
    text = tmp_path / "texto.txt"
    text.write_text("Cliente: ACME", encoding="utf-8")
    model = _model(tmp_path)
    ref = ModelRef(
        ModelEntry(
            alias="nuextract",
            name="NuExtract",
            kind="gguf",
            license="MIT",
            prompt_style="nuextract",
            file=model.name,
        ),
        model,
    )

    record = bench.run_bench(
        ref, doc=tmp_path / "doc.pdf", contract_path=_contract(tmp_path), text=text
    )

    assert record["mode"] == "json"
    assert "prompt" in calls[0]
    assert "response_format" not in calls[0]
