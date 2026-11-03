from __future__ import annotations

import json
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


def test_match_template_with_contract_copy(tmp_path: Path, monkeypatch) -> None:
    template_dir = tmp_path / "templates"
    contract_dir = template_dir / "hash1" / "contracts"
    contract_dir.mkdir(parents=True)
    schema = {"type": "object", "properties": {"total": {"type": "number"}}}
    (contract_dir / "contract.schema.json").write_text(
        json.dumps(schema), encoding="utf-8"
    )
    template = SimpleNamespace(
        contract_hash="hash1", digest="digest1", version=2
    )
    monkeypatch.setattr(server.templates, "template_dir", lambda: template_dir)
    monkeypatch.setattr(server.templates, "all_templates", lambda: [template])
    monkeypatch.setattr(
        server.templates, "score_template", lambda blocks, item: 0.9
    )

    match = server._match_template([], tmp_path / "ws")

    assert match is not None
    assert match["template"]["digest"] == "digest1"
    assert match["template"]["score"] == 0.9
    assert match["contract"] == schema


def test_match_template_below_threshold(tmp_path: Path, monkeypatch) -> None:
    template = SimpleNamespace(
        contract_hash="hash1", digest="digest1", version=1
    )
    monkeypatch.setattr(server.templates, "all_templates", lambda: [template])
    monkeypatch.setattr(
        server.templates, "score_template", lambda blocks, item: 0.5
    )

    assert server._match_template([], tmp_path / "ws") is None


def test_match_template_ambiguous(tmp_path: Path, monkeypatch) -> None:
    first = SimpleNamespace(contract_hash="h1", digest="d1", version=1)
    second = SimpleNamespace(contract_hash="h2", digest="d2", version=1)
    monkeypatch.setattr(server.templates, "all_templates", lambda: [first, second])
    monkeypatch.setattr(
        server.templates,
        "score_template",
        lambda blocks, item: 0.9 if item is first else 0.88,
    )

    assert server._match_template([], tmp_path / "ws") is None


def test_match_template_workspace_fallback(tmp_path: Path, monkeypatch) -> None:
    from vlm_ocr.workspace import create_workspace

    workspace = create_workspace(tmp_path / "ws", b"x", "doc.pdf")
    schema = {"type": "object", "properties": {"total": {"type": "number"}}}
    (workspace.root / "contracts" / "contract.schema.json").write_text(
        json.dumps(schema), encoding="utf-8"
    )
    contract_hash = server.templates.contract_hash(schema)
    template = SimpleNamespace(
        contract_hash=contract_hash, digest="digest1", version=1
    )
    monkeypatch.setattr(server.templates, "template_dir", lambda: tmp_path / "empty")
    monkeypatch.setattr(server.templates, "all_templates", lambda: [template])
    monkeypatch.setattr(
        server.templates, "score_template", lambda blocks, item: 0.95
    )

    match = server._match_template([], tmp_path / "ws")

    assert match is not None
    assert match["contract"] == schema
