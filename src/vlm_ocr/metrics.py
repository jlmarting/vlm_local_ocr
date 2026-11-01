from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from .types import LayoutBlock


def empty_report() -> dict[str, Any]:
    """Esqueleto del informe: claves estables, valores desconocidos a None."""
    return {
        "file": {"path": None, "size_bytes": None, "format": None, "pages": None},
        "ingest": {
            "time_ms": None,
            "native_pages": None,
            "rasterized_pages": None,
            "dpi": None,
        },
        "ocr": {"time_ms": None, "blocks": None, "mean_confidence": None},
        "llm": {
            "enabled": False,
            "model": None,
            "provider": None,
            "load_time_ms": None,
            "time_ms": None,
            "attempts": None,
            "prompt_tokens": None,
            "completion_tokens": None,
            "total_tokens": None,
            "tokens_per_second": None,
            "finish_reason": None,
        },
        "output": {"format": None, "size_bytes": None},
        "extract": {
            "deterministic": None,
            "llm": False,
            "unmatched": None,
            "pending": None,
            "coverage": None,
        },
        "template": {
            "found": False,
            "digest": None,
            "score": None,
            "version": None,
            "coverage": None,
            "homologated": False,
            "drift": False,
        },
        "verify": {"errors": []},
        "total": {"time_ms": None},
        "error": None,
    }


def mean_confidence(
    blocks: list[LayoutBlock], raster_pages: set[int]
) -> float | None:
    """Confianza media de los bloques OCR reales (las páginas nativas valen 1.0 sintético)."""
    values = [block.confidence for block in blocks if block.page in raster_pages]
    if not values:
        return None
    return round(sum(values) / len(values), 4)


def emit(report: dict[str, Any], *, to_stderr: bool, out: Path | None) -> None:
    """Escribe el informe: a fichero y/o a stderr, en una línea JSON."""
    text = json.dumps(report, ensure_ascii=False)
    if out is not None:
        Path(out).write_text(text + "\n", encoding="utf-8")
    if to_stderr:
        print(text, file=sys.stderr)
