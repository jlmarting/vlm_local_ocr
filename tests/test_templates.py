from __future__ import annotations

import json

from vlm_ocr.templates import (
    FieldMap,
    Template,
    best_template,
    contract_hash,
    list_templates,
    save_template,
    score_template,
    signature,
)
from vlm_ocr.types import LayoutBlock

LABELS = ["CLIENTE", "NUM PEDIDO", "FECHA", "TOTAL"]


def _block(text: str, x: float, y: float, page: int = 0, width: float = 80.0) -> LayoutBlock:
    return LayoutBlock(page, text, 1.0, (x, y, x + width, y + 10))


def _order(values: tuple[str, str, str, str] = ("ACME", "123", "01/01/2026", "9,99")):
    return [
        _block("CLIENTE", 10, 0),
        _block(values[0], 100, 0),
        _block("NUM PEDIDO", 10, 12),
        _block(values[1], 100, 12),
        _block("FECHA", 10, 24),
        _block(values[2], 100, 24),
        _block("TOTAL", 10, 36),
        _block(values[3], 100, 36),
    ]


def _scaled(blocks: list[LayoutBlock], factor: float) -> list[LayoutBlock]:
    return [
        LayoutBlock(
            block.page,
            block.text,
            block.confidence,
            tuple(value * factor for value in block.box),  # type: ignore[arg-type]
        )
        for block in blocks
    ]


def _template(fp, *, contract: str = "a" * 64, mapping: dict | None = None) -> Template:
    return Template(
        contract_hash=contract,
        fingerprint=fp,
        map=mapping
        if mapping is not None
        else {"total": FieldMap(labels=("TOTAL",), source=None)},
    )


def test_signature_is_stable_across_values() -> None:
    first = signature(_order(), LABELS)
    second = signature(_order(("OTRO CLIENTE", "999", "02/02/2026", "1.234,56")), LABELS)

    assert first is not None and second is not None
    assert first.digest == second.digest


def test_signature_ignores_letterhead_and_observations() -> None:
    plain = signature(_order(), LABELS)
    noisy = signature(
        _order()
        + [
            _block("ACME PEDIDOS S.L.", 10, -24),
            _block("OBSERVACIONES", 10, 48),
            _block("entregar antes de las 18 h", 100, 48),
        ],
        LABELS,
    )

    assert plain is not None and noisy is not None
    assert plain.digest == noisy.digest


def test_signature_is_stable_across_scale() -> None:
    base = signature(_order(), LABELS)
    scaled = signature(_scaled(_order(), 2.3), LABELS)

    assert base is not None and scaled is not None
    assert base.digest == scaled.digest


def test_signature_changes_with_label_order() -> None:
    base = signature(_order(), LABELS)
    reordered = signature(
        [
            _block("TOTAL", 10, 0),
            _block("9,99", 100, 0),
            _block("CLIENTE", 10, 12),
            _block("ACME", 100, 12),
            _block("NUM PEDIDO", 10, 24),
            _block("123", 100, 24),
            _block("FECHA", 10, 36),
            _block("01/01/2026", 100, 36),
        ],
        LABELS,
    )

    assert base is not None and reordered is not None
    assert base.digest != reordered.digest


def test_signature_changes_with_label_column() -> None:
    base = signature(_order(), LABELS)
    moved = _order()
    moved[0] = _block("CLIENTE", 300, 0)
    changed = signature(moved, LABELS)

    assert base is not None and changed is not None
    assert base.digest != changed.digest


def test_signature_needs_relevant_labels() -> None:
    assert signature(_order(), []) is None
    assert signature(_order(), ["NO EXISTE"]) is None


def test_signature_includes_column_headers() -> None:
    blocks = [
        _block("CONCEPTO", 10, 0),
        _block("UNIDADES", 100, 0),
        _block("IMPORTE", 200, 0),
        _block("SALARIO BASE", 10, 12),
        _block("1", 100, 12),
        _block("2.000,00", 200, 12),
    ]
    with_header = signature(blocks, ["SALARIO BASE"])
    without_header = signature(blocks[3:], ["SALARIO BASE"])

    assert with_header is not None and without_header is not None
    assert with_header.columns == ("unidades", "importe")
    assert with_header.digest != without_header.digest


def test_contract_hash_is_canonical() -> None:
    assert contract_hash({"b": 1, "a": 2}) == contract_hash({"a": 2, "b": 1})


def test_save_and_list_variants_under_one_contract(tmp_path) -> None:
    fp_one = signature(_order(), LABELS)
    fp_two = signature(_order(("ACME", "123", "01/01/2026", "9,99")), LABELS)
    other = signature(
        [
            _block("CLIENTE", 10, 0),
            _block("ACME", 400, 0),
            _block("TOTAL", 10, 40),
            _block("9,99", 400, 40),
        ],
        LABELS,
    )
    assert fp_one is not None and fp_two is not None and other is not None
    assert fp_one.digest == fp_two.digest
    assert other.digest != fp_one.digest

    save_template(fp_one, _template(fp_one), directory=tmp_path)
    save_template(other, _template(other), directory=tmp_path)

    found = list_templates("a" * 64, directory=tmp_path)

    assert {item.fingerprint.digest for item in found} == {fp_one.digest, other.digest}


def test_save_versions_and_archives(tmp_path) -> None:
    fp = signature(_order(), LABELS)
    assert fp is not None

    first = save_template(fp, _template(fp), directory=tmp_path)
    second = save_template(fp, _template(fp), directory=tmp_path)

    assert first.version == 1
    assert second.version == 2
    history = tmp_path / ("a" * 64) / "history" / f"{fp.digest}.v1.json"
    assert history.is_file()


