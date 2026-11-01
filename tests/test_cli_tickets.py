from __future__ import annotations

import json
from pathlib import Path

from vlm_ocr import cli
from vlm_ocr.types import LayoutBlock

CONTRACT = Path(__file__).resolve().parents[1] / "examples" / "contrato-ticket.schema.json"


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
        *_item("3 Fry", "6.90", 488.0),
        *_item("1 Water", None, 535.0),
        *_item("COUNTER-Eat In", "26.80", 588.0),
        _block("TAX 9.50%", 227.0, 330.0, 612.0),
        _block("2.55", 623.0, 677.0, 612.0),
        _block("Amount Due", 226.0, 340.0, 639.0),
        _block("$29.35", 605.0, 676.0, 639.0),
    ]


def _doc(tmp_path: Path) -> Path:
    path = tmp_path / "ticket.txt"
    path.write_text("ticket\n", encoding="utf-8")
    return path


def test_item_contract_uses_rows_and_no_llm(monkeypatch, tmp_path: Path, capsys) -> None:
    blocks = _ticket_blocks()
    monkeypatch.setattr(cli, "ocr_pages", lambda pages, lang="default": blocks)

    code = cli.main(
        [
            str(_doc(tmp_path)),
            "--format",
            "json",
            "--contract",
            str(CONTRACT),
            "--contract-kind",
            "schema",
            "--no-llm",
        ]
    )

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["pedido"][0]["producto"] == "Hamburger"
    assert payload["pedido"][0]["cantidad"] == 1
    assert payload["pedido"][0]["observaciones"] == "- Tomato"
    assert payload["pedido"][-1]["precio"] is None
    assert payload["total"] == 29.35


def test_low_item_coverage_warns(monkeypatch, tmp_path: Path, capsys) -> None:
    blocks = [_block("1 Hamburger 3.60", 230.0, 680.0, 300.0)]
    monkeypatch.setattr(cli, "ocr_pages", lambda pages, lang="default": blocks)

    code = cli.main(
        [
            str(_doc(tmp_path)),
            "--format",
            "json",
            "--contract",
            str(CONTRACT),
            "--contract-kind",
            "schema",
            "--no-llm",
        ]
    )

    assert code == 0
    captured = capsys.readouterr()
    assert "cobertura baja" in captured.err
    payload = json.loads(captured.out)
    assert payload["pedido"] is None
