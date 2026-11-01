from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest

from vlm_ocr.inputs import (
    detect_document_kind,
    is_stdin,
    read_stdin_bytes,
    stdin_is_tty,
)


@pytest.mark.parametrize(
    ("data", "kind"),
    [
        (b"%PDF-1.7\n", "pdf"),
        (b"\x89PNG\r\n\x1a\nrest", "png"),
        (b"\xff\xd8\xffrest", "jpg"),
        (b"II*\x00rest", "tiff"),
        (b"MM\x00*rest", "tiff"),
        (b"BMrest", "bmp"),
        (b"RIFF\x00\x00\x00\x00WEBPrest", "webp"),
    ],
)
def test_detect_document_kind(data: bytes, kind: str) -> None:
    assert detect_document_kind(data) == kind


def test_detect_document_kind_unknown() -> None:
    assert detect_document_kind(b"no soy un documento") is None


def test_is_stdin() -> None:
    assert is_stdin("-") is True
    assert is_stdin(Path("doc.pdf")) is False


def test_read_stdin_bytes(monkeypatch) -> None:
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(b"\x00\x01")))

    assert read_stdin_bytes() == b"\x00\x01"


def test_read_stdin_bytes_returns_empty(monkeypatch) -> None:
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(b"")))

    assert read_stdin_bytes() == b""


def test_stdin_is_tty(monkeypatch) -> None:
    class TTY:
        def isatty(self) -> bool:
            return True

    monkeypatch.setattr(sys, "stdin", TTY())

    assert stdin_is_tty() is True


def test_stdin_is_not_tty(monkeypatch) -> None:
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(b"")))

    assert stdin_is_tty() is False
