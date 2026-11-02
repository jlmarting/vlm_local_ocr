from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from vlm_ocr import server
from vlm_ocr.workspace import create_workspace

TOKEN = "secreto"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}

SCHEMA = {
    "type": "object",
    "properties": {
        "pedido": {
            "type": ["array", "null"],
            "x-item-columns": {
                "producto": "text",
                "cantidad": "quantity",
                "precio": "number_right",
            },
            "x-stop-labels": ["TOTAL"],
            "items": {
                "type": "object",
                "required": ["producto", "precio"],
                "properties": {
                    "producto": {"type": "string"},
                    "cantidad": {"type": ["integer", "null"]},
                    "precio": {"type": ["number", "null"]},
                },
                "additionalProperties": False,
            },
        }
    },
}

ITEMS = [
    {"producto": "Hamburger", "cantidad": 1, "precio": 3.6},
    {"producto": "Water", "cantidad": 1, "precio": 1.5},
]


def _workspace(tmp_path: Path) -> tuple[Path, str]:
    base = tmp_path / "ws"
    workspace = create_workspace(base, b"%PDF-1.4\n", "ticket.pdf")
    (workspace.root / "ocr.json").write_text(
        json.dumps(
            {
                "text": "1 Hamburger 3.60\n1 Water 1.50\nTOTAL 5.10",
                "blocks": [
                    {"page": 0, "text": "1 Hamburger", "box": [40.0, 100.0, 180.0, 116.0]},
                    {"page": 0, "text": "3.60", "box": [300.0, 100.0, 360.0, 116.0]},
                    {"page": 0, "text": "1 Water", "box": [40.0, 120.0, 180.0, 136.0]},
                    {"page": 0, "text": "1.50", "box": [300.0, 120.0, 360.0, 136.0]},
                    {"page": 0, "text": "TOTAL", "box": [40.0, 140.0, 120.0, 156.0]},
                    {"page": 0, "text": "5.10", "box": [300.0, 140.0, 360.0, 156.0]},
                ],
                "pages": [{"index": 0, "width": 600, "height": 300}],
                "native_pages": [],
                "dpi": 200,
            }
        ),
        encoding="utf-8",
    )
    return base, workspace.id


def _client(base: Path) -> TestClient:
    return TestClient(server.create_app(workspace_dir=base, token=TOKEN))


def test_contract_endpoint_returns_repeated_list(tmp_path: Path, monkeypatch) -> None:
    base, workspace_id = _workspace(tmp_path)
    monkeypatch.setattr(
        server,
        "_run_cli",
        lambda document, extra: (0, {"data": {"pedido": ITEMS}}, ""),
    )
    client = _client(base)

    response = client.post(
        f"/api/workspaces/{workspace_id}/contract",
        headers=HEADERS,
        json={"schema": SCHEMA},
    )

    assert response.status_code == 200
    extraction = response.json()["extraction"]
    assert extraction["data"]["pedido"] == ITEMS
    assert "pedido" in extraction["matched"]

    schema = client.get(
        f"/api/workspaces/{workspace_id}/export/schema", headers=HEADERS
    )
    assert schema.status_code == 200
    exported = schema.json()
    assert exported["properties"]["pedido"]["x-item-columns"] == {
        "producto": "text",
        "cantidad": "quantity",
        "precio": "number_right",
    }
    assert exported["properties"]["pedido"]["x-stop-labels"] == ["TOTAL"]


def test_contract_endpoint_marks_list_pending_when_no_items(
    tmp_path: Path, monkeypatch
) -> None:
    base, workspace_id = _workspace(tmp_path)
    (base / workspace_id / "ocr.json").write_text(
        json.dumps(
            {
                "text": "TOTAL 5.10",
                "blocks": [
                    {"page": 0, "text": "TOTAL", "box": [40.0, 100.0, 120.0, 116.0]},
                    {"page": 0, "text": "5.10", "box": [300.0, 100.0, 360.0, 116.0]},
                ],
                "pages": [{"index": 0, "width": 600, "height": 300}],
                "native_pages": [],
                "dpi": 200,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        server,
        "_run_cli",
        lambda document, extra: (0, {"data": {"pedido": None}}, ""),
    )
    client = _client(base)

    response = client.post(
        f"/api/workspaces/{workspace_id}/contract",
        headers=HEADERS,
        json={"schema": SCHEMA},
    )

    assert response.status_code == 200
    extraction = response.json()["extraction"]
    assert "pedido" not in extraction["matched"]
    assert "pedido" in extraction["pending"]
