from __future__ import annotations

import sys
from pathlib import Path

STDIN = "-"

_PNG = b"\x89PNG\r\n\x1a\n"
_WEBP_RIFF = b"RIFF"


def is_stdin(path: Path | str) -> bool:
    """Indica si la entrada es el marcador de stdin."""
    return str(path) == STDIN


def stdin_is_tty() -> bool:
    """Indica si stdin es un terminal interactivo."""
    return bool(getattr(sys.stdin, "isatty", lambda: False)())


def read_stdin_bytes() -> bytes:
    """Lee stdin en binario, sin decidir si está vacío ni decodificar."""
    stream = getattr(sys.stdin, "buffer", sys.stdin)
    return stream.read()


def detect_document_kind(data: bytes) -> str | None:
    """Detecta el tipo de documento por su firma; None si no se reconoce."""
    if data.startswith(b"%PDF-"):
        return "pdf"
    if data.startswith(_PNG):
        return "png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if data.startswith((b"II*\x00", b"MM\x00*")):
        return "tiff"
    if data.startswith(b"BM"):
        return "bmp"
    if len(data) >= 12 and data.startswith(_WEBP_RIFF) and data[8:12] == b"WEBP":
        return "webp"
    return None
