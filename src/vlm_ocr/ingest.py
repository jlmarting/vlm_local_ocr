from __future__ import annotations

from pathlib import Path

import pymupdf

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
    with pymupdf.open(path) as doc:
        for index, page in enumerate(doc):
            text = page.get_text("text") or ""
            if len(text.strip()) >= TEXT_MIN_CHARS:
                pages.append(PageInput(index=index, text=text, image_png=None))
            else:
                pixmap = page.get_pixmap(dpi=dpi)
                pages.append(
                    PageInput(index=index, text=None, image_png=pixmap.tobytes("png"))
                )
    if not pages:
        raise InputError(f"el PDF no tiene páginas: {path}")
    return pages
