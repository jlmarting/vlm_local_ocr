from __future__ import annotations

from vlm_ocr.catalog import ModelEntry, ModelRef
from vlm_ocr.promptstyles import (
    build_chat_messages,
    build_prompt,
    build_repair_prompt,
    schema_from,
)

EXAMPLE = {"cliente": "ACME", "total": 1.5}


def ref(**overrides) -> ModelRef:
    entry = ModelEntry(
        alias="a",
        name="Modelo",
        kind="gguf",
        license="MIT",
        prompt_style="chat",
        **overrides,
    )
    return ModelRef(entry)


def test_chat_prompt_keeps_invariants_before_task_block() -> None:
    prompt = build_prompt(
        ref(), "texto", EXAMPLE, "example", "El total va tras TOTAL:"
    )

    content = prompt.messages[0]["content"]
    assert "Copy values literally" in content
    assert "Do not perform calculations" in content
    assert content.index("Copy values literally") < content.index("TASK-SPECIFIC INSTRUCTIONS:")
    assert "El total va tras TOTAL:" in content


def test_prompt_hints_go_after_invariants() -> None:
    prompt = build_prompt(
        ref(prompt_hints="No calcules nada."), "texto", EXAMPLE, "example"
    )

    content = prompt.messages[0]["content"]
    assert "No calcules nada." in content
    assert content.index("Copy values literally") < content.index("No calcules nada.")


def test_hints_come_after_sidecar_instructions() -> None:
    prompt = build_prompt(
        ref(prompt_hints="Nota del modelo."),
        "texto",
        EXAMPLE,
        "example",
        "Instrucción del sidecar.",
    )

    content = prompt.messages[0]["content"]
    assert content.index("Instrucción del sidecar.") < content.index("Nota del modelo.")


def test_response_format_includes_schema_only_for_schema_kind() -> None:
    schema = {"$schema": "https://json-schema.org/draft/2020-12/schema", "type": "object"}

    assert build_prompt(ref(), "t", EXAMPLE, "example").response_format == {"type": "json_object"}
    assert build_prompt(ref(), "t", schema, "schema").response_format["schema"] == schema


def test_repair_prompt_adds_error_turn() -> None:
    prompt = build_prompt(ref(), "texto", EXAMPLE, "example")
    raw = '{"cliente": "ACME"}'

    repair = build_repair_prompt(ref(), prompt, raw, ["total: required"])

    assert repair.messages[-2] == {"role": "assistant", "content": raw}
    assert "total: required" in repair.messages[-1]["content"]
    assert repair.response_format == prompt.response_format


def test_chat_messages_are_unchanged_without_hints() -> None:
    messages = build_chat_messages("Cliente: ACME", EXAMPLE, "example")

    content = messages[0]["content"]
    assert 'OCR TEXT:\n<ocr_text>\nCliente: ACME\n</ocr_text>' in content
    assert "SHAPE:" in content


def test_schema_from_uses_any_of_for_nullables() -> None:
    schema = schema_from({"a": 1, "b": ["x"], "c": True})

    assert schema["properties"]["a"] == {"anyOf": [{"type": "number"}, {"type": "null"}]}
    assert schema["properties"]["b"]["items"] == {
        "anyOf": [{"type": "string"}, {"type": "null"}]
    }
    assert schema["required"] == ["a", "b", "c"]
    assert schema["additionalProperties"] is False