def test_template_does_not_store_values(tmp_path) -> None:
    fp = signature(_order(("ACME", "123", "01/01/2026", "987,65")), LABELS)
    assert fp is not None

    save_template(fp, _template(fp), directory=tmp_path)
    path = tmp_path / ("a" * 64) / f"{fp.digest}.json"
    text = path.read_text(encoding="utf-8")

    assert "987,65" not in text
    assert json.loads(text)["map"]["total"]["labels"] == ["TOTAL"]


def test_contract_mismatch_is_not_listed(tmp_path) -> None:
    fp = signature(_order(), LABELS)
    assert fp is not None
    save_template(fp, _template(fp), directory=tmp_path)

    assert list_templates("b" * 64, directory=tmp_path) == []


def test_score_exact_match_is_one(tmp_path) -> None:
    fp = signature(_order(), LABELS)
    assert fp is not None
    tpl = _template(fp)

    assert score_template(_order(), tpl) == 1.0


def test_score_tolerates_small_layout_jitter(tmp_path) -> None:
    fp = signature(_order(), LABELS)
    assert fp is not None
    tpl = _template(fp)
    shifted = [
        LayoutBlock(block.page, block.text, block.confidence,
                    (block.box[0] + 2, block.box[1] + 1, block.box[2] + 2, block.box[3] + 1))
        for block in _order()
    ]

    assert score_template(shifted, tpl) >= 0.85


def test_best_template_rejects_ambiguous_margin(tmp_path) -> None:
    one = signature(_order(), ["CLIENTE", "TOTAL"])
    two = signature(_order(), ["CLIENTE", "FECHA"])
    assert one is not None and two is not None
    assert one.digest != two.digest
    save_template(
        one,
        _template(one, mapping={"total": FieldMap(labels=("TOTAL",), source=None)}),
        directory=tmp_path,
    )
    save_template(
        two,
        _template(two, mapping={"fecha": FieldMap(labels=("FECHA",), source=None)}),
        directory=tmp_path,
    )

    assert best_template(_order(), "a" * 64, directory=tmp_path) is None


def test_hint_from_template_reuses_assign() -> None:
    from vlm_ocr.extract import assign

    contract = {
        "type": "object",
        "properties": {
            "cliente": {"type": "string"},
            "total": {"type": "number"},
        },
    }
    fp = signature(_order(), LABELS)
    assert fp is not None
    tpl = Template(
        contract_hash=contract_hash(contract),
        fingerprint=fp,
        map={
            "cliente": FieldMap(labels=("CLIENTE",), source=None),
            "total": FieldMap(labels=("TOTAL",), source=None),
        },
    )
    from vlm_ocr.templates import hint_from_template

    hint = hint_from_template(tpl, contract)
    result = assign(_order(), hint)

    assert result.data["cliente"] == "ACME"
    assert result.data["total"] == 9.99


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
        "total": {"type": ["number", "null"], "x-labels": ["TOTAL"]},
    },
}


def test_template_roundtrip_preserves_items() -> None:
    from vlm_ocr.templates import ItemMap, template_from_dict, template_to_dict

    fp = signature(_order(), LABELS)
    assert fp is not None
    tpl = Template(
        contract_hash="c" * 64,
        fingerprint=fp,
        map={"total": FieldMap(labels=("TOTAL",), source=None)},
        items={
            "pedido": ItemMap(
                columns={"producto": "text", "precio": "number_right"},
                stop_labels=("TAX",),
                start_labels=("CHECK",),
            )
        },
    )

    again = template_from_dict(template_to_dict(tpl))

    assert again.items["pedido"].columns["precio"] == "number_right"
    assert again.items["pedido"].stop_labels == ("TAX",)
    assert again.items["pedido"].start_labels == ("CHECK",)


def test_old_template_without_items_loads() -> None:
    from vlm_ocr.templates import template_from_dict

    old = {
        "contract_hash": "d" * 64,
        "digest": "e" * 64,
        "fingerprint": {"rows": [], "columns": []},
        "map": {},
    }

    assert template_from_dict(old).items == {}


def test_hint_from_template_reinjects_item_annotations() -> None:
    from vlm_ocr.templates import ItemMap, hint_from_template

    fp = signature(_order(), LABELS)
    assert fp is not None
    tpl = Template(
        contract_hash=contract_hash(ITEM_CONTRACT),
        fingerprint=fp,
        map={"total": FieldMap(labels=("TOTAL",), source=None)},
        items={
            "pedido": ItemMap(
                columns={
                    "producto": "text",
                    "cantidad": "quantity",
                    "precio": "number_right",
                    "observaciones": "observation",
                },
                stop_labels=("TAX",),
                start_labels=("CHECK",),
            )
        },
    )

    hint = hint_from_template(tpl, ITEM_CONTRACT)
    pedido = hint["properties"]["pedido"]

    assert pedido["x-item-columns"]["precio"] == "number_right"
    assert pedido["x-stop-labels"] == ["TAX"]
    assert pedido["x-item-labels"] == ["CHECK"]
    assert pedido["items"] == ITEM_CONTRACT["properties"]["pedido"]["items"]


def test_template_dir_usa_paths(monkeypatch, tmp_path):
    from vlm_ocr import paths, templates

    monkeypatch.setattr(paths, "data_dir", lambda: tmp_path / "datos")
    assert templates.template_dir() == tmp_path / "datos" / "templates"


def test_template_dir_explicito_manda(tmp_path):
    from vlm_ocr import templates

    assert templates.template_dir(tmp_path / "x") == tmp_path / "x"
