from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PageInput:
    """Una página de entrada: texto nativo, imagen rasterizada, o ambos."""

    index: int
    text: str | None
    image_png: bytes | None


@dataclass(frozen=True)
class LayoutBlock:
    """Un bloque de texto detectado, con su caja (x0, y0, x1, y1)."""

    page: int
    text: str
    confidence: float
    box: tuple[float, float, float, float]
