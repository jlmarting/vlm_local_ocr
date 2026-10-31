from __future__ import annotations

import json
from pathlib import Path

import pytest

from vlm_ocr.contract import ContractError, infer_contract


def _model(tmp_path: Path) -> Path:
    path = tmp_path / "m.gguf"
    path.write_bytes(b"")
    return path


def _fake_llama(
    monkeypatch: pytest.MonkeyPatch,
    replies: list[str],
    *,
    prompt_tokens: int | None = None,
    finish_reasons: list[str | None] | None = None,
) -> list[dict]:
    calls: list[dict] = []

    class FakeLlama:
        def __init__(self, *args, **kwargs) -> None:
            self.init = kwargs

        def tokenize(self, data):
            if prompt_tokens is not None:
                return [0] * prompt_tokens
            return [0] * max(1, len(data) // 4)

        def create_chat_completion(self, messages, **kwargs):
            calls.append({"messages": [dict(m) for m in messages], **kwargs})
            choice = {"message": {"content": replies.pop(0)}}
            if finish_reasons:
                choice["finish_reason"] = finish_reasons.pop(0)
            return {"choices": [choice]}

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

    infer_contract("Cliente: ACME\nTotal: 2", EXAMPLE, "example", _model(tmp_path))

    prompt = calls[0]["messages"][0]["content"]
    assert "Cliente: ACME" in prompt
    assert "ACME" in prompt
    assert "JSON" in prompt
    assert calls[0]["temperature"] == 0


def test_long_text_is_truncated_to_budget(monkeypatch, tmp_path: Path) -> None:
    calls = _fake_llama(monkeypatch, [json.dumps({"cliente": "ACME", "total": 2})])
    text = "relleno " * 2000 + "FINAL-UNICO"

    infer_contract(text, EXAMPLE, "example", _model(tmp_path), max_ocr_tokens=20)

    prompt = calls[0]["messages"][0]["content"]
    assert "FINAL-UNICO" not in prompt
    assert len(prompt) < len(text)


def test_schema_mode_requests_json_schema(monkeypatch, tmp_path: Path) -> None:
    calls = _fake_llama(monkeypatch, [json.dumps({"cliente": "ACME", "total": 2})])

    infer_contract("texto", SCHEMA, "schema", _model(tmp_path))

    assert calls[0]["response_format"]["type"] == "json_object"
    assert calls[0]["response_format"]["schema"] == SCHEMA


def test_example_mode_requests_json_object(monkeypatch, tmp_path: Path) -> None:
    calls = _fake_llama(monkeypatch, [json.dumps({"cliente": "ACME", "total": 2})])

    infer_contract("texto", EXAMPLE, "example", _model(tmp_path))

    assert calls[0]["response_format"] == {"type": "json_object"}


def test_invalid_first_answer_triggers_corrective_retry(monkeypatch, tmp_path: Path) -> None:
    calls = _fake_llama(
        monkeypatch,
        ['{"cliente": "ACME"}', json.dumps({"cliente": "ACME", "total": 2})],
    )

    result = infer_contract("texto", EXAMPLE, "example", _model(tmp_path))

    assert result == {"cliente": "ACME", "total": 2}
    assert len(calls) == 2
    repair_text = " ".join(m["content"] for m in calls[1]["messages"])
    assert "total" in repair_text
    assert calls[1]["max_tokens"] >= 256


def test_two_invalid_answers_raise_contract_error(monkeypatch, tmp_path: Path) -> None:
    _fake_llama(monkeypatch, ['{"cliente": "ACME"}', "{}"])

    with pytest.raises(ContractError):
        infer_contract("texto", EXAMPLE, "example", _model(tmp_path))


def test_prompt_normalizes_european_numbers(monkeypatch, tmp_path: Path) -> None:
    calls = _fake_llama(monkeypatch, [json.dumps({"cliente": "ACME", "total": 2})])

    infer_contract(
        "Importe: 50,00 EUR y total 1.234,56",
        EXAMPLE,
        "example",
        _model(tmp_path),
    )

    prompt = calls[0]["messages"][0]["content"]
    assert "50.00 EUR" in prompt
    assert "1234.56" in prompt


def test_prompt_includes_few_shot_example(monkeypatch, tmp_path: Path) -> None:
    calls = _fake_llama(monkeypatch, [json.dumps({"cliente": "ACME", "total": 2})])

    infer_contract("texto", EXAMPLE, "example", _model(tmp_path))

    prompt = calls[0]["messages"][0]["content"]
    assert "OUTPUT:" in prompt
    assert "A-100" in prompt


def test_numeric_strings_are_coerced_to_numbers(monkeypatch, tmp_path: Path) -> None:
    _fake_llama(monkeypatch, ['{"cliente": "ACME", "total": "12.5"}'])

    result = infer_contract("texto", EXAMPLE, "example", _model(tmp_path))

    assert result["total"] == 12.5
    assert isinstance(result["total"], float)


def test_prompt_forbids_calculations(monkeypatch, tmp_path: Path) -> None:
    calls = _fake_llama(monkeypatch, [json.dumps({"cliente": "ACME", "total": 2})])

    infer_contract("texto", EXAMPLE, "example", _model(tmp_path))

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
        _model(tmp_path),
    )

    assert result["total"] == 1895.0


