from __future__ import annotations

from vlm_ocr.annotations import ItemHint
from vlm_ocr.extract import assign, extract_items
from vlm_ocr.types import LayoutBlock

HINT = ItemHint(
    path="pedido",
    columns={
        "producto": "text",
        "cantidad": "quantity",
        "precio": "number_right",
        "observaciones": "observation",
    },
    stop_labels=("COUNTER", "TAX", "AMOUNT DUE", "TENDER", "CHANGE"),
    start_labels=(),
)

SCHEMA = {
    "type": "object",
    "properties": {
        "pedido": {
            "type": "array",
            "x-item-columns": HINT.columns,
            "x-stop-labels": list(HINT.stop_labels),
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
        "total": {"type": ["number", "null"], "x-labels": ["AMOUNT DUE"]},
    },
}


def _block(text: str, x0: float, x1: float, y: float) -> LayoutBlock:
    return LayoutBlock(0, text, 1.0, (x0, y, x1, y + 26))


def _item(text: str, price: str | None, y: float) -> list[LayoutBlock]:
    blocks = [_block(text, 230.0, 412.0, y)]
    if price is not None:
        blocks.append(_block(price, 614.0, 679.0, y))
    return blocks


def _obs(text: str, y: float) -> LayoutBlock:
    return _block(text, 267.0, 391.0, y)


def _ticket_blocks() -> list[LayoutBlock]:
    return [
        _block("CHECK 91", 231.0, 349.0, 249.0),
        *_item("1 Hamburger", "3.60", 300.0),
        _obs("- Tomato", 322.0),
        *_item("1 Db1-Db1", "5.90", 343.0),
        _obs("+ Onion", 369.0),
        _obs("Well Done", 393.0),
        *_item("1 Db1-Db1", "5.90", 416.0),
        _obs("- Lettuce", 441.0),
        _obs("+ Grilled 0", 463.0),
        *_item("3 Fry", "6.90", 488.0),
        *_item("2 Med Soft Drink", "4.50", 513.0),
        *_item("1 Water", None, 535.0),
        *_item("COUNTER-Eat In", "26.80", 588.0),
        _block("TAX 9.50%", 227.0, 330.0, 612.0),
        _block("2.55", 623.0, 677.0, 612.0),
        _block("Amount Due", 226.0, 340.0, 639.0),
        _block("$29.35", 605.0, 676.0, 639.0),
    ]


def test_ticket_rows_become_items() -> None:
    result = extract_items(_ticket_blocks(), HINT)

    assert result.items is not None
    assert [item["producto"] for item in result.items] == [
        "Hamburger",
        "Db1-Db1",
        "Db1-Db1",
        "Fry",
        "Med Soft Drink",
        "Water",
    ]
    assert [item["cantidad"] for item in result.items] == [1, 1, 1, 3, 2, 1]
    assert [item["precio"] for item in result.items] == [3.6, 5.9, 5.9, 6.9, 4.5, None]
    assert result.items[1]["observaciones"] == "+ Onion \nWell Done"
    assert result.items[2]["observaciones"] == "- Lettuce \n+ Grilled 0"
    assert result.items[0]["observaciones"] == "- Tomato"
    assert result.items[5]["observaciones"] is None
    assert result.candidates == 6
    assert result.parsed == 6


def test_stop_label_ends_the_list() -> None:
    result = extract_items(_ticket_blocks()[1:], HINT)

    assert result.items is not None
    products = [item["producto"] for item in result.items]
    assert "COUNTER-Eat In" not in products
    assert all("TAX" not in product for product in products)


def test_start_label_skips_the_header() -> None:
    hint = ItemHint("pedido", HINT.columns, HINT.stop_labels, ("CHECK",))
    result = extract_items(_ticket_blocks(), hint)

    assert result.items is not None
    assert result.items[0]["producto"] == "Hamburger"


def test_observation_before_first_item_aborts() -> None:
    result = extract_items([_obs("- Tomato", 300.0)], HINT)

    assert result.items is None


def test_merged_item_cell_aborts() -> None:
    result = extract_items([_block("1 Hamburger 3.60", 230.0, 680.0, 300.0)], HINT)

    assert result.items is None


def test_empty_list_returns_none() -> None:
    result = extract_items([_block("CHECK 91", 231.0, 349.0, 249.0)], HINT)

    assert result.items is None
    assert result.candidates == 0


def test_assign_integrates_items_and_scalars() -> None:
    assignment = assign(_ticket_blocks(), SCHEMA)

    assert assignment.data["pedido"][0]["producto"] == "Hamburger"
    assert assignment.data["total"] == 29.35
    assert "pedido" in assignment.matched
    assert "pedido" not in assignment.unmatched


def test_assign_marks_items_pending_on_failure() -> None:
    assignment = assign([_block("1 Hamburger 3.60", 230.0, 680.0, 300.0)], SCHEMA)

    assert assignment.data["pedido"] is None
    assert "pedido" in assignment.pending
