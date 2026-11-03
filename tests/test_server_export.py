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
        }
    },
}


def _workspace(tmp_path: Path) -> tuple[Path, str]:
    base = tmp_path / "ws"
    workspace = create_workspace(base, b"%PDF-1.4\n", "doc.pdf")
    root = workspace.root
    (root / "ocr.json").write_text(
        json.dumps(
            {
                "text": "SALARIO BASE 2.406,89",
                "blocks": [
                    {
                        "page": 0,
                        "text": "SALARIO BASE",
                        "box": [40.0, 100.0, 180.0, 116.0],
                    }
                ],
                "pages": [{"index": 0, "width": 1240, "height": 1754}],
                "native_pages": [],
                "dpi": 200,
            }
        ),
        encoding="utf-8",
    )
    (root / "contracts" / "contract.schema.json").write_text(
        json.dumps(SCHEMA), encoding="utf-8"
    )
    (root / "results" / "last.json").write_text(
        json.dumps({"schema": SCHEMA, "extraction": {"data": {"salario_base": 2406.89}}}),
        encoding="utf-8",
    )
    return base, workspace.id


def _client(base: Path) -> TestClient:
    return TestClient(server.create_app(workspace_dir=base, token=TOKEN))


def test_export_schema_result_and_text(tmp_path: Path) -> None:
    base, workspace_id = _workspace(tmp_path)
    client = _client(base)

    schema = client.get(
        f"/api/workspaces/{workspace_id}/export/schema", headers=HEADERS
    )
    assert schema.status_code == 200
    assert schema.headers["content-type"].startswith("application/json")
    assert "attachment" in schema.headers["content-disposition"]
    assert schema.json() == SCHEMA

    result = client.get(
        f"/api/workspaces/{workspace_id}/export/result", headers=HEADERS
    )
    assert result.status_code == 200
    assert result.json()["extraction"]["data"]["salario_base"] == 2406.89

    text = client.get(
        f"/api/workspaces/{workspace_id}/export/text", headers=HEADERS
    )
    assert text.status_code == 200
    assert text.headers["content-type"].startswith("text/markdown")
    assert "SALARIO BASE" in text.text


def test_export_missing_file_returns_404(tmp_path: Path) -> None:
    base = tmp_path / "ws"
    workspace = create_workspace(base, b"%PDF-1.4\n", "doc.pdf")
    client = _client(base)

    response = client.get(
        f"/api/workspaces/{workspace.id}/export/schema", headers=HEADERS
    )

    assert response.status_code == 404


def test_homologate_reports_saved_template(tmp_path: Path, monkeypatch) -> None:
    base, workspace_id = _workspace(tmp_path)

    def fake_run(document, extra):
        report = Path(extra[extra.index("--homologate-report") + 1])
        report.write_text(
            json.dumps(
                {
                    "saved": True,
                    "blocked": False,
                    "unlocated": [],
                    "digest": "abc123",
                }
            ),
            encoding="utf-8",
        )
        return 0, {"data": {"salario_base": 2406.89}}, ""

    monkeypatch.setattr(server, "_run_cli", fake_run)
    client = _client(base)

    response = client.post(
        f"/api/workspaces/{workspace_id}/homologate",
        headers=HEADERS,
        json={"schema": SCHEMA},
    )

    assert response.status_code == 200
    assert response.json() == {"template_saved": True, "digest": "abc123"}


def test_homologate_reports_blocked_without_saving(tmp_path: Path, monkeypatch) -> None:
    base, workspace_id = _workspace(tmp_path)

    def fake_run(document, extra):
        report = Path(extra[extra.index("--homologate-report") + 1])
        report.write_text(
            json.dumps(
                {"saved": False, "blocked": True, "unlocated": ["salario_base"]}
            ),
            encoding="utf-8",
        )
        return 0, {"data": {}}, ""

    monkeypatch.setattr(server, "_run_cli", fake_run)
    client = _client(base)

    response = client.post(
        f"/api/workspaces/{workspace_id}/homologate",
        headers=HEADERS,
        json={"schema": SCHEMA},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["template_saved"] is False
    assert payload["blocked"] is True
    assert payload["unlocated"] == ["salario_base"]


def test_homologate_cli_error_returns_422(tmp_path: Path, monkeypatch) -> None:
    base, workspace_id = _workspace(tmp_path)
    monkeypatch.setattr(
        server, "_run_cli", lambda document, extra: (2, None, "no homologable")
    )
    client = _client(base)

    response = client.post(
        f"/api/workspaces/{workspace_id}/homologate",
        headers=HEADERS,
        json={"schema": SCHEMA},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "no homologable"


def test_recents_and_delete(tmp_path: Path) -> None:
    base = tmp_path / "ws"
    first = create_workspace(base, b"a", "a.pdf", name="Primero")
    second = create_workspace(base, b"b", "b.png", name="Segundo")
    client = _client(base)

    recents = client.get("/api/workspaces", headers=HEADERS)
    assert recents.status_code == 200
    assert [row["id"] for row in recents.json()["workspaces"]] == [
        second.id,
        first.id,
    ]

    deleted = client.delete(f"/api/workspaces/{first.id}", headers=HEADERS)
    assert deleted.status_code == 204

    after = client.get("/api/workspaces", headers=HEADERS)
    assert [row["id"] for row in after.json()["workspaces"]] == [second.id]
