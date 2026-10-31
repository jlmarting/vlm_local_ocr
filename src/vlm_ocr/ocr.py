from __future__ import annotations

from functools import lru_cache

from rapidocr import RapidOCR

from .errors import InputError
from .types import LayoutBlock, PageInput

SUPPORTED_LANGS = {
    "default",
    "en",
    "es",
    "fr",
    "de",
    "it",
    "pt",
    "nl",
    "pl",
    "tr",
    "vi",
    "ch",
    "zh",
    "ja",
}


@lru_cache(maxsize=1)
def _engine() -> RapidOCR:
    return RapidOCR()


def ocr_pages(pages: list[PageInput], lang: str = "default") -> list[LayoutBlock]:
    """Extrae bloques de texto de cada página, en orden top-down."""
    if lang not in SUPPORTED_LANGS:
        raise ValueError(
            f"idioma no soportado por los modelos empaquetados: {lang!r}. "
            "Añade el modelo de reconocimiento correspondiente o usa 'default'."
        )

    blocks: list[LayoutBlock] = []
    for page in pages:
        if page.text is not None:
            for line in page.text.splitlines():
                if line.strip():
                    blocks.append(
                        LayoutBlock(page.index, line.strip(), 1.0, (0.0, 0.0, 0.0, 0.0))
                    )
            continue

        if page.image_png is None:
            continue

        try:
            result = _engine()(page.image_png)
        except Exception as exc:
            raise InputError(f"falló el OCR en la página {page.index}: {exc}") from exc
        if result.boxes is None or result.txts is None or len(result.boxes) == 0:
            continue
        scores = result.scores if result.scores is not None else [0.0] * len(result.txts)
        for box, text, score in zip(result.boxes, result.txts, scores):
            xs = [float(point[0]) for point in box]
            ys = [float(point[1]) for point in box]
            blocks.append(
                LayoutBlock(
                    page=page.index,
                    text=str(text),
                    confidence=float(score),
                    box=(min(xs), min(ys), max(xs), max(ys)),
                )
            )

    blocks.sort(key=lambda block: (block.page, block.box[1], block.box[0]))
    return blocks
