from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from vlm_ocr import catalog

MODEL = b"modelo"
MMPROJ = b"proyector"


def gguf(**overrides) -> dict:
    entry = {
        "name": "Modelo de prueba",
        "kind": "gguf",
        "file": "m.gguf",
        "url": "https://example.com/m.gguf",
        "sha256": hashlib.sha256(MODEL).hexdigest(),
        "size_bytes": len(MODEL),
        "license": "MIT",
    }
    entry.update(overrides)
    return entry


def vision(**overrides) -> dict:
    entry = gguf(
        vision=True,
        mmproj_file="mm.gguf",
        mmproj_url="https://example.com/mm.gguf",
        mmproj_sha256=hashlib.sha256(MMPROJ).hexdigest(),
        mmproj_size_bytes=len(MMPROJ),
    )
    entry.update(overrides)
    return entry


@pytest.fixture
def install(monkeypatch, tmp_path: Path):
    def _install(models: dict) -> None:
        pack = tmp_path / "pack.json"
        pack.write_text(json.dumps({"version": 1, "models": models}), encoding="utf-8")
        monkeypatch.setattr(catalog, "packaged_catalog_path", lambda: pack)
        monkeypatch.setattr(catalog, "user_catalog_path", lambda: tmp_path / "nada.json")

    return _install


def fake_urlopen(monkeypatch, contents: dict[str, bytes]) -> None:
    class FakeResponse:
        def __init__(self, payload: bytes) -> None:
            self.payload = payload
            self.headers = {"Content-Length": str(len(payload))}

        def read(self, size):
            chunk, self.payload = self.payload[:size], self.payload[size:]
            return chunk

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def _urlopen(request, timeout=60):
        return FakeResponse(contents[str(request.full_url)])

    monkeypatch.setattr(catalog.urllib.request, "urlopen", _urlopen)


def test_fetch_vision_downloads_model_and_mmproj(
    tmp_path: Path, monkeypatch, install
) -> None:
    install({"v": vision()})
    fake_urlopen(
        monkeypatch,
        {"https://example.com/m.gguf": MODEL, "https://example.com/mm.gguf": MMPROJ},
    )

    path = catalog.fetch("v", dest=tmp_path / "dest")

    assert path == tmp_path / "dest" / "m.gguf"
    assert (tmp_path / "dest" / "mm.gguf").read_bytes() == MMPROJ


def test_fetch_vision_bad_mmproj_hash_leaves_no_model(
    tmp_path: Path, monkeypatch, install
) -> None:
    install({"v": vision()})
    fake_urlopen(
        monkeypatch,
        {"https://example.com/m.gguf": MODEL, "https://example.com/mm.gguf": b"corrupto"},
    )

    with pytest.raises(catalog.CatalogError, match="sha256"):
        catalog.fetch("v", dest=tmp_path / "dest")

    assert not (tmp_path / "dest" / "mm.gguf").exists()
    assert not (tmp_path / "dest" / "m.gguf").exists()
