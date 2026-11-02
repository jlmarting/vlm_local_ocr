from __future__ import annotations

import secrets
import sys
import threading
import time
import webbrowser
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from . import __version__, paths

WEB_DIR = Path(__file__).parent / "web"
LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}


def is_loopback(host: str) -> bool:
    return host in LOOPBACK_HOSTS


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
        return {"workspaces": []}

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
