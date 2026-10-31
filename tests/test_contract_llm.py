from __future__ import annotations

import json
from pathlib import Path

import pytest

from vlm_ocr.contract import ContractError, infer_contract


def _fake_llama(monkeypatch: pytest.MonkeyPatch, replies: list[str]) -> list[dict]:
    calls: list[dict] = []

    class FakeLlama:
        def __init__(self, *args, **kwargs) -> None:
            self.init = kwargs

        def create_chat_completion(self, messages, **kwargs):
            calls.append({"messages": [dict(m) for m in messages], **kwargs})
            return {"choices": [{"message": {"content": replies.pop(0)}}]}

    monkeypatch.setattr("vlm_ocr.contract.Llama", FakeLlama)
    return calls


EXAMPLE = {"cliente": "ACME", "total": 1.5}
SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {"cliente": {"type": "string"}, "total": {"type": "number"}},
    "required": ["cliente", "total"],
}


def test_prompt_contains_text_and_contract(monkeypatch, tmp_path: Path) -> None:
    calls = _fake_llama(monkeypatch, [json.dumps({"cliente": "ACME", "total": 2})])

    infer_contract("Cliente: ACME\nTotal: 2", EXAMPLE, "example", tmp_path / "m.gguf")

    prompt = calls[0]["messages"][0]["content"]
    assert "Cliente: ACME" in prompt
    assert "ACME" in prompt
    assert "JSON" in prompt
    assert calls[0]["temperature"] == 0


def test_long_text_is_truncated_to_budget(monkeypatch, tmp_path: Path) -> None:
    calls = _fake_llama(monkeypatch, [json.dumps({"cliente": "ACME", "total": 2})])
    text = "relleno " * 2000 + "FINAL-UNICO"

    infer_contract(text, EXAMPLE, "example", tmp_path / "m.gguf", max_ocr_tokens=20)

    prompt = calls[0]["messages"][0]["content"]
    assert "FINAL-UNICO" not in prompt
    assert len(prompt) < len(text)


def test_schema_mode_requests_json_schema(monkeypatch, tmp_path: Path) -> None:
    calls = _fake_llama(monkeypatch, [json.dumps({"cliente": "ACME", "total": 2})])

    infer_contract("texto", SCHEMA, "schema", tmp_path / "m.gguf")

    assert calls[0]["response_format"]["type"] == "json_object"
    assert calls[0]["response_format"]["schema"] == SCHEMA


def test_example_mode_requests_json_object(monkeypatch, tmp_path: Path) -> None:
    calls = _fake_llama(monkeypatch, [json.dumps({"cliente": "ACME", "total": 2})])

    infer_contract("texto", EXAMPLE, "example", tmp_path / "m.gguf")

    assert calls[0]["response_format"] == {"type": "json_object"}


def test_invalid_first_answer_triggers_corrective_retry(monkeypatch, tmp_path: Path) -> None:
    calls = _fake_llama(
        monkeypatch,
        ['{"cliente": "ACME"}', json.dumps({"cliente": "ACME", "total": 2})],
    )

    result = infer_contract("texto", EXAMPLE, "example", tmp_path / "m.gguf")

    assert result == {"cliente": "ACME", "total": 2}
    assert len(calls) == 2
    repair_text = " ".join(m["content"] for m in calls[1]["messages"])
    assert "total" in repair_text
    assert calls[1]["max_tokens"] > calls[0]["max_tokens"]


def test_two_invalid_answers_raise_contract_error(monkeypatch, tmp_path: Path) -> None:
    _fake_llama(monkeypatch, ['{"cliente": "ACME"}', "{}"])

    with pytest.raises(ContractError):
        infer_contract("texto", EXAMPLE, "example", tmp_path / "m.gguf")


def test_prompt_normalizes_european_numbers(monkeypatch, tmp_path: Path) -> None:
    calls = _fake_llama(monkeypatch, [json.dumps({"cliente": "ACME", "total": 2})])

    infer_contract(
        "Importe: 50,00 EUR y total 1.234,56",
        EXAMPLE,
        "example",
        tmp_path / "m.gguf",
    )

    prompt = calls[0]["messages"][0]["content"]
    assert "50.00 EUR" in prompt
    assert "1234.56" in prompt


def test_prompt_includes_few_shot_example(monkeypatch, tmp_path: Path) -> None:
    calls = _fake_llama(monkeypatch, [json.dumps({"cliente": "ACME", "total": 2})])

    infer_contract("texto", EXAMPLE, "example", tmp_path / "m.gguf")

    prompt = calls[0]["messages"][0]["content"]
    assert "OUTPUT:" in prompt
    assert "A-100" in prompt


def test_numeric_strings_are_coerced_to_numbers(monkeypatch, tmp_path: Path) -> None:
    _fake_llama(monkeypatch, ['{"cliente": "ACME", "total": "12.5"}'])

    result = infer_contract("texto", EXAMPLE, "example", tmp_path / "m.gguf")

    assert result["total"] == 12.5
    assert isinstance(result["total"], float)


def test_prompt_forbids_calculations(monkeypatch, tmp_path: Path) -> None:
    calls = _fake_llama(monkeypatch, [json.dumps({"cliente": "ACME", "total": 2})])

    infer_contract("texto", EXAMPLE, "example", tmp_path / "m.gguf")

    prompt = calls[0]["messages"][0]["content"]
    assert "Copy values literally" in prompt
    assert "Do not perform calculations" in prompt
    assert "derived figures" in prompt


def test_label_anchor_prefers_explicitly_labelled_number(monkeypatch, tmp_path: Path) -> None:
    _fake_llama(monkeypatch, ['{"cliente": "ACME", "total": 100.0}'])

    result = infer_contract(
        "Unit price: 100. Total: 1895 EUR.",
        {"cliente": "ACME", "total": 0.0},
        "example",
        tmp_path / "m.gguf",
    )

    assert result["total"] == 1895.0


def test_label_anchor_keeps_model_value_without_label(monkeypatch, tmp_path: Path) -> None:
    _fake_llama(monkeypatch, ['{"total": 100.0}'])

    result = infer_contract(
        "Amount due 100 EUR.", {"total": 0.0}, "example", tmp_path / "m.gguf"
    )

    assert result["total"] == 100.0
