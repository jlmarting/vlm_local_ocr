from __future__ import annotations

from vlm_ocr.contract import subschema
from vlm_ocr.extract import assign
from vlm_ocr.homologate import learn_map
from vlm_ocr.types import LayoutBlock

SCHEMA = {
    "type": "object",
    "properties": {
        "cliente": {"type": ["string", "null"], "x-labels": ["CLIENTE"]},
        "total": {"type": ["number", "null"], "x-labels": ["TOTAL"]},
        "observaciones": {"type": ["string", "null"], "x-labels": ["OBSERVACIONES"]},
    },
}

EXAMPLE = {"cliente": "ACME", "total": 9.99, "observaciones": None}


def _block(text: str, x: float, y: float, width: float = 80.0) -> LayoutBlock:
    return LayoutBlock(0, text, 1.0, (x, y, x + width, y + 10))


def _order(values: tuple[str, str] = ("ACME", "9,99")) -> list[LayoutBlock]:
    return [
        _block("CLIENTE", 10, 0),
        _block(values[0], 100, 0),
        _block("TOTAL", 10, 12),
        _block(values[1], 100, 12),
    ]


def test_learn_map_from_assignment() -> None:
    assignment = assign(_order(), SCHEMA)
    data = dict(assignment.data)
    data["observaciones"] = None

    learned, absent, unlocated = learn_map(data, _order(), SCHEMA, "schema", assignment)

    assert learned["cliente"].labels == ("CLIENTE",)
    assert learned["total"].labels == ("TOTAL",)
    assert absent == ["observaciones"]
    assert unlocated == []


def test_learn_map_locates_values_without_annotations() -> None:
    learned, absent, unlocated = learn_map(
        {"cliente": "ACME", "total": 9.99, "observaciones": None},
        _order(),
        EXAMPLE,
        "example",
    )

    assert learned["cliente"].labels == ("CLIENTE",)
    assert learned["total"].labels == ("TOTAL",)
    assert absent == ["observaciones"]
    assert unlocated == []


def test_learn_map_marks_repeated_values_unlocated() -> None:
    blocks = _order() + [_block("TOTAL", 10, 24), _block("9,99", 100, 24)]

    learned, _, unlocated = learn_map(
        {"cliente": "ACME", "total": 9.99}, blocks, {"cliente": "", "total": 0}, "example"
    )

    assert "total" not in learned
    assert unlocated == ["total"]


def test_learn_map_detects_column() -> None:
    blocks = [
        _block("CONCEPTO", 10, 0),
        _block("UNIDADES", 100, 0),
        _block("IMPORTE", 220, 0),
        _block("TOTAL", 10, 12),
        _block("1", 110, 12),
        _block("9,99", 230, 12),
    ]

    learned, _, _ = learn_map({"total": 9.99}, blocks, {"total": 0}, "example")

    assert learned["total"].source == "importe"


def test_subschema_prunes_schema_and_required() -> None:
    contract = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "required": ["nomina"],
        "properties": {
            "nomina": {
                "type": "object",
                "required": ["devengos", "deducciones"],
                "properties": {
                    "devengos": {
                        "type": "object",
                        "required": ["salario_base"],
                        "properties": {
                            "salario_base": {"type": "number", "x-labels": ["SALARIO"]},
                            "horas_extras": {"type": "number"},
                        },
                    },
                    "deducciones": {"type": "object", "properties": {}},
                },
            }
        },
    }

    pruned = subschema(contract, ["nomina.devengos.salario_base"], "schema")

    assert pruned["properties"]["nomina"]["properties"]["devengos"]["properties"] == {
        "salario_base": {"type": "number", "x-labels": ["SALARIO"]}
    }
    assert pruned["properties"]["nomina"]["required"] == ["devengos"]


def test_subschema_keeps_example_intact() -> None:
    contract = {"a": {"b": 1, "c": 2}, "d": 3}

    assert subschema(contract, ["a.b"], "example") is contract


def test_subschema_without_paths_returns_contract() -> None:
    assert subschema(SCHEMA, [], "schema") is SCHEMA


def test_learn_map_marks_when_label_and_value_are_joined() -> None:
    blocks = [
        _block("GRUPO", 10, 0),
        _block("3", 100, 0),
        _block("PEDIDO:", 10, 12),
        _block("123", 100, 12),
    ]

    learned, _, _ = learn_map(
        {"grupo": "GRUPO 3", "pedido": "123"},
        blocks,
        {"grupo": "", "pedido": ""},
        "example",
    )

    assert learned["grupo"].join_label is True
    assert learned["pedido"].join_label is False


def test_learn_map_matches_dates_in_other_formats() -> None:
    blocks = [_block("FECHA", 10, 0), _block("02/02/2026", 100, 0)]

    learned, _, unlocated = learn_map(
        {"fecha": "2026-02-02"}, blocks, {"fecha": ""}, "example"
    )

    assert learned["fecha"].labels == ("FECHA",)
    assert learned["fecha"].join_label is False
    assert unlocated == []
