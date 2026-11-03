from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

from vlm_ocr import server

TOKEN = "secreto"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}


def _client() -> TestClient:
    return TestClient(server.create_app(workspace_dir=Path("/tmp/ws"), token=TOKEN))


def test_list_templates(monkeypatch) -> None:
    rows = [
        SimpleNamespace(
            contract_hash="hash1",
            digest="digest1",
            version=2,
            updated_at="2026-11-03T10:00:00Z",
            map={"a": object()},
            items={"b": object()},
        ),
        SimpleNamespace(
            contract_hash="hash2",
            digest="digest2",
            version=1,
            updated_at="2026-11-04T10:00:00Z",
            map={},
            items={},
        ),
    ]
    monkeypatch.setattr(server.templates, "all_templates", lambda: rows)
    client = _client()

    response = client.get("/api/templates", headers=HEADERS)

    assert response.status_code == 200
    templates = response.json()["templates"]
    assert [row["digest"] for row in templates] == ["digest2", "digest1"]
    assert templates[0]["fields_mapped"] == 0
    assert templates[1]["fields_mapped"] == 1
    assert templates[1]["items_mapped"] == 1


def test_delete_template(monkeypatch) -> None:
    dropped: list[str] = []
    template = SimpleNamespace(
        contract_hash="hash1",
        digest="digest1",
        version=1,
        updated_at="",
        map={},
        items={},
    )
    monkeypatch.setattr(server.templates, "find_templates", lambda prefix: [template])
    monkeypatch.setattr(
        server.templates, "drop_template", lambda item: dropped.append(item.digest)
    )
    client = _client()

    response = client.delete("/api/templates/digest1", headers=HEADERS)

    assert response.status_code == 204
    assert dropped == ["digest1"]


def test_delete_unknown_template(monkeypatch) -> None:
    monkeypatch.setattr(server.templates, "find_templates", lambda prefix: [])
    client = _client()

    response = client.delete("/api/templates/nope", headers=HEADERS)

    assert response.status_code == 404


def test_delete_ambiguous_template(monkeypatch) -> None:
    monkeypatch.setattr(
        server.templates,
        "find_templates",
        lambda prefix: [SimpleNamespace(digest="a"), SimpleNamespace(digest="b")],
    )
    client = _client()

    response = client.delete("/api/templates/a", headers=HEADERS)

    assert response.status_code == 409


def test_templates_require_token() -> None:
    client = _client()

    assert client.get("/api/templates").status_code == 401
