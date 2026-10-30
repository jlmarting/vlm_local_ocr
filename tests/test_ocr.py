from __future__ import annotations

import io

import pytest
from PIL import Image, ImageDraw

from vlm_ocr.ocr import ocr_pages
from vlm_ocr.types import PageInput


def _image_with_text(text: str = "HOLA") -> bytes:
    img = Image.new("RGB", (240, 90), "white")
    ImageDraw.Draw(img).text((10, 30), text, fill="black")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_ocr_reads_text_from_image() -> None:
    blocks = ocr_pages([PageInput(0, None, _image_with_text())])

    assert blocks
    joined = "".join(b.text.upper().replace(" ", "") for b in blocks)
    assert "HOLA" in joined
    for block in blocks:
        x0, y0, x1, y1 = block.box
        assert block.confidence > 0.0
        assert x0 < x1 and y0 < y1
        assert block.page == 0


def test_native_text_is_not_ocrd_and_keeps_lines() -> None:
    blocks = ocr_pages([PageInput(0, "linea uno\nlinea dos", None)])

    assert [b.text for b in blocks] == ["linea uno", "linea dos"]
    assert all(b.confidence == 1.0 and b.box == (0.0, 0.0, 0.0, 0.0) for b in blocks)


def test_unsupported_language_raises_with_hint() -> None:
    with pytest.raises(ValueError, match="idioma"):
        ocr_pages([PageInput(0, None, _image_with_text())], lang="ar")
