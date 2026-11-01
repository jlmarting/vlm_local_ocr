from __future__ import annotations

import json
from pathlib import Path

from vlm_ocr.annotations import field_map, has_annotations
from vlm_ocr.contract import infer_contract, validate_payload

SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "nomina": {
            "type": "object",
            "properties": {
                "datos_generales": {
                    "type": "object",
                    "properties": {
                        "grupo_cotizacion": {
                            "type": ["string", "null"],
                            "x-labels": ["GRUPO"],
                        }
                    },
                },
                "devengos": {
                    "type": "object",
                    "properties": {
                        "salario_base": {
                            "type": ["number", "null"],
                            "x-labels": ["SALARIO BASE"],
                            "x-source": "devengado",
                        },
                        "antiguedad": {
                            "type": "object",
                            "properties": {
                                "unidades": {
                                    "type": ["number", "null"],
                                    "x-labels": ["ANTIGÜEDAD"],
                                    "x-source": "unidades",
                                },
                                "importe": {
                                    "type": ["number", "null"],
                                    "x-labels": ["ANTIGÜEDAD"],
                                    "x-source": "devengado",
                                },
                            },
                        },
                    },
                },
            },
        }
    },
}

PLAIN = {
    "type": "object",
    "properties": {"cliente": {"type": "string"}, "total": {"type": "number"}},
}


def test_field_map_reads_paths_labels_and_source() -> None:
    hints = field_map(SCHEMA)

    assert [hint.path for hint in hints] == [
        "nomina.datos_generales.grupo_cotizacion",
        "nomina.devengos.salario_base",
        "nomina.devengos.antiguedad.unidades",
        "nomina.devengos.antiguedad.importe",
    ]
    assert hints[1].labels == ("SALARIO BASE",)
    assert hints[1].source == "devengado"
    assert hints[2].source == "unidades"


def test_has_annotations_is_false_without_x_keys() -> None:
    assert has_annotations(SCHEMA) is True
    assert has_annotations(PLAIN) is False


def _fake_llama(monkeypatch, replies: list[str]) -> list[dict]:
    calls: list[dict] = []

    class FakeLlama:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def tokenize(self, data):
            return [0] * max(1, len(data) // 4)

        def create_chat_completion(self, messages, **kwargs):
            calls.append({"messages": [dict(m) for m in messages], **kwargs})
            return {"choices": [{"message": {"content": replies.pop(0)}}]}

    monkeypatch.setattr("vlm_ocr.llmrun.Llama", FakeLlama)
    return calls


def _model(tmp_path: Path) -> Path:
    path = tmp_path / "m.gguf"
    path.write_bytes(b"")
    return path


def test_prompt_includes_generated_field_map(monkeypatch, tmp_path: Path) -> None:
    calls = _fake_llama(monkeypatch, [json.dumps({"nomina": {}})])

    infer_contract(
        "texto", SCHEMA, "schema", _model(tmp_path), instructions=None
    )

    prompt = calls[0]["messages"][0]["content"]
    assert "MAPA DE CAMPOS" in prompt
    assert "conforms to the JSON Schema" in prompt
    assert "SALARIO BASE -> nomina.devengos.salario_base (devengado)" in prompt
    assert "ANTIGÜEDAD -> nomina.devengos.antiguedad.unidades (unidades)" in prompt


def test_prompt_without_annotations_has_no_field_map(monkeypatch, tmp_path: Path) -> None:
    calls = _fake_llama(monkeypatch, [json.dumps({"cliente": "ACME", "total": 2})])

    infer_contract("texto", PLAIN, "schema", _model(tmp_path))

    assert "MAPA DE CAMPOS" not in calls[0]["messages"][0]["content"]


def test_annotated_schema_is_still_validated() -> None:
    assert validate_payload({"nomina": {}}, SCHEMA, "schema") == []
    assert validate_payload({"nomina": {"devengos": {"salario_base": "x"}}}, SCHEMA, "schema")
