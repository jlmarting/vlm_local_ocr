from __future__ import annotations

import io
import json
import subprocess
import sys

import pytest
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

pytestmark = pytest.mark.integration


def _text_pdf_bytes() -> bytes:
    buffer = io.BytesIO()
    doc = canvas.Canvas(buffer, pagesize=A4)
    doc.drawString(
        72,
        800,
        "Factura de prueba con capa de texto nativa y longitud suficiente.",
    )
    doc.showPage()
    doc.save()
    return buffer.getvalue()


def test_document_from_stdin_pipe() -> None:
    process = subprocess.Popen(
        [sys.executable, "-m", "vlm_ocr", "-", "--format", "json"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    stdout, stderr = process.communicate(_text_pdf_bytes(), timeout=60)

    assert process.returncode == 0, stderr.decode("utf-8", "replace")
    payload = json.loads(stdout)
    assert "Factura de prueba" in payload["text"]


def test_text_from_stdin_pipe() -> None:
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "vlm_ocr",
            "-",
            "--format",
            "json",
            "--input-format",
            "txt",
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    stdout, stderr = process.communicate(b"TOTAL | 29.35\n", timeout=60)

    assert process.returncode == 0, stderr.decode("utf-8", "replace")
    assert "TOTAL | 29.35" in json.loads(stdout)["text"]
