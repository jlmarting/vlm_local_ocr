from __future__ import annotations

import asyncio
import json
import secrets
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from . import __version__, paths, serve_layout
from . import workspace as workspace_mod
from .errors import InputError

WEB_DIR = Path(__file__).parent / "web"
LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}
MAX_UPLOAD_BYTES = 50 * 1024 * 1024


def is_loopback(host: str) -> bool:
    return host in LOOPBACK_HOSTS


def _document_path(workspace: workspace_mod.Workspace) -> Path:
    suffix = workspace.meta["document"]["format"]
    return workspace.root / f"document.{suffix}"


def _run_cli(document: Path, extra: list[str]) -> tuple[int, dict | None, str]:
    command = [sys.executable, "-m", "vlm_ocr", str(document), *extra]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        return result.returncode, None, result.stderr.strip()
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return 1, None, "el CLI no devolvió JSON"
    return 0, payload if isinstance(payload, dict) else None, result.stderr.strip()


def _process_document(
    base: Path, workspace: workspace_mod.Workspace
) -> dict:
    document = _document_path(workspace)
    dpi = int(workspace.meta.get("dpi", 200))
    processed = serve_layout.process_document(
        document, dpi, workspace.root / "pages"
    )
    code, payload, stderr = _run_cli(
        document, ["--format", "json", "--with-layout"]
    )
    if code != 0 or payload is None:
        raise InputError(stderr or "el CLI no pudo procesar el documento")

    blocks = serve_layout.normalize_blocks(
        payload.get("layout", []), processed["native_pages"], dpi
    )
    text = payload.get("text", "")
    ocr = {
        "text": text,
        "blocks": blocks,
        "native_pages": sorted(processed["native_pages"]),
        "dpi": dpi,
    }
    (workspace.root / "ocr.json").write_text(
        json.dumps(ocr, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    meta = workspace_mod.update_workspace(
        workspace,
        base,
        document={**workspace.meta["document"], "pages": len(processed["pages"])},
    )
    return {
        "workspace": meta.meta,
        "document": {
            "filename": workspace.meta["document"]["filename"],
            "format": workspace.meta["document"]["format"],
            "pages": [
                {
                    "index": page["index"],
                    "width": page["width"],
                    "height": page["height"],
                    "image_url": (
                        f"/api/workspaces/{workspace.id}/pages/{page['index']}.png"
                    ),
                }
                for page in processed["pages"]
            ],
            "blocks": blocks,
            "text": text,
        },
    }


def _read_ocr(workspace: workspace_mod.Workspace) -> dict:
    path = workspace.root / "ocr.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise InputError("el workspace no tiene texto extraído") from exc
    if not isinstance(data, dict):
        raise InputError("el workspace no tiene texto extraído")
    return data


def create_app(workspace_dir: Path, token: str) -> FastAPI:
    app = FastAPI(title="vlm-local-ocr", version=__version__)
    app.state.workspace_dir = Path(workspace_dir)
    app.state.token = token

    @app.middleware("http")
    async def require_token(request: Request, call_next):
        path = request.url.path
        if path.startswith("/api/") and path != "/api/health":
            header = request.headers.get("authorization", "")
            supplied = header.removeprefix("Bearer ").strip()
            if not supplied or not secrets.compare_digest(supplied, token):
                return JSONResponse({"error": "unauthorized"}, status_code=401)
        return await call_next(request)

    @app.get("/api/health")
    def health() -> dict:
        return {"ok": True, "version": __version__}

    @app.get("/api/workspaces")
    def list_workspaces() -> dict:
        return {"workspaces": workspace_mod.list_workspaces(app.state.workspace_dir)}

    @app.post("/api/workspaces", status_code=201)
    async def create_workspace_endpoint(
        file: Annotated[UploadFile, File()],
        name: Annotated[str | None, Form()] = None,
    ) -> JSONResponse:
        upload = await file.read()
        if not upload:
            return JSONResponse(
                {"error": "input", "detail": "el documento está vacío"},
                status_code=422,
            )
        if len(upload) > MAX_UPLOAD_BYTES:
            return JSONResponse(
                {
                    "error": "input",
                    "detail": "el documento supera el máximo de 50 MB",
                },
                status_code=413,
            )
        try:
            workspace = workspace_mod.create_workspace(
                app.state.workspace_dir,
                upload,
                file.filename or "document",
                name or None,
            )
            result = await asyncio.to_thread(
                _process_document, app.state.workspace_dir, workspace
            )
        except InputError as exc:
            return JSONResponse(
                {"error": "input", "detail": str(exc)}, status_code=422
            )
        return JSONResponse(result, status_code=201)

    @app.get("/api/workspaces/{workspace_id}")
    def get_workspace(workspace_id: str) -> JSONResponse:
        try:
            workspace = workspace_mod.get_workspace(
                app.state.workspace_dir, workspace_id
            )
        except InputError as exc:
            return JSONResponse(
                {"error": "not_found", "detail": str(exc)}, status_code=404
            )
        return JSONResponse({"workspace": workspace.meta})

    @app.delete("/api/workspaces/{workspace_id}", status_code=204)
    def delete_workspace(workspace_id: str) -> Response:
        try:
            workspace_mod.delete_workspace(
                app.state.workspace_dir, workspace_id
            )
        except InputError as exc:
            return JSONResponse(
                {"error": "not_found", "detail": str(exc)}, status_code=404
            )
        return Response(status_code=204)

    @app.get("/api/workspaces/{workspace_id}/pages/{page}.png")
    def get_page(workspace_id: str, page: int) -> Response:
        try:
            workspace = workspace_mod.get_workspace(
                app.state.workspace_dir, workspace_id
            )
        except InputError as exc:
            return JSONResponse(
                {"error": "not_found", "detail": str(exc)}, status_code=404
            )
        path = workspace.root / "pages" / f"page-{page:03d}.png"
        if not path.exists():
            return JSONResponse(
                {"error": "not_found", "detail": "página no encontrada"},
                status_code=404,
            )
        return FileResponse(path, media_type="image/png")

    @app.get("/api/workspaces/{workspace_id}/text")
    def get_text(workspace_id: str) -> JSONResponse:
        try:
            workspace = workspace_mod.get_workspace(
                app.state.workspace_dir, workspace_id
            )
            ocr = _read_ocr(workspace)
        except InputError as exc:
            return JSONResponse(
                {"error": "not_found", "detail": str(exc)}, status_code=404
            )
        return JSONResponse({"text": ocr["text"], "blocks": ocr["blocks"]})

    if WEB_DIR.exists():
        app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
    return app


def run(
    host: str,
    port: int,
    *,
    open_browser: bool = True,
    workspace_dir: Path | None = None,
) -> int:
    import uvicorn

    if not is_loopback(host):
        print(
            "error: --host solo admite loopback (127.0.0.1, ::1, localhost)",
            file=sys.stderr,
        )
        return 2

    token = secrets.token_urlsafe(32)
    root = (
        Path(workspace_dir)
        if workspace_dir is not None
        else paths.data_dir() / "workspaces"
    )
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        print(f"error: no se pudo crear el workspace: {exc}", file=sys.stderr)
        return 1

    app = create_app(root, token)
    config = uvicorn.Config(
        app, host=host, port=port, log_level="warning", access_log=False
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    while not server.started and thread.is_alive():
        time.sleep(0.02)
    if not server.started:
        print(
            "error: no se pudo arrancar el servidor (¿puerto ocupado?)",
            file=sys.stderr,
        )
        return 1

    sockets = server.servers[0].sockets if server.servers else []
    actual_port = sockets[0].getsockname()[1] if sockets else port
    url_host = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
    url = f"http://{url_host}:{actual_port}/#token={token}"
    print(url, flush=True)
    print(f"workspace: {root}", file=sys.stderr)
    if open_browser:
        webbrowser.open(url)
    try:
        thread.join()
    except KeyboardInterrupt:
        server.should_exit = True
        thread.join()
    return 0
