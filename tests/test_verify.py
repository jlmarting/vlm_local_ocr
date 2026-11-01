from __future__ import annotations

from vlm_ocr.verify import literal_errors

DATA = {
    "nomina": {
        "devengos": {"salario_base": 2406.89, "horas_extras": 141.96},
        "deducciones": {"irpf": {"retencion": 443.74}},
    }
}
TEXT = "SALARIO BASE | 30,00 | 80,2297 | 2.406,89\nRETENCION I.R.P.F. | 443,74"


def test_present_numbers_pass() -> None:
    data = {"nomina": {"devengos": {"salario_base": 2406.89}}}

    assert literal_errors(data, TEXT) == []


def test_invented_number_is_reported() -> None:
    errors = literal_errors(DATA, TEXT)

    assert [error["field"] for error in errors] == ["nomina.devengos.horas_extras"]
    assert errors[0]["kind"] == "literal"
    assert "141.96" in errors[0]["message"]


def test_integer_values_compare_by_value_not_notation() -> None:
    assert literal_errors({"total": 30}, "Total días 30,00") == []


def test_nulls_are_ignored() -> None:
    assert literal_errors({"a": None, "b": 2406.89}, TEXT) == []


def test_invented_string_is_reported() -> None:
    errors = literal_errors({"cliente": "ACME"}, "sin datos")

    assert [error["field"] for error in errors] == ["cliente"]
    assert errors[0]["kind"] == "literal"
    assert "ACME" in errors[0]["message"]


def test_string_with_punctuation_and_case_passes() -> None:
    assert literal_errors({"cliente": "ACME, S.L."}, "Cliente: ACME, S.L.") == []


def test_accents_are_ignored() -> None:
    assert literal_errors({"nombre": "José Pérez"}, "JOSE PEREZ") == []


def test_string_across_lines_passes() -> None:
    assert literal_errors({"obs": "sin cebolla"}, "sin\ncebolla") == []


def test_reformatted_date_passes() -> None:
    assert literal_errors({"fecha": "2026-02-02"}, "Fecha: 02/02/2026") == []


def test_invented_date_is_reported() -> None:
    errors = literal_errors({"fecha": "02/14/2022"}, "064 2 1404 2022")

    assert [error["field"] for error in errors] == ["fecha"]
    assert "fecha" in errors[0]["message"]


def test_compact_time_passes() -> None:
    assert literal_errors({"hora": "14:04"}, "064 2 1404 2022") == []


def test_invented_time_is_reported() -> None:
    errors = literal_errors({"hora": "02:04"}, "064 2 1404 2022")

    assert [error["field"] for error in errors] == ["hora"]
    assert "hora" in errors[0]["message"]


def test_list_items_are_checked() -> None:
    errors = literal_errors({"pedido": [{"producto": "Inventado"}]}, "Hamburger")

    assert [error["field"] for error in errors] == ["pedido[0].producto"]


def test_single_character_strings_are_ignored() -> None:
    assert literal_errors({"sexo": "S"}, "") == []


def test_long_strings_are_truncated_in_the_message() -> None:
    errors = literal_errors({"nota": "x" * 200}, "")

    assert len(errors[0]["message"]) < 120


def test_field_coverage_counts_top_level_contract_keys() -> None:
    from vlm_ocr.verify import field_coverage

    contract = {"fecha": "", "hora": "", "pedido": [{"producto": ""}], "total": 0.0}
    data = {"fecha": None, "hora": None, "pedido": [{"producto": "X"}], "total": 29.35}

    assert field_coverage(data, contract, "example") == (2, 4)


def test_field_coverage_uses_annotated_paths_for_schemas() -> None:
    from vlm_ocr.verify import field_coverage

    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": {
            "nomina": {
                "type": "object",
                "properties": {
                    "a": {"type": ["number", "null"], "x-labels": ["A"]},
                    "b": {"type": ["number", "null"], "x-labels": ["B"]},
                },
            }
        },
    }
    data = {"nomina": {"a": 1.0, "b": None}}

    assert field_coverage(data, schema, "schema") == (1, 2)
