from __future__ import annotations

import io
from pathlib import Path

import pypdfium2 as pdfium

from .errors import InputError
from .types import PageInput

TEXT_MIN_CHARS = 20
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}


def ingest(path: Path | str, dpi: int = 200) -> list[PageInput]:
    """Convierte un fichero en páginas listas para OCR o texto nativo."""
    path = Path(path)
    if not path.exists():
        raise InputError(f"no existe el fichero: {path}")

    suffix = path.suffix.lower()
    if suffix == ".pdf":
        try:
            return _ingest_pdf(path, dpi)
        except InputError:
            raise
        except Exception as exc:
            raise InputError(f"no se pudo leer el PDF {path}: {exc}") from exc
    if suffix in IMAGE_EXTENSIONS:
        try:
            data = path.read_bytes()
        except OSError as exc:
            raise InputError(f"no se pudo leer la imagen {path}: {exc}") from exc
        if not data:
            raise InputError(f"la imagen está vacía: {path}")
        return [PageInput(index=0, text=None, image_png=data)]
    raise InputError(f"formato no soportado: {suffix or '(sin extensión)'}")


def _ingest_pdf(path: Path, dpi: int) -> list[PageInput]:
    pages: list[PageInput] = []
    pdf = pdfium.PdfDocument(str(path))
    try:
        count = len(pdf)
        if count == 0:
            raise InputError(f"el PDF no tiene páginas: {path}")
        for index in range(count):
            page = pdf[index]
            try:
                text = page.get_textpage().get_text_range() or ""
            except pdfium.PdfiumError:
                text = ""
            if len(text.strip()) >= TEXT_MIN_CHARS:
                pages.append(PageInput(index=index, text=text, image_png=None))
            else:
                bitmap = page.render(scale=dpi / 72)
                image = bitmap.to_pil()
                buffer = io.BytesIO()
                image.save(buffer, format="PNG")
                pages.append(
                    PageInput(index=index, text=None, image_png=buffer.getvalue())
                )
    finally:
        pdf.close()
    return pages
