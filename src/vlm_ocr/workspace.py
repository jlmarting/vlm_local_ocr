from __future__ import annotations

import json
import re
import shutil
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .errors import InputError

ALLOWED_EXTENSIONS = {
    ".pdf",
    ".png",
    ".jpg",
    ".jpeg",
    ".tif",
    ".tiff",
    ".bmp",
    ".webp",
    ".txt",
}
WORKSPACE_ID = re.compile(r"^[0-9a-f]{12}$")


def _now() -> str:
    return (
        datetime.now(UTC)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


@dataclass(frozen=True)
class Workspace:
    id: str
    root: Path
    meta: dict[str, Any]


def _index_path(base: Path) -> Path:
    return base / "index.json"


def _read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _index_read(base: Path) -> dict[str, Any]:
    data = _read_json(_index_path(base), {"workspaces": []})
    if not isinstance(data, dict) or not isinstance(data.get("workspaces"), list):
        return {"workspaces": []}
    return data


def _summary(meta: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": meta["id"],
        "name": meta.get("name") or meta["document"]["filename"],
        "updated_at": meta["updated_at"],
        "document": {
            "filename": meta["document"]["filename"],
            "format": meta["document"]["format"],
        },
    }


def _touch_index(base: Path, meta: dict[str, Any]) -> None:
    index = _index_read(base)
    index["workspaces"] = [
        row for row in index["workspaces"] if row.get("id") != meta["id"]
    ]
    index["workspaces"].insert(0, _summary(meta))
    _write_json(_index_path(base), index)


def _valid_id(workspace_id: str) -> str:
    if not WORKSPACE_ID.fullmatch(workspace_id):
        raise InputError(f"workspace no válido: {workspace_id!r}")
    return workspace_id


def create_workspace(
    base: Path,
    upload: bytes,
    filename: str,
    name: str | None = None,
    dpi: int = 200,
) -> Workspace:
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise InputError(f"formato no soportado: {suffix or '(sin extensión)'}")
    if not upload:
        raise InputError("el documento está vacío")
    base = Path(base)
    try:
        base.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise InputError(f"no se pudo crear el workspace: {exc}") from exc

    workspace_id = uuid.uuid4().hex[:12]
    root = base / workspace_id
    try:
        (root / "pages").mkdir(parents=True)
        (root / "contracts").mkdir()
        (root / "results").mkdir()
        document = root / f"document{suffix}"
        document.write_bytes(upload)
    except OSError as exc:
        shutil.rmtree(root, ignore_errors=True)
        raise InputError(f"no se pudo guardar el documento: {exc}") from exc

    now = _now()
    meta: dict[str, Any] = {
        "id": workspace_id,
        "name": name or Path(filename).stem,
        "created_at": now,
        "updated_at": now,
        "dpi": dpi,
        "document": {
            "filename": filename,
            "format": suffix.lstrip("."),
            "size_bytes": len(upload),
            "pages": 0,
        },
        "contract": None,
        "last_result": None,
    }
    _write_json(root / "workspace.json", meta)
    _touch_index(base, meta)
    return Workspace(workspace_id, root, meta)


def list_workspaces(base: Path) -> list[dict[str, Any]]:
    base = Path(base)
    rows = [
        row
        for row in _index_read(base)["workspaces"]
        if isinstance(row, dict)
        and isinstance(row.get("id"), str)
        and (base / row["id"] / "workspace.json").exists()
    ]
    rows.sort(key=lambda row: row.get("updated_at", ""), reverse=True)
    return rows


def get_workspace(base: Path, workspace_id: str) -> Workspace:
    workspace_id = _valid_id(workspace_id)
    root = Path(base) / workspace_id
    meta = _read_json(root / "workspace.json")
    if not isinstance(meta, dict):
        raise InputError(f"no existe el workspace: {workspace_id}")
    return Workspace(workspace_id, root, meta)


def update_workspace(
    workspace: Workspace, base: Path, **changes: Any
) -> Workspace:
    meta = dict(workspace.meta)
    meta.update(changes)
    meta["updated_at"] = _now()
    _write_json(workspace.root / "workspace.json", meta)
    _touch_index(Path(base), meta)
    return Workspace(workspace.id, workspace.root, meta)


def delete_workspace(base: Path, workspace_id: str) -> None:
    workspace_id = _valid_id(workspace_id)
    root = Path(base) / workspace_id
    if not root.exists():
        raise InputError(f"no existe el workspace: {workspace_id}")
    try:
        shutil.rmtree(root)
    except OSError as exc:
        raise InputError(f"no se pudo borrar el workspace: {exc}") from exc
    index = _index_read(Path(base))
    index["workspaces"] = [
        row for row in index["workspaces"] if row.get("id") != workspace_id
    ]
    _write_json(_index_path(Path(base)), index)
