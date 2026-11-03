from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

from vlm_ocr import server
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
                "text": "TOTAL 8.40\n1 Hamburger 3.60",
                "blocks": [],
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


def test_prompt_returns_model_answer(tmp_path: Path, monkeypatch) -> None:
    base, workspace_id = _workspace(tmp_path)
    monkeypatch.setattr(
        server, "_model_ref", lambda alias: SimpleNamespace(label="llama32-3b", is_remote=False)
    )
    captured: dict = {}

    def fake_llm(command, stdin_text, job_id, metrics_path):
        captured.update(command=command, stdin=stdin_text, job_id=job_id)
        return (
            0,
            json.dumps({"text": "TOTAL 8.40", "answer": "El total es 8.40"}),
            "",
            {"time_ms": 7.5},
        )

    monkeypatch.setattr(server, "_run_llm_cli", fake_llm)
    client = _client(base)

    response = client.post(
        f"/api/workspaces/{workspace_id}/prompt",
        headers=HEADERS,
        json={"prompt": "¿Cuánto es el total?", "model": "llama32-3b"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["answer"] == "El total es 8.40"
    assert payload["model"] == "llama32-3b"
    assert payload["remote"] is False
    assert payload["usage"]["time_ms"] == 7.5
    assert "--prompt" in captured["command"]
    assert "¿Cuánto es el total?" in captured["command"]
    assert "TOTAL 8.40" in captured["stdin"]


def test_prompt_requires_text(tmp_path: Path, monkeypatch) -> None:
    base, workspace_id = _workspace(tmp_path)
    client = _client(base)

    response = client.post(
        f"/api/workspaces/{workspace_id}/prompt",
        headers=HEADERS,
        json={"prompt": "", "model": "llama32-3b"},
    )

    assert response.status_code == 422
    assert "prompt" in response.json()["detail"]


def test_prompt_rejects_too_long(tmp_path: Path) -> None:
    base, workspace_id = _workspace(tmp_path)
    client = _client(base)

    response = client.post(
        f"/api/workspaces/{workspace_id}/prompt",
        headers=HEADERS,
        json={"prompt": "x" * 4001, "model": "llama32-3b"},
    )

    assert response.status_code == 422
    assert "4000" in response.json()["detail"]


def test_prompt_rejects_remote_model(tmp_path: Path, monkeypatch) -> None:
    base, workspace_id = _workspace(tmp_path)

    def fail(alias):
        raise ContractError("el modelo cloud requiere OLLAMA_API_KEY en el entorno")

    monkeypatch.setattr(server, "_model_ref", fail)
    client = _client(base)

    response = client.post(
        f"/api/workspaces/{workspace_id}/prompt",
        headers=HEADERS,
        json={"prompt": "hola", "model": "cloud"},
    )

    assert response.status_code == 422
    assert "OLLAMA_API_KEY" in response.json()["detail"]


def test_prompt_reports_model_failure(tmp_path: Path, monkeypatch) -> None:
    base, workspace_id = _workspace(tmp_path)
    monkeypatch.setattr(
        server, "_model_ref", lambda alias: SimpleNamespace(label="llama32-3b", is_remote=False)
    )

    monkeypatch.setattr(
        server,
        "_run_llm_cli",
        lambda command, stdin_text, job_id, metrics_path: (1, "", "boom", {}),
    )
    client = _client(base)

    response = client.post(
        f"/api/workspaces/{workspace_id}/prompt",
        headers=HEADERS,
        json={"prompt": "hola", "model": "llama32-3b"},
    )

    assert response.status_code == 422
    assert "boom" in response.json()["detail"]


def test_prompt_requires_token(tmp_path: Path) -> None:
    base, workspace_id = _workspace(tmp_path)
    client = _client(base)

    response = client.post(
        f"/api/workspaces/{workspace_id}/prompt",
        json={"prompt": "hola", "model": "llama32-3b"},
    )

    assert response.status_code == 401
