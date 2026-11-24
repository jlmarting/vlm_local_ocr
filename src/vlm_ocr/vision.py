from __future__ import annotations

import sys

from .errors import InputError
from .llmrun import BuiltPrompt, Runner
from .types import LayoutBlock, PageInput

VISION_PROMPT = (
    "Transcribe literalmente el texto visible de la imagen, línea a línea, en el orden de "
    "lectura. No traduzcas, no resumas, no añadas comentarios. Si no hay texto, responde con "
    "una línea vacía."
)


def build_prompt(image_png: bytes) -> BuiltPrompt:
    """Prompt de transcripción para una página rasterizada."""
    return BuiltPrompt(images=(image_png,), text_for_tokens=VISION_PROMPT)


def transcribe_pages(
    pages: list[PageInput],
    runner: Runner,
    *,
    max_tokens: int,
) -> list[LayoutBlock]:
    """Transcribe cada página rasterizada y devuelve sus líneas como bloques.

    Las páginas con capa de texto nativa no se envían al modelo (son más fiables y gratis).
    """
    raster = [page for page in pages if page.text is None and page.image_png is not None]
    blocks: list[LayoutBlock] = []
    for page in raster:
        content, _usage, _finish = runner.complete(build_prompt(page.image_png), max_tokens)
        lines = [line.strip() for line in (content or "").splitlines() if line.strip()]
        if not lines:
            print(
                f"aviso: el modelo de visión no devolvió texto en la página {page.index}",
                file=sys.stderr,
            )
            continue
        blocks.extend(
            LayoutBlock(page.index, line, 0.0, (0.0, 0.0, 0.0, 0.0)) for line in lines
        )
    if raster and not blocks:
        raise InputError("el modelo de visión no devolvió texto en ninguna página")
    return blocks
