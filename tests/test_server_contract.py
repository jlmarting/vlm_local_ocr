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
        "salario_base": {
            "type": ["number", "null"],
            "x-labels": ["SALARIO BASE"],
        },
        "irpf": {
            "type": ["number", "null"],
            "x-labels": ["IRPF"],
        },
        "importe": {
            "type": ["number", "null"],
            "x-labels": ["TOTAL"],
        },
        "extra": {
            "type": ["string", "null"],
            "x-labels": ["NO EXISTE"],
        },
    },
}


def _workspace(tmp_path: Path) -> Path:
    base = tmp_path / "ws"
    workspace = create_workspace(base, b"%PDF-1.4\n", "doc.pdf")
    (workspace.root / "ocr.json").write_text(
        json.dumps(
            {
                "text": "SALARIO BASE 2.406,89\nIRPF",
                "blocks": [
                    {
                        "page": 0,
                        "text": "SALARIO BASE",
                        "box": [40.0, 100.0, 180.0, 116.0],
                    },
                    {
                        "page": 0,
                        "text": "2.406,89",
                        "box": [300.0, 100.0, 400.0, 116.0],
                    },
                    {"page": 0, "text": "IRPF", "box": [40.0, 120.0, 100.0, 136.0]},
                    {"page": 0, "text": "TOTAL", "box": [40.0, 140.0, 100.0, 156.0]},
                    {"page": 0, "text": "N/A", "box": [200.0, 140.0, 260.0, 156.0]},
                ],
                "native_pages": [],
                "dpi": 200,
            }
        ),
        encoding="utf-8",
    )
    return base


def _client(base: Path) -> TestClient:
    return TestClient(server.create_app(workspace_dir=base, token=TOKEN))


def test_contract_endpoint_persists_schema_and_returns_extraction(
    tmp_path: Path, monkeypatch
) -> None:
    base = _workspace(tmp_path)
    monkeypatch.setattr(
        server,
        "_run_cli",
        lambda document, extra: (0, {"data": {"salario_base": 2406.89}}, ""),
    )
    client = _client(base)

    response = client.post(
        f"/api/workspaces/{_only_id(base)}/contract",
        headers=HEADERS,
        json={"schema": SCHEMA},
    )

    assert response.status_code == 200
    extraction = response.json()["extraction"]
    assert extraction["data"]["salario_base"] == 2406.89
    assert extraction["matched"] == ["salario_base"]
    assert extraction["pending"] == ["importe"]
    assert extraction["unmatched"] == ["extra", "irpf"]
    assert extraction["sources"]["salario_base"]["label"] == "SALARIO BASE"

    workspace_id = _only_id(base)
    root = base / workspace_id
    assert (root / "contracts" / "contract.schema.json").exists()
    assert (root / "results" / "last.json").exists()


def test_contract_endpoint_maps_cli_usage_error_to_422(
    tmp_path: Path, monkeypatch
) -> None:
    base = _workspace(tmp_path)
    monkeypatch.setattr(
        server, "_run_cli", lambda document, extra: (2, None, "contrato inválido")
    )
    client = _client(base)

    response = client.post(
        f"/api/workspaces/{_only_id(base)}/contract",
        headers=HEADERS,
        json={"schema": SCHEMA},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "contrato inválido"


def test_contract_endpoint_rejects_invalid_schema(tmp_path: Path) -> None:
    base = _workspace(tmp_path)
    client = _client(base)

    response = client.post(
        f"/api/workspaces/{_only_id(base)}/contract",
        headers=HEADERS,
        json={"schema": [1, 2, 3]},
    )

    assert response.status_code == 422


def test_contract_endpoint_requires_token(tmp_path: Path) -> None:
    base = _workspace(tmp_path)
    client = _client(base)

    response = client.post(
        f"/api/workspaces/{_only_id(base)}/contract",
        json={"schema": SCHEMA},
    )

    assert response.status_code == 401


def _only_id(base: Path) -> str:
    index = json.loads((base / "index.json").read_text(encoding="utf-8"))
    return index["workspaces"][0]["id"]
