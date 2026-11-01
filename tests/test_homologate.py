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


ITEM_CONTRACT = {
    "type": "object",
    "properties": {
        "pedido": {
            "type": ["array", "null"],
            "items": {
                "type": "object",
                "properties": {
                    "producto": {"type": "string"},
                    "cantidad": {"type": ["integer", "null"]},
                    "precio": {"type": ["number", "null"]},
                    "observaciones": {"type": ["string", "null"]},
                },
            },
        },
        "total": {"type": ["number", "null"]},
    },
}

ITEM_CONTRACT_ANNOTATED = {
    "type": "object",
    "properties": {
        "pedido": {
            "type": ["array", "null"],
            "x-item-columns": {
                "producto": "text",
                "cantidad": "quantity",
                "precio": "number_right",
                "observaciones": "observation",
            },
            "x-stop-labels": ["COUNTER"],
            "items": ITEM_CONTRACT["properties"]["pedido"]["items"],
        },
        "total": {"type": ["number", "null"]},
    },
}

TICKET_DATA = {
    "pedido": [
        {
            "producto": "Hamburger",
            "cantidad": 1,
            "precio": 3.6,
            "observaciones": "- Tomato",
        },
        {
            "producto": "Db1-Db1",
            "cantidad": 1,
            "precio": 5.9,
            "observaciones": "+ Onion \nWell Done",
        },
        {
            "producto": "Db1-Db1",
            "cantidad": 1,
            "precio": 5.9,
            "observaciones": "- Lettuce \n+ Grilled 0",
        },
        {
            "producto": "Fry",
            "cantidad": 3,
            "precio": 6.9,
            "observaciones": None,
        },
        {
            "producto": "Med Soft Drink",
            "cantidad": 2,
            "precio": 4.5,
            "observaciones": None,
        },
        {
            "producto": "Water",
            "cantidad": 1,
            "precio": None,
            "observaciones": None,
        },
    ],
    "total": 29.35,
}


def _ticket_row(text: str, price: str | None, y: float) -> list[LayoutBlock]:
    blocks = [LayoutBlock(0, text, 1.0, (230.0, y, 412.0, y + 26))]
    if price is not None:
        blocks.append(LayoutBlock(0, price, 1.0, (614.0, y, 679.0, y + 26)))
    return blocks


def _ticket_obs(text: str, y: float) -> LayoutBlock:
    return LayoutBlock(0, text, 1.0, (267.0, y, 391.0, y + 26))


def _ticket_blocks() -> list[LayoutBlock]:
    return [
        *_ticket_row("1 Hamburger", "3.60", 300.0),
        _ticket_obs("- Tomato", 322.0),
        *_ticket_row("1 Db1-Db1", "5.90", 343.0),
        _ticket_obs("+ Onion", 369.0),
        _ticket_obs("Well Done", 393.0),
        *_ticket_row("1 Db1-Db1", "5.90", 416.0),
        _ticket_obs("- Lettuce", 441.0),
        _ticket_obs("+ Grilled 0", 463.0),
        *_ticket_row("3 Fry", "6.90", 488.0),
        *_ticket_row("2 Med Soft Drink", "4.50", 513.0),
        *_ticket_row("1 Water", None, 535.0),
        *_ticket_row("COUNTER-Eat In", "26.80", 588.0),
        _ticket_row("TAX 9.50%", "2.55", 612.0)[0],
    ]


def test_learn_items_from_annotations() -> None:
    from vlm_ocr.homologate import learn_items

    learned, unlocated = learn_items(
        {}, _ticket_blocks(), ITEM_CONTRACT_ANNOTATED, "schema"
    )

    assert unlocated == []
    assert learned["pedido"].columns["precio"] == "number_right"
    assert learned["pedido"].stop_labels == ("COUNTER",)


def test_learn_items_from_llm_data() -> None:
    from vlm_ocr.homologate import learn_items

    learned, unlocated = learn_items(TICKET_DATA, _ticket_blocks(), ITEM_CONTRACT, "schema")

    assert unlocated == []
    assert learned["pedido"].columns["producto"] == "text"
    assert learned["pedido"].columns["cantidad"] == "quantity"
    assert learned["pedido"].columns["precio"] == "number_right"
    assert learned["pedido"].columns["observaciones"] == "observation"
    assert learned["pedido"].stop_labels == ("COUNTER",)
    assert learned["pedido"].start_labels == ()


def test_learn_items_blocks_when_an_item_is_missing() -> None:
    from vlm_ocr.homologate import learn_items

    data = {
        "pedido": TICKET_DATA["pedido"][:2]
        + [{"producto": "Pizza", "cantidad": 1, "precio": 9.9, "observaciones": None}],
        "total": 29.35,
    }

    learned, unlocated = learn_items(data, _ticket_blocks(), ITEM_CONTRACT, "schema")

    assert learned == {}
    assert unlocated == ["pedido"]


def test_learn_map_skips_item_paths() -> None:
    learned, absent, unlocated = learn_map(
        TICKET_DATA, _ticket_blocks(), ITEM_CONTRACT, "schema"
    )

    assert "pedido" not in learned
    assert "pedido" not in absent
    assert "pedido" not in unlocated
