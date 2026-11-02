from __future__ import annotations

import json
from pathlib import Path

import pytest

from vlm_ocr.errors import InputError
from vlm_ocr.workspace import (
    create_workspace,
    delete_workspace,
    get_workspace,
    list_workspaces,
    update_workspace,
)


def test_create_workspace_writes_files_and_index(tmp_path: Path) -> None:
    workspace = create_workspace(
        tmp_path, b"documento", "factura.pdf", name="Factura de enero"
    )

    assert workspace.id in workspace.root.name
    assert (workspace.root / "document.pdf").read_bytes() == b"documento"
    assert (workspace.root / "pages").is_dir()
    assert (workspace.root / "contracts").is_dir()
    assert (workspace.root / "results").is_dir()
    meta = json.loads((workspace.root / "workspace.json").read_text(encoding="utf-8"))
    assert meta["name"] == "Factura de enero"
    assert meta["document"]["filename"] == "factura.pdf"

    index = json.loads((tmp_path / "index.json").read_text(encoding="utf-8"))
    assert index["workspaces"][0]["id"] == workspace.id


def test_list_workspaces_is_newest_first(tmp_path: Path) -> None:
    first = create_workspace(tmp_path, b"a", "a.pdf")
    second = create_workspace(tmp_path, b"b", "b.png")

    rows = list_workspaces(tmp_path)

    assert [row["id"] for row in rows] == [second.id, first.id]


def test_get_and_update_workspace(tmp_path: Path) -> None:
    workspace = create_workspace(tmp_path, b"a", "a.pdf")

    loaded = get_workspace(tmp_path, workspace.id)
    assert loaded.meta["id"] == workspace.id

    updated = update_workspace(
        loaded, tmp_path, document={**loaded.meta["document"], "pages": 3}
    )
    assert updated.meta["document"]["pages"] == 3
    rows = list_workspaces(tmp_path)
    assert rows[0]["updated_at"] == updated.meta["updated_at"]


def test_delete_workspace_removes_folder_and_index_row(tmp_path: Path) -> None:
    workspace = create_workspace(tmp_path, b"a", "a.pdf")

    delete_workspace(tmp_path, workspace.id)

    assert not workspace.root.exists()
    assert list_workspaces(tmp_path) == []


def test_delete_unknown_workspace_raises(tmp_path: Path) -> None:
    with pytest.raises(InputError):
        delete_workspace(tmp_path, "no-existe")


def test_create_workspace_rejects_unknown_extension(tmp_path: Path) -> None:
    with pytest.raises(InputError):
        create_workspace(tmp_path, b"a", "a.exe")


def test_create_workspace_rejects_empty_document(tmp_path: Path) -> None:
    with pytest.raises(InputError):
        create_workspace(tmp_path, b"", "a.pdf")