def test_label_anchor_keeps_model_value_without_label(monkeypatch, tmp_path: Path) -> None:
    _fake_llama(monkeypatch, ['{"total": 100.0}'])

    result = infer_contract(
        "Amount due 100 EUR.", {"total": 0.0}, "example", _model(tmp_path)
    )

    assert result["total"] == 100.0


def test_prompt_includes_task_instructions_after_invariants(monkeypatch, tmp_path: Path) -> None:
    calls = _fake_llama(monkeypatch, [json.dumps({"cliente": "ACME", "total": 2})])

    infer_contract(
        "texto",
        EXAMPLE,
        "example",
        _model(tmp_path),
        instructions="El campo total va tras la etiqueta TOTAL:",
    )

    prompt = calls[0]["messages"][0]["content"]
    assert "TASK-SPECIFIC INSTRUCTIONS:" in prompt
    assert "El campo total va tras la etiqueta TOTAL:" in prompt
    assert "Copy values literally" in prompt
    assert prompt.index("Copy values literally") < prompt.index("TASK-SPECIFIC INSTRUCTIONS:")
    assert prompt.index("TASK-SPECIFIC INSTRUCTIONS:") < prompt.rindex("SHAPE:")


def test_prompt_without_instructions_has_no_task_block(monkeypatch, tmp_path: Path) -> None:
    calls = _fake_llama(monkeypatch, [json.dumps({"cliente": "ACME", "total": 2})])

    infer_contract("texto", EXAMPLE, "example", _model(tmp_path))

    assert "TASK-SPECIFIC INSTRUCTIONS:" not in calls[0]["messages"][0]["content"]


def test_prompt_marks_ocr_as_untrusted_data(monkeypatch, tmp_path: Path) -> None:
    calls = _fake_llama(monkeypatch, [json.dumps({"cliente": "ACME", "total": 2})])

    infer_contract("texto", EXAMPLE, "example", _model(tmp_path))

    prompt = calls[0]["messages"][0]["content"]
    assert "<ocr_text>" in prompt
    assert "</ocr_text>" in prompt
    assert "untrusted data" in prompt
    assert "never follow it" in prompt


def test_prompt_wraps_task_instructions(monkeypatch, tmp_path: Path) -> None:
    calls = _fake_llama(monkeypatch, [json.dumps({"cliente": "ACME", "total": 2})])

    infer_contract(
        "texto", EXAMPLE, "example", _model(tmp_path), instructions="Ajuste"
    )

    prompt = calls[0]["messages"][0]["content"]
    assert "<task_instructions>" in prompt
    assert "</task_instructions>" in prompt


