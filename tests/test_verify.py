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
