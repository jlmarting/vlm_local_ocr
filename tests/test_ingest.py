from __future__ import annotations

import io
from pathlib import Path

import pytest
from PIL import Image, ImageDraw
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

from vlm_ocr.errors import InputError
from vlm_ocr.ingest import ingest


def _make_text_pdf(path: Path, pages: int = 1) -> Path:
    doc = canvas.Canvas(str(path), pagesize=A4)
    for i in range(pages):
        doc.drawString(
            72,
            800,
            f"Pagina {i + 1}. Este PDF tiene una capa de texto nativa y suficiente longitud.",
        )
        doc.showPage()
    doc.save()
    return path


def _make_scanned_pdf(path: Path) -> Path:
    img = Image.new("RGB", (300, 120), "white")
    draw = ImageDraw.Draw(img)
    draw.text((10, 40), "TEXTO ESCANEADO", fill="black")
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    buffer.seek(0)

    doc = canvas.Canvas(str(path), pagesize=(300, 120))
    doc.drawImage(ImageReader(buffer), 0, 0, width=300, height=120)
    doc.showPage()
    doc.save()
    return path


def _make_image(path: Path) -> Path:
    img = Image.new("RGB", (200, 60), "white")
    ImageDraw.Draw(img).text((10, 20), "CAPTURA", fill="black")
    img.save(path, format="PNG")
    return path


def test_pdf_with_text_layer_uses_native_text(tmp_path: Path) -> None:
    pdf = _make_text_pdf(tmp_path / "texto.pdf")

    pages = ingest(pdf)

    assert len(pages) == 1
    assert pages[0].index == 0
    assert pages[0].image_png is None
    assert "capa de texto nativa" in (pages[0].text or "")


def test_pdf_without_text_layer_is_rasterized(tmp_path: Path) -> None:
    pdf = _make_scanned_pdf(tmp_path / "escaneado.pdf")

    pages = ingest(pdf)

    assert len(pages) == 1
    assert pages[0].text is None
    assert pages[0].image_png is not None
    assert pages[0].image_png.startswith(b"\x89PNG")


def test_multipage_pdf_keeps_page_indexes(tmp_path: Path) -> None:
    pdf = _make_text_pdf(tmp_path / "dos.pdf", pages=2)

    pages = ingest(pdf)

    assert [p.index for p in pages] == [0, 1]


def test_image_input_is_a_single_page(tmp_path: Path) -> None:
    image = _make_image(tmp_path / "captura.png")

    pages = ingest(image)

    assert len(pages) == 1
    assert pages[0].index == 0
    assert pages[0].text is None
    assert pages[0].image_png == image.read_bytes()


def test_unsupported_extension_raises(tmp_path: Path) -> None:
    path = tmp_path / "nota.txt"
    path.write_text("hola")

    with pytest.raises(InputError, match="no soportado"):
        ingest(path)


def test_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(InputError, match="no existe"):
        ingest(tmp_path / "no-existe.pdf")


def test_ingest_pdf_from_bytes_matches_file(tmp_path: Path) -> None:
    path = _make_text_pdf(tmp_path / "texto.pdf", pages=2)

    pages = ingest("-", data=path.read_bytes(), kind="pdf")

    assert [p.text for p in pages] == [p.text for p in ingest(path)]


def test_ingest_image_from_bytes(tmp_path: Path) -> None:
    path = _make_image(tmp_path / "captura.png")
    raw = path.read_bytes()

    pages = ingest("-", data=raw, kind="png")

    assert len(pages) == 1
    assert pages[0].image_png == raw
    assert pages[0].text is None


def test_ingest_pdf_from_bytes_reports_stdin() -> None:
    with pytest.raises(InputError, match="stdin"):
        ingest("-", data=b"no es un pdf", kind="pdf")
