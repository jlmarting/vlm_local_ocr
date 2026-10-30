from __future__ import annotations

import io
import re
from pathlib import Path

import pymupdf
import pytest
from PIL import Image, ImageDraw, ImageFont

from vlm_ocr.contract import infer_contract, validate_payload
from vlm_ocr.ingest import ingest
from vlm_ocr.ocr import ocr_pages
from vlm_ocr.output import to_markdown

MODEL = Path(__file__).resolve().parents[2] / "models" / "qwen2.5-0.5b-instruct-q4_k_m.gguf"
FONT = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not MODEL.exists(), reason=f"falta el modelo {MODEL.name}"),
]


def _text_pdf(path: Path) -> Path:
    doc = pymupdf.open()
    page = doc.new_page()
    lines = [
        "Factura",
        "Cliente: ACME S.L.",
        "Total: 123,45 EUR",
        "Fecha: 2026-10-30",
    ]
    for i, line in enumerate(lines):
        page.insert_text((72, 72 + i * 24), line, fontsize=14)
    doc.save(path)
    doc.close()
    return path


def _scanned_pdf(path: Path) -> Path:
    img = Image.new("RGB", (600, 220), "white")
    draw = ImageDraw.Draw(img)
    font = ImageFont.truetype(str(FONT), 28) if FONT.exists() else ImageFont.load_default()
    lines = [
        "RECIBO",
        "Proveedor: Beta Corp",
        "Importe: 50,00 EUR",
        "Fecha: 2026-09-15",
    ]
    for i, line in enumerate(lines):
        draw.text((30, 20 + i * 48), line, fill="black", font=font)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    doc = pymupdf.open()
    page = doc.new_page(width=600, height=220)
    page.insert_image(page.rect, stream=buf.getvalue())
    doc.save(path)
    doc.close()
    return path


def _normalize(value: object) -> str:
    return re.sub(r"\s+", " ", str(value)).strip().lower()


def _number(value: object) -> float | None:
    if isinstance(value, int | float) and not isinstance(value, bool):
        return float(value)
    if isinstance(value, str):
        match = re.search(r"-?\d+(?:[.,]\d+)?", value)
        if match:
            return float(match.group(0).replace(",", "."))
    return None


def _extract(path: Path, contract: dict) -> dict:
    pages = ingest(path)
    blocks = ocr_pages(pages)
    data = infer_contract(to_markdown(blocks), contract, "example", MODEL)
    assert validate_payload(data, contract, "example") == []
    return data


def test_golden_native_pdf(tmp_path: Path) -> None:
    contract = {"cliente": "texto", "total": 0.0, "fecha": "texto"}
    data = _extract(_text_pdf(tmp_path / "factura.pdf"), contract)

    checks = [
        "acme" in _normalize(data.get("cliente")),
        _number(data.get("total")) == pytest.approx(123.45, abs=0.01),
        "2026-10-30" in _normalize(data.get("fecha")),
    ]
    assert sum(checks) >= 2, data


def test_golden_scanned_pdf(tmp_path: Path) -> None:
    contract = {"proveedor": "texto", "importe": 0.0, "fecha": "texto"}
    data = _extract(_scanned_pdf(tmp_path / "recibo.pdf"), contract)

    checks = [
        "beta" in _normalize(data.get("proveedor")),
        _number(data.get("importe")) == pytest.approx(50.0, abs=0.01),
        "2026-09-15" in _normalize(data.get("fecha")),
    ]
    assert sum(checks) >= 2, data
