from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from vlm_ocr import catalog, server
from vlm_ocr.errors import ContractError
from vlm_ocr.workspace import create_workspace

TOKEN = "secreto"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}


def _workspace(tmp_path: Path) -> tuple[Path, str]:
    base = tmp_path / "ws"
    workspace = create_workspace(base, b"%PDF-1.4\n", "doc.pdf")
    (workspace.root / "ocr.json").write_text(
        json.dumps(
            {
                "text": "Unidades Importe Devengado\nSALARIO BASE 2.406,89",
                "blocks": [
                    {"page": 0, "text": "Unidades", "box": [0.0, 0.0, 80.0, 20.0]},
                    {"page": 0, "text": "Importe", "box": [200.0, 0.0, 280.0, 20.0]},
                    {"page": 0, "text": "Devengado", "box": [400.0, 0.0, 480.0, 20.0]},
                    {"page": 0, "text": "SALARIO BASE", "box": [0.0, 40.0, 100.0, 60.0]},
                    {"page": 0, "text": "2.406,89", "box": [400.0, 40.0, 500.0, 60.0]},
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


def test_models_lists_only_local_models(tmp_path: Path, monkeypatch) -> None:
    entries = {
        "llama32-3b": catalog.ModelEntry(
            alias="llama32-3b",
            name="Llama 3.2 3B",
            kind="gguf",
            license="MIT",
            size_bytes=100,
            default=True,
        ),
        "qwen05b": catalog.ModelEntry(
            alias="qwen05b",
            name="Qwen 0.5B",
            kind="gguf",
            license="Apache-2.0",
            size_bytes=200,
        ),
        "cloud": catalog.ModelEntry(
            alias="cloud", name="Cloud", kind="ollama", license="remote"
        ),
        "nuextract-tiny": catalog.ModelEntry(
            alias="nuextract-tiny",
            name="NuExtract",
            kind="gguf",
            license="MIT",
            prompt_style="nuextract",
        ),
    }
    monkeypatch.setattr(server.catalog, "load_catalog", lambda: entries)
    monkeypatch.setattr(
        server.catalog,
        "find_downloaded",
        lambda entry: Path("/tmp/model.gguf") if entry.alias == "llama32-3b" else None,
    )
    client = _client(tmp_path)

    response = client.get("/api/models", headers=HEADERS)

    assert response.status_code == 200
    models = response.json()["models"]
    assert [model["alias"] for model in models] == ["llama32-3b", "qwen05b"]
    assert models[0]["present"] is True
    assert models[0]["default"] is True
    assert models[1]["present"] is False


def test_propose_maps_and_filters_labels(tmp_path: Path, monkeypatch) -> None:
    base, workspace_id = _workspace(tmp_path)
    monkeypatch.setattr(
        server, "_local_model", lambda alias: SimpleNamespace(label="llama32-3b")
    )
    captured: dict = {}

    def fake_infer(text, contract, kind, model, **kwargs):
        captured.update(
            text=text,
            contract=contract,
            kind=kind,
            model=model,
            instructions=kwargs.get("instructions"),
        )
        return {
            "fields": [
                {
                    "name": "Salario Base",
                    "type": "number",
                    "labels": ["SALARIO BASE", "INVENTADO"],
                    "source": "devengado",
                }
            ],
            "lists": [],
        }

    monkeypatch.setattr(server, "infer_contract", fake_infer)
    client = _client(base)

    response = client.post(
        f"/api/workspaces/{workspace_id}/propose",
        headers=HEADERS,
        json={
            "model": "llama32-3b",
            "instructions": "prioriza la tabla de artículos",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["model"] == "llama32-3b"
    assert payload["fields"] == [
        {
            "kind": "scalar",
            "name": "salario_base",
            "type": "number",
            "labels": ["SALARIO BASE"],
            "source": "devengado",
        }
    ]
    assert captured["contract"] is server.propose.PROPOSAL_SCHEMA
    assert captured["kind"] == "schema"
    assert "SALARIO BASE | 2.406,89" in captured["text"]
    assert server.propose.PROPOSAL_INSTRUCTIONS in captured["instructions"]
    assert "prioriza la tabla de artículos" in captured["instructions"]


def test_propose_rejects_remote_model(tmp_path: Path, monkeypatch) -> None:
    base, workspace_id = _workspace(tmp_path)

    def fail(alias):
        raise ContractError("solo se admiten modelos locales")

    monkeypatch.setattr(server, "_local_model", fail)
    client = _client(base)

    response = client.post(
        f"/api/workspaces/{workspace_id}/propose",
        headers=HEADERS,
        json={"model": "cloud-deepseek"},
    )

    assert response.status_code == 422
    assert "modelos locales" in response.json()["detail"]


def test_propose_reports_model_failure(tmp_path: Path, monkeypatch) -> None:
    base, workspace_id = _workspace(tmp_path)
    monkeypatch.setattr(
        server, "_local_model", lambda alias: SimpleNamespace(label="llama32-3b")
    )

    def explode(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(server, "infer_contract", explode)
    client = _client(base)

    response = client.post(
        f"/api/workspaces/{workspace_id}/propose",
        headers=HEADERS,
        json={"model": "llama32-3b"},
    )

    assert response.status_code == 502
    assert "boom" in response.json()["detail"]


def test_propose_missing_workspace(tmp_path: Path) -> None:
    client = _client(tmp_path)

    response = client.post(
        "/api/workspaces/no-existe/propose",
        headers=HEADERS,
        json={"model": "llama32-3b"},
    )

    assert response.status_code == 404


def test_propose_requires_token(tmp_path: Path) -> None:
    base, workspace_id = _workspace(tmp_path)
    client = _client(base)

    assert client.get("/api/models").status_code == 401
    assert (
        client.post(
            f"/api/workspaces/{workspace_id}/propose", json={"model": "llama32-3b"}
        ).status_code
        == 401
    )


def test_local_model_rejects_remote(monkeypatch) -> None:
    remote = catalog.ModelRef(
        catalog.ModelEntry(alias="cloud", name="Cloud", kind="ollama", license="x")
    )
    monkeypatch.setattr(server.catalog, "resolve", lambda alias: remote)

    with pytest.raises(ContractError):
        server._local_model("cloud")
