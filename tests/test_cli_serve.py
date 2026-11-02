from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from vlm_ocr import cli
from vlm_ocr.server import create_app


def test_serve_help_mentions_flags(capsys) -> None:
    with pytest.raises(SystemExit) as exc:
        cli.main(["serve", "--help"])

    assert exc.value.code == 0
    out = capsys.readouterr().out
    for flag in ("--host", "--port", "--no-open", "--workspace-dir"):
        assert flag in out


@pytest.mark.parametrize("host", ["0.0.0.0", "192.168.1.10", "example.com"])
def test_serve_rejects_non_loopback_host(host: str, capsys) -> None:
    code = cli.main(["serve", "--host", host, "--no-open"])

    assert code == 2
    assert "loopback" in capsys.readouterr().err


def test_health_is_public_and_api_requires_token(tmp_path: Path) -> None:
    app = create_app(workspace_dir=tmp_path, token="secreto")
    client = TestClient(app)

    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json()["ok"] is True

    assert client.get("/api/workspaces").status_code == 401
    authorized = client.get(
        "/api/workspaces", headers={"Authorization": "Bearer secreto"}
    )
    assert authorized.status_code == 200
    assert authorized.json() == {"workspaces": []}


def test_wrong_token_is_rejected(tmp_path: Path) -> None:
    app = create_app(workspace_dir=tmp_path, token="secreto")
    client = TestClient(app)

    response = client.get(
        "/api/workspaces", headers={"Authorization": "Bearer otro"}
    )

    assert response.status_code == 401


def test_clean_stderr_drops_rapidocr_info_and_keeps_actions() -> None:
    from vlm_ocr.server import _clean_stderr

    raw = (
        "\x1b[32m[INFO] 2026-11-02 22:03:37,527 [RapidOCR] base.py:23: "
        "Using engine_name: onnxruntime\x1b[0m\n"
        "aviso: cobertura baja: 0/2 campos anotados\n"
        "error: JSON Schema inválido: ['text', 'null'] is not valid\n"
    )

    cleaned = _clean_stderr(raw)

    assert "RapidOCR" not in cleaned
    assert "[INFO]" not in cleaned
    assert "aviso: cobertura baja" in cleaned
    assert "error: JSON Schema inválido" in cleaned