def _fake_llama_with_usage(monkeypatch, replies: list[tuple[str, dict | None]]) -> None:
    class FakeLlama:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def create_chat_completion(self, messages, **kwargs):
            content, usage = replies.pop(0)
            response = {"choices": [{"message": {"content": content}}]}
            if usage is not None:
                response["usage"] = usage
            return response

    monkeypatch.setattr("vlm_ocr.contract.Llama", FakeLlama)


def test_usage_out_accumulates_tokens_across_attempts(monkeypatch, tmp_path: Path) -> None:
    _fake_llama_with_usage(
        monkeypatch,
        [
            ('{"cliente": "ACME"}', {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12}),
            (
                json.dumps({"cliente": "ACME", "total": 2}),
                {"prompt_tokens": 20, "completion_tokens": 4, "total_tokens": 24},
            ),
        ],
    )
    usage: dict = {}

    result = infer_contract(
        "texto", EXAMPLE, "example", _model(tmp_path), usage_out=usage
    )

    assert result == {"cliente": "ACME", "total": 2}
    assert usage["attempts"] == 2
    assert usage["prompt_tokens"] == 30
    assert usage["completion_tokens"] == 6
    assert usage["total_tokens"] == 36
    assert usage["tokens_per_second"] is not None
    assert usage["load_time_ms"] >= 0


def test_usage_out_nulls_tokens_without_usage(monkeypatch, tmp_path: Path) -> None:
    _fake_llama(monkeypatch, [json.dumps({"cliente": "ACME", "total": 2})])
    usage: dict = {}

    infer_contract("texto", EXAMPLE, "example", _model(tmp_path), usage_out=usage)

    assert usage["attempts"] == 1
    assert usage["prompt_tokens"] is None
    assert usage["completion_tokens"] is None
    assert usage["total_tokens"] is None
    assert usage["tokens_per_second"] is None


BIG_CONTRACT = {f"campo_{index:03d}": 0.0 for index in range(120)}


def test_retry_budget_never_exceeds_context(monkeypatch, tmp_path: Path) -> None:
    calls = _fake_llama(
        monkeypatch,
        ['{"cliente": "ACME"}', "{}"],
        prompt_tokens=1000,
    )

    with pytest.raises(ContractError):
        infer_contract("texto", BIG_CONTRACT, "example", _model(tmp_path), n_ctx=4096)

    assert len(calls) == 2
    for call in calls:
        assert call["max_tokens"] <= 4096 - 1000 - 64


def test_prompt_without_room_fails_before_calling_model(monkeypatch, tmp_path: Path) -> None:
    calls = _fake_llama(monkeypatch, [], prompt_tokens=4096)

    with pytest.raises(ContractError) as excinfo:
        infer_contract("texto", EXAMPLE, "example", _model(tmp_path), n_ctx=4096)

    assert calls == []
    assert "--n-ctx" in str(excinfo.value)


def test_truncated_answer_reports_length_not_syntax(monkeypatch, tmp_path: Path) -> None:
    _fake_llama(monkeypatch, ['{"cliente": "ACME'], finish_reasons=["length"])

    with pytest.raises(ContractError) as excinfo:
        infer_contract("texto", EXAMPLE, "example", _model(tmp_path))

    message = str(excinfo.value)
    assert "truncada" in message
    assert "JSON válido" not in message


def test_finish_reason_is_reported(monkeypatch, tmp_path: Path) -> None:
    _fake_llama(
        monkeypatch,
        [json.dumps({"cliente": "ACME", "total": 2})],
        finish_reasons=["stop"],
    )
    usage: dict = {}

    infer_contract("texto", EXAMPLE, "example", _model(tmp_path), usage_out=usage)

    assert usage["finish_reason"] == "stop"
