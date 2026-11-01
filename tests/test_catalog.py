from __future__ import annotations

import json
from pathlib import Path

import pytest

from vlm_ocr import catalog


def write_catalog(path: Path, models: dict, version: int = 1) -> Path:
    path.write_text(json.dumps({"version": version, "models": models}), encoding="utf-8")
    return path


def gguf(**overrides) -> dict:
    entry = {
        "name": "Modelo de prueba",
        "kind": "gguf",
        "file": "m.gguf",
        "url": "https://example.com/m.gguf",
        "sha256": "a" * 64,
        "size_bytes": 10,
        "license": "MIT",
    }
    entry.update(overrides)
    return entry


def ollama(**overrides) -> dict:
    entry = {
        "name": "Modelo remoto",
        "kind": "ollama",
        "license": "MIT",
        "model": "m:1b",
        "base_url": "https://ollama.com",
        "requires_key": True,
        "api_key_env": "OLLAMA_API_KEY",
    }
    entry.update(overrides)
    return entry


def test_load_catalog_from_explicit_path(tmp_path: Path) -> None:
    path = write_catalog(tmp_path / "catalog.json", {"a": gguf(), "b": ollama()})

    entries = catalog.load_catalog(path)

    assert sorted(entries) == ["a", "b"]
    assert entries["a"].kind == "gguf"
    assert entries["a"].prompt_style == "chat"
    assert entries["b"].kind == "ollama"
    assert entries["b"].requires_key is True


def test_overlay_wins_per_alias(tmp_path: Path, monkeypatch) -> None:
    pack = write_catalog(tmp_path / "pack.json", {"a": gguf(name="base")})
    overlay = write_catalog(tmp_path / "user.json", {"a": gguf(name="propio")})
    monkeypatch.setattr(catalog, "packaged_catalog_path", lambda: pack)
    monkeypatch.setattr(catalog, "user_catalog_path", lambda: overlay)

    entries = catalog.load_catalog()

    assert entries["a"].name == "propio"


def test_overlay_adds_aliases(tmp_path: Path, monkeypatch) -> None:
    pack = write_catalog(tmp_path / "pack.json", {"a": gguf()})
    overlay = write_catalog(tmp_path / "user.json", {"mio": gguf(file="mio.gguf")})
    monkeypatch.setattr(catalog, "packaged_catalog_path", lambda: pack)
    monkeypatch.setattr(catalog, "user_catalog_path", lambda: overlay)

    assert "mio" in catalog.load_catalog()


def test_unsupported_version_raises(tmp_path: Path) -> None:
    path = write_catalog(tmp_path / "catalog.json", {"a": gguf()}, version=2)

    with pytest.raises(catalog.CatalogError, match="versión"):
        catalog.load_catalog(path)


def test_gguf_without_sha256_raises(tmp_path: Path) -> None:
    entry = gguf()
    del entry["sha256"]
    path = write_catalog(tmp_path / "catalog.json", {"a": entry})

    with pytest.raises(catalog.CatalogError, match="sha256"):
        catalog.load_catalog(path)


def test_gguf_with_bad_sha256_raises(tmp_path: Path) -> None:
    path = write_catalog(tmp_path / "catalog.json", {"a": gguf(sha256="xyz")})

    with pytest.raises(catalog.CatalogError, match="sha256"):
        catalog.load_catalog(path)


def test_ollama_without_model_raises(tmp_path: Path) -> None:
    entry = ollama()
    del entry["model"]
    path = write_catalog(tmp_path / "catalog.json", {"a": entry})

    with pytest.raises(catalog.CatalogError, match="model"):
        catalog.load_catalog(path)


def test_ollama_without_key_env_raises(tmp_path: Path) -> None:
    entry = ollama()
    del entry["api_key_env"]
    path = write_catalog(tmp_path / "catalog.json", {"a": entry})

    with pytest.raises(catalog.CatalogError, match="api_key_env"):
        catalog.load_catalog(path)


def test_unknown_kind_raises(tmp_path: Path) -> None:
    path = write_catalog(tmp_path / "catalog.json", {"a": gguf(kind="magic")})

    with pytest.raises(catalog.CatalogError, match="tipo"):
        catalog.load_catalog(path)


def test_missing_catalog_raises(tmp_path: Path) -> None:
    with pytest.raises(catalog.CatalogError, match="no existe"):
        catalog.load_catalog(tmp_path / "nada.json")
