from __future__ import annotations

import json

import pytest

from vlm_ocr.annotations import ColumnSpec, item_hints
from vlm_ocr.errors import ContractError
from vlm_ocr.extract import assign
from vlm_ocr.layout import group_rows
from vlm_ocr.templates import (
    Fingerprint,
    ItemMap,
    Template,
    template_from_dict,
    template_to_dict,
)
from vlm_ocr.types import LayoutBlock

SCHEMA = {
    "type": "object",
    "properties": {
        "movimientos": {
            "type": ["array", "null"],
            "x-item-columns": {
                "fecha": {"x0": 0.0, "x1": 0.25, "type": "text"},
                "concepto": {"x0": 0.25, "x1": 0.55, "type": "text"},
                "importe": {"x0": 0.55, "x1": 0.8, "type": "number"},
                "saldo": {"x0": 0.8, "x1": 1.0, "type": "number"},
            },
            "x-item-labels": ["FECHA"],
            "x-stop-labels": ["TOTAL"],
            "items": {
                "type": "object",
                "properties": {
                    "fecha": {"type": ["string", "null"]},
                    "concepto": {"type": ["string", "null"]},
                    "importe": {"type": ["number", "null"]},
                    "saldo": {"type": ["number", "null"]},
                },
                "additionalProperties": False,
            },
        }
    },
}


def _block(text: str, x0: float, y0: float) -> LayoutBlock:
    return LayoutBlock(0, text, 1.0, (x0, y0, x0 + 150.0, y0 + 18.0))


def _blocks() -> list[LayoutBlock]:
    blocks = [
        _block("FECHA", 0.0, 0.0),
        _block("CONCEPTO", 200.0, 0.0),
        _block("IMPORTE", 500.0, 0.0),
        _block("SALDO", 700.0, 0.0),
    ]
    rows = [
        ("01/02", "Compra", "10,50", "100,50"),
        ("02/02", "Venta", "20,00", "80,50"),
        ("03/02", "Banco", "5,00", "75,50"),
    ]
    for index, (fecha, concepto, importe, saldo) in enumerate(rows, start=1):
        y = index * 40.0
        blocks.extend(
            [
                _block(fecha, 0.0, y),
                _block(concepto, 200.0, y),
                _block(importe, 500.0, y),
                _block(saldo, 700.0, y),
            ]
        )
    blocks.extend([_block("TOTAL", 0.0, 160.0), _block("35,50", 500.0, 160.0)])
    return blocks


def test_extract_columns_reads_arbitrary_columns() -> None:
    assignment = assign(_blocks(), SCHEMA)

    assert assignment.matched == ["movimientos"]
    assert assignment.data["movimientos"] == [
        {"fecha": "01/02", "concepto": "Compra", "importe": 10.5, "saldo": 100.5},
        {"fecha": "02/02", "concepto": "Venta", "importe": 20.0, "saldo": 80.5},
        {"fecha": "03/02", "concepto": "Banco", "importe": 5.0, "saldo": 75.5},
    ]


def test_extract_columns_keeps_missing_values_null() -> None:
    blocks = _blocks()
    # El saldo de la segunda fila no se reconoce.
    blocks = [
        block
        for block in blocks
        if block.text != "80,50"
    ]
    assignment = assign(blocks, SCHEMA)

    assert assignment.data["movimientos"][1]["saldo"] is None


def test_extract_columns_requires_start_labels() -> None:
    schema = json.loads(json.dumps(SCHEMA))
    schema["properties"]["movimientos"]["x-item-labels"] = []

    with pytest.raises(ContractError):
        item_hints(schema)


def test_extract_columns_rejects_mixed_roles() -> None:
    schema = json.loads(json.dumps(SCHEMA))
    schema["properties"]["movimientos"]["x-item-columns"]["producto"] = "text"

    with pytest.raises(ContractError):
        item_hints(schema)


@pytest.mark.parametrize(
    ("x0", "x1"),
    [(0.5, 0.2), (-0.1, 0.2), (0.2, 1.2)],
)
def test_extract_columns_rejects_bad_ranges(x0: float, x1: float) -> None:
    schema = json.loads(json.dumps(SCHEMA))
    schema["properties"]["movimientos"]["x-item-columns"]["fecha"]["x0"] = x0
    schema["properties"]["movimientos"]["x-item-columns"]["fecha"]["x1"] = x1

    with pytest.raises(ContractError):
        item_hints(schema)


def test_extract_columns_rejects_unknown_type() -> None:
    schema = json.loads(json.dumps(SCHEMA))
    schema["properties"]["movimientos"]["x-item-columns"]["fecha"]["type"] = "money"

    with pytest.raises(ContractError):
        item_hints(schema)


def test_template_roundtrip_with_column_spec() -> None:
    template = Template(
        contract_hash="abc",
        fingerprint=Fingerprint(digest="digest", rows=(), columns=()),
        items={
            "movimientos": ItemMap(
                columns={"fecha": ColumnSpec(0.0, 0.25, "text", True)},
                stop_labels=("TOTAL",),
                start_labels=("FECHA",),
            )
        },
    )

    payload = template_to_dict(template)
    assert isinstance(payload["items"]["movimientos"]["columns"]["fecha"], dict)
    restored = template_from_dict(payload)
    columns = restored.items["movimientos"].columns
    assert isinstance(columns["fecha"], ColumnSpec)
    assert columns["fecha"].x1 == 0.25


def test_group_rows_is_stable_for_columns_fixture() -> None:
    rows = group_rows(_blocks())
    assert len(rows) == 5
