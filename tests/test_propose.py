from __future__ import annotations

import pytest

from vlm_ocr.propose import proposal_fields, rows_text_from_ocr


def test_rows_text_from_ocr_uses_boxes() -> None:
    ocr = {
        "text": "texto plano",
        "blocks": [
            {"page": 0, "text": "SALARIO BASE", "box": [0.0, 0.0, 100.0, 20.0]},
            {"page": 0, "text": "2.406,89", "box": [200.0, 0.0, 300.0, 20.0]},
        ],
    }

    assert rows_text_from_ocr(ocr) == "SALARIO BASE | 2.406,89"


def test_rows_text_from_ocr_falls_back_to_text() -> None:
    assert rows_text_from_ocr({"text": "solo texto", "blocks": []}) == "solo texto"


def test_proposal_fields_maps_and_filters() -> None:
    text = (
        "Concepto | Unidades | Importe | Devengado | A deducir\n"
        "SALARIO BASE | 30,00 | 80,2297 | 2.406,89 |\n"
        "REGULAR SALE\nTOTAL"
    )
    payload = {
        "fields": [
            {
                "name": "Salario Base",
                "type": "number",
                "labels": ["SALARIO BASE", "INVENTADO"],
                "source": "devengado",
            }
        ],
        "lists": [
            {
                "name": "Pedido",
                "text_prop": "Producto",
                "quantity_prop": "Cantidad",
                "number_prop": "Precio",
                "observation_prop": None,
                "start_labels": ["REGULAR SALE"],
                "stop_labels": ["TOTAL", "INVENTADO"],
            }
        ],
    }

    fields = proposal_fields(payload, text)

    assert fields[0] == {
        "kind": "scalar",
        "name": "salario_base",
        "type": "number",
        "labels": ["SALARIO BASE"],
        "source": "devengado",
    }
    assert fields[1] == {
        "kind": "list",
        "name": "pedido",
        "roles": {
            "text": "producto",
            "quantity": "cantidad",
            "number_right": "precio",
            "observation": "",
        },
        "startLabels": ["REGULAR SALE"],
        "stopLabels": ["TOTAL"],
    }


def test_proposal_fields_drops_scalar_without_valid_labels() -> None:
    payload = {
        "fields": [
            {"name": "x", "type": "text", "labels": ["NO EXISTE"], "source": None}
        ],
        "lists": [],
    }

    assert proposal_fields(payload, "texto sin esa etiqueta") == []


def test_proposal_fields_dedupes_names() -> None:
    payload = {
        "fields": [
            {"name": "Total", "type": "number", "labels": ["TOTAL"], "source": ""},
            {"name": "total", "type": "number", "labels": ["TOTAL"], "source": ""},
        ],
        "lists": [],
    }

    names = [field["name"] for field in proposal_fields(payload, "TOTAL 1,00")]

    assert names == ["total", "total_2"]


def test_proposal_fields_skips_list_without_required_roles() -> None:
    payload = {
        "fields": [],
        "lists": [
            {
                "name": "pedido",
                "text_prop": "",
                "quantity_prop": None,
                "number_prop": "precio",
                "observation_prop": None,
                "start_labels": [],
                "stop_labels": ["TOTAL"],
            }
        ],
    }

    assert proposal_fields(payload, "TOTAL") == []


def test_proposal_fields_handles_garbage() -> None:
    assert proposal_fields({}, "texto") == []
    assert proposal_fields({"fields": "no", "lists": [1, 2]}, "texto") == []


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("string", "text"), ("text", "text"), ("date", "date"), ("weird", "text")],
)
def test_proposal_fields_maps_types(raw: str, expected: str) -> None:
    payload = {
        "fields": [
            {"name": "campo", "type": raw, "labels": ["TOTAL"], "source": ""}
        ],
        "lists": [],
    }

    [field] = proposal_fields(payload, "TOTAL")
    assert field["type"] == expected


def test_proposal_fields_drops_numeric_only_labels() -> None:
    payload = {
        "fields": [
            {"name": "number", "type": "number", "labels": ["3.60"], "source": None}
        ],
        "lists": [],
    }

    assert proposal_fields(payload, "3.60") == []


def test_proposal_fields_drops_list_without_anchors() -> None:
    payload = {
        "fields": [],
        "lists": [
            {
                "name": "pedido",
                "text_prop": "producto",
                "quantity_prop": None,
                "number_prop": "precio",
                "observation_prop": None,
                "start_labels": [],
                "stop_labels": [],
            }
        ],
    }

    assert proposal_fields(payload, "1 Water 2.00") == []


def test_proposal_fields_uses_canonical_roles_and_dedupes_lists() -> None:
    payload = {
        "fields": [],
        "lists": [
            {
                "name": "pedido",
                "text_prop": "producto",
                "quantity_prop": "cantidad",
                "number_prop": "precio",
                "observation_prop": "observaciones",
                "start_labels": [],
                "stop_labels": ["TOTAL"],
            },
            {
                "name": "otra",
                "text_prop": "Hamburger",
                "quantity_prop": None,
                "number_prop": "3.60",
                "observation_prop": None,
                "start_labels": [],
                "stop_labels": ["TOTAL"],
            },
        ],
    }

    [field] = proposal_fields(payload, "1 Hamburger 3.60 TOTAL")

    assert field["roles"] == {
        "text": "producto",
        "quantity": "cantidad",
        "number_right": "precio",
        "observation": "observaciones",
    }


def test_proposal_fields_derives_scalar_name_from_label() -> None:
    payload = {
        "fields": [
            {"name": "number", "type": "number", "labels": ["TOTAL"], "source": None}
        ],
        "lists": [],
    }

    [field] = proposal_fields(payload, "TOTAL")

    assert field["name"] == "total"


def test_proposal_fields_drops_source_without_header() -> None:
    payload = {
        "fields": [
            {
                "name": "total",
                "type": "number",
                "labels": ["TOTAL"],
                "source": "base",
            }
        ],
        "lists": [],
    }

    [field] = proposal_fields(payload, "TOTAL 8.40")

    assert field["source"] == ""


def test_proposal_fields_drops_table_headers() -> None:
    text = (
        "Concepto | Unidades | Importe | Devengado | A deducir\n"
        "SALARIO BASE | 30,00 | 80,2297 | 2.406,89 |"
    )
    payload = {
        "fields": [
            {"name": "concepto", "type": "text", "labels": ["Concepto"], "source": ""},
            {"name": "unidades", "type": "number", "labels": ["Unidades"], "source": ""},
            {"name": "salario_base", "type": "number", "labels": ["SALARIO BASE"], "source": "devengado"},
        ],
        "lists": [],
    }

    fields = proposal_fields(payload, text)

    assert [field["name"] for field in fields] == ["salario_base"]
    assert fields[0]["source"] == "devengado"
