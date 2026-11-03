from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from vlm_ocr import server
from vlm_ocr.server import create_app

TOKEN = "secreto"


def _text_pdf(path: Path) -> Path:
    document = canvas.Canvas(str(path), pagesize=A4)
    document.setFont("Helvetica", 12)
    document.drawString(72, 720, "Factura de prueba")
    document.drawString(72, 700, "Total: 42,00")
    document.save()
    return path


@pytest.mark.integration
def test_upload_native_pdf_returns_text_blocks_and_page_image(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(server, "_match_template", lambda *args, **kwargs: None)
    source = _text_pdf(tmp_path / "factura.pdf")
    app = create_app(workspace_dir=tmp_path / "workspaces", token=TOKEN)
    client = TestClient(app)
    headers = {"Authorization": f"Bearer {TOKEN}"}

    response = client.post(
        "/api/workspaces",
        headers=headers,
        files={"file": ("factura.pdf", source.read_bytes(), "application/pdf")},
        data={"name": "Factura"},
    )

    assert response.status_code == 201
    payload = response.json()
    document = payload["document"]
    assert "Factura de prueba" in document["text"]
    assert document["blocks"]
    assert document["pages"][0]["width"] > 0
    assert all(block["box"] != [0.0, 0.0, 0.0, 0.0] for block in document["blocks"])

    page = client.get(document["pages"][0]["image_url"], headers=headers)
    assert page.status_code == 200
    assert page.headers["content-type"] == "image/png"

    workspace_id = payload["workspace"]["id"]
    assert (tmp_path / "workspaces" / workspace_id / "ocr.json").exists()


@pytest.mark.integration
def test_upload_requires_token(tmp_path: Path) -> None:
    app = create_app(workspace_dir=tmp_path / "workspaces", token=TOKEN)
    client = TestClient(app)

    response = client.post(
        "/api/workspaces",
        files={"file": ("factura.pdf", b"%PDF-1.4\n", "application/pdf")},
    )

    assert response.status_code == 401
