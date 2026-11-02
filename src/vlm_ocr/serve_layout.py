from __future__ import annotations

from pathlib import Path

import pypdfium2 as pdfium
from PIL import Image

from .ingest import ingest
from .types import PageInput


def native_pages(pages: list[PageInput]) -> set[int]:
    return {page.index for page in pages if page.text is not None}


def normalize_blocks(
    blocks: list[dict], native_page_indexes: set[int], dpi: int
) -> list[dict]:
    scale = dpi / 72.0
    normalized: list[dict] = []
    for block in blocks:
        box = [float(value) for value in block.get("box") or (0.0, 0.0, 0.0, 0.0)]
        if block.get("page") in native_page_indexes:
            box = [value * scale for value in box]
        normalized.append({**block, "box": box})
    return normalized


def render_pages(
    document: Path, dpi: int, out_dir: Path, pages: list[PageInput]
) -> list[dict]:
    out_dir.mkdir(parents=True, exist_ok=True)
    rendered: list[dict] = []
    pdf = None
    try:
        if document.suffix.lower() == ".pdf":
            pdf = pdfium.PdfDocument(str(document))
        for page in pages:
            path = out_dir / f"page-{page.index:03d}.png"
            if page.image_png is not None:
                path.write_bytes(page.image_png)
            elif pdf is not None:
                bitmap = pdf[page.index].render(scale=dpi / 72)
                bitmap.to_pil().save(path, format="PNG")
            else:
                continue
            with Image.open(path) as image:
                width, height = image.size
            rendered.append(
                {
                    "index": page.index,
                    "width": width,
                    "height": height,
                    "path": str(path),
                }
            )
    finally:
        if pdf is not None:
            pdf.close()
    return rendered


def process_document(document: Path, dpi: int, pages_dir: Path) -> dict:
    pages = ingest(document, dpi)
    rendered = render_pages(document, dpi, pages_dir, pages)
    return {
        "pages": rendered,
        "native_pages": native_pages(pages),
    }
