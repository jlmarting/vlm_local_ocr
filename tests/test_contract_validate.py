from __future__ import annotations

import json
from pathlib import Path

import pytest

from vlm_ocr.contract import ContractError, load_contract, validate_payload


def _write(tmp_path: Path, payload: dict) -> Path:
    path = tmp_path / "contrato.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_load_contract_detects_json_schema(tmp_path: Path) -> None:
    path = _write(tmp_path, {"$schema": "https://json-schema.org/draft/2020-12/schema"})

    contract, kind = load_contract(path)

    assert kind == "schema"
    assert contract["$schema"]


def test_load_contract_does_not_misdetect_payload_with_type_key(tmp_path: Path) -> None:
    path = _write(tmp_path, {"type": "factura", "total": 1})

    _, kind = load_contract(path)

    assert kind == "example"


def test_example_missing_required_key_is_error() -> None:
    errors = validate_payload({"total": 1}, {"total": 1, "cliente": "ACME"}, "example")

    assert any("cliente" in error for error in errors)


def test_example_extra_key_is_error() -> None:
    errors = validate_payload(
        {"total": 1, "cliente": "ACME", "extra": True},
        {"total": 1, "cliente": "ACME"},
        "example",
    )

    assert any("extra" in error for error in errors)


def test_example_null_is_nullable() -> None:
    contract = {"nota": None, "total": 1.5}

    assert validate_payload({"nota": None, "total": 2}, contract, "example") == []
    assert validate_payload({"nota": "texto", "total": 2.0}, contract, "example") == []


def test_example_null_value_is_accepted_as_absent() -> None:
    assert validate_payload({"total": None}, {"total": 1.5}, "example") == []


def test_example_arrays_merge_element_shapes() -> None:
    contract = {"items": [{"a": 1}, {"a": 2, "b": "x"}]}

    assert validate_payload({"items": [{"a": 3}, {"a": 4, "b": "y"}]}, contract, "example") == []
    extra = validate_payload({"items": [{"a": 5, "c": 1}]}, contract, "example")
    assert extra


def test_example_empty_array_accepts_any_content() -> None:
    assert validate_payload({"items": [{"lo": "que sea"}]}, {"items": []}, "example") == []


def test_example_int_accepted_where_float_expected() -> None:
    assert validate_payload({"total": 1}, {"total": 1.5}, "example") == []


def test_example_unambiguous_numeric_string_is_coerced() -> None:
    assert validate_payload({"total": "12"}, {"total": 1.5}, "example") == []


def test_example_ambiguous_numeric_string_is_rejected() -> None:
    errors = validate_payload({"total": "1.234,56"}, {"total": 1.5}, "example")

    assert errors


def test_schema_mode_uses_jsonschema() -> None:
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": {"total": {"type": "number"}},
        "required": ["total"],
        "additionalProperties": False,
    }

    assert validate_payload({"total": 3}, schema, "schema") == []
    assert validate_payload({"total": "tres"}, schema, "schema")


def test_example_int_rejects_fractional_float() -> None:
    assert validate_payload({"n": 1.5}, {"n": 1}, "example")


def test_example_int_rejects_fractional_string() -> None:
    assert validate_payload({"n": "1.5"}, {"n": 1}, "example")


def test_example_int_accepts_integral_float() -> None:
    assert validate_payload({"n": 2.0}, {"n": 1}, "example") == []


def test_load_contract_from_stdin_data() -> None:
    contract, kind = load_contract(
        "-", data=b'{"$schema": "https://json-schema.org/draft/2020-12/schema"}'
    )

    assert kind == "schema"
    assert contract["$schema"]


def test_load_contract_from_stdin_reports_label_and_line() -> None:
    with pytest.raises(ContractError, match=r"stdin \(línea 2\)"):
        load_contract("-", data=b'{\n  "a": }')


def test_load_contract_from_stdin_rejects_non_utf8() -> None:
    with pytest.raises(ContractError, match="stdin"):
        load_contract("-", data=b"\xff")


def test_load_contract_from_stdin_must_be_an_object() -> None:
    with pytest.raises(ContractError, match="objeto JSON"):
        load_contract("-", data=b"[1, 2]")
