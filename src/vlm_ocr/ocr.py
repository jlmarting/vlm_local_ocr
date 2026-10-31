from __future__ import annotations

import io
from functools import lru_cache
from itertools import pairwise

from PIL import Image, ImageOps
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


DESKEW_RANGE = 30
DESKEW_MIN_ANGLE = 0.7
DESKEW_MARGIN = 20


@lru_cache(maxsize=1)
def _engine() -> RapidOCR:
    return RapidOCR()


def _row_profile_score(gray: Image.Image, angle: float) -> int:
    rotated = gray.rotate(angle, resample=Image.BILINEAR, expand=False, fillcolor=255)
    column = rotated.resize((1, rotated.height), Image.BOX)
    values = column.tobytes()
    return sum((right - left) ** 2 for left, right in pairwise(values))


def deskew(image_png: bytes) -> bytes:
    """Endereza una imagen girada y recorta los márgenes blancos.

    Estima el ángulo por el perfil de filas (la proyección horizontal de la tinta se hace
    más contrastada cuando las líneas de texto quedan horizontales), en dos pasadas.
    """
    image = Image.open(io.BytesIO(image_png)).convert("RGB")
    gray = ImageOps.grayscale(image)
    factor = 800 / max(gray.size)
    if factor < 1:
        gray = gray.resize(
            (max(1, int(gray.width * factor)), max(1, int(gray.height * factor))),
            Image.BILINEAR,
        )

    coarse = [index * 1.0 for index in range(-DESKEW_RANGE, DESKEW_RANGE + 1)]
    best = max(coarse, key=lambda angle: _row_profile_score(gray, angle))
    fine = [best + step / 10 for step in range(-10, 11)]
    angle = max(fine, key=lambda candidate: _row_profile_score(gray, candidate))
    if abs(angle) < DESKEW_MIN_ANGLE:
        return image_png

    rotated = image.rotate(angle, resample=Image.BICUBIC, expand=True, fillcolor="white")
    mask = ImageOps.invert(ImageOps.grayscale(rotated)).point(
        lambda value: 255 if value > 20 else 0
    )
    box = mask.getbbox()
    if box is not None:
        left, top, right, bottom = box
        rotated = rotated.crop(
            (
                max(0, left - DESKEW_MARGIN),
                max(0, top - DESKEW_MARGIN),
                min(rotated.width, right + DESKEW_MARGIN),
                min(rotated.height, bottom + DESKEW_MARGIN),
            )
        )
    buffer = io.BytesIO()
    rotated.save(buffer, format="PNG")
    return buffer.getvalue()


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
            result = _engine()(deskew(page.image_png))
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
