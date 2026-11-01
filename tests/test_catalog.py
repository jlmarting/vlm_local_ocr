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


@pytest.fixture
def install(monkeypatch, tmp_path: Path):
    def _install(models: dict) -> None:
        pack = write_catalog(tmp_path / "pack.json", models)
        monkeypatch.setattr(catalog, "packaged_catalog_path", lambda: pack)
        monkeypatch.setattr(catalog, "user_catalog_path", lambda: tmp_path / "nada.json")

    return _install


@pytest.fixture
def models_dir(monkeypatch, tmp_path: Path) -> Path:
    directory = tmp_path / "models"
    directory.mkdir()
    monkeypatch.setattr(catalog, "search_dirs", lambda: [directory])
    return directory


def test_resolve_alias_returns_downloaded_path(install, models_dir: Path) -> None:
    install({"a": gguf()})
    (models_dir / "m.gguf").write_bytes(b"")

    ref = catalog.resolve("a")

    assert ref.label == "a"
    assert ref.path == models_dir / "m.gguf"
    assert ref.is_remote is False


def test_resolve_alias_not_downloaded_raises(install, models_dir: Path) -> None:
    install({"a": gguf()})

    with pytest.raises(catalog.CatalogError, match="models fetch a"):
        catalog.resolve("a")


def test_alias_wins_over_existing_file(install, models_dir, monkeypatch, tmp_path: Path) -> None:
    install({"m.gguf": gguf(file="otro.gguf")})
    (models_dir / "otro.gguf").write_bytes(b"")
    monkeypatch.chdir(tmp_path)
    (tmp_path / "m.gguf").write_bytes(b"")

    ref = catalog.resolve("m.gguf")

    assert ref.entry.name == "Modelo de prueba"


def test_resolve_gguf_path_is_ad_hoc(install, tmp_path: Path) -> None:
    install({})
    path = tmp_path / "x.gguf"
    path.write_bytes(b"")

    ref = catalog.resolve(str(path))

    assert ref.label == "x.gguf"
    assert ref.path == path
    assert ref.entry.prompt_style == "chat"


def test_resolve_unknown_lists_aliases(install) -> None:
    install({"a": gguf()})

    with pytest.raises(catalog.CatalogError) as excinfo:
        catalog.resolve("nope")

    message = str(excinfo.value)
    assert "alias desconocido" in message
    assert "a" in message


def test_by_profile_selects_local_model(install, models_dir: Path) -> None:
    install({"a": gguf(profile="balanced")})
    (models_dir / "m.gguf").write_bytes(b"")

    assert catalog.by_profile("balanced").label == "a"


def test_by_profile_ignores_remote(install) -> None:
    install({"r": ollama(profile="balanced")})

    with pytest.raises(catalog.CatalogError, match="perfil"):
        catalog.by_profile("balanced")


def test_by_profile_not_downloaded_raises(install, models_dir: Path) -> None:
    install({"a": gguf(profile="fast")})

    with pytest.raises(catalog.CatalogError, match="models fetch a"):
        catalog.by_profile("fast")


def test_default_ref_only_when_downloaded(install, models_dir: Path) -> None:
    install({"d": gguf(default=True)})

    assert catalog.default_ref() is None

    (models_dir / "m.gguf").write_bytes(b"")

    assert catalog.default_ref().label == "d"


def test_default_alias_ignores_download_state(install) -> None:
    install({"d": gguf(default=True)})

    assert catalog.default_alias() == "d"


PACKAGED = [
    "llama32-3b",
    "llama32-3b-cloud",
    "nuextract-tiny",
    "phi4mini",
    "qwen05b",
    "qwen25-3b",
]


def packaged_entries():
    return catalog.load_catalog(catalog.packaged_catalog_path())


def test_packaged_catalog_ships_in_the_package() -> None:
    from importlib import resources

    assert resources.files("vlm_ocr").joinpath("catalog.json").is_file()


def test_packaged_catalog_has_the_six_models() -> None:
    assert sorted(packaged_entries()) == PACKAGED


def test_packaged_sha256_are_well_formed() -> None:
    for entry in packaged_entries().values():
        if entry.kind == "gguf":
            assert entry.sha256 is not None
            assert len(entry.sha256) == 64
            int(entry.sha256, 16)


def test_packaged_files_and_profiles_are_unique() -> None:
    entries = packaged_entries().values()
    files = [entry.file for entry in entries if entry.file]
    assert len(files) == len(set(files))
    profiles = [entry.profile for entry in entries if entry.kind == "gguf" and entry.profile]
    assert len(profiles) == len(set(profiles))
    assert sum(1 for entry in entries if entry.default) == 1


def test_redistributable_models_have_a_license_text() -> None:
    root = Path(__file__).resolve().parents[1]
    for entry in packaged_entries().values():
        if not entry.redistributable:
            continue
        assert entry.license_file is not None
        license_path = root / entry.license_file
        assert license_path.is_file(), license_path
        assert license_path.stat().st_size > 0


def test_ref_for_path_matches_catalog_entry(install, models_dir: Path) -> None:
    install({"a": gguf()})
    path = models_dir / "m.gguf"
    path.write_bytes(b"")

    ref = catalog.ref_for_path(path)

    assert ref.label == "a"


def test_ref_for_path_falls_back_to_ad_hoc(install, tmp_path: Path) -> None:
    install({"a": gguf()})
    path = tmp_path / "otro.gguf"
    path.write_bytes(b"")

    assert catalog.ref_for_path(path).label == "otro.gguf"


class FakeResponse:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload
        self.headers = {"Content-Length": str(len(payload))}

    def read(self, size: int) -> bytes:
        chunk, self.payload = self.payload[:size], self.payload[size:]
        return chunk

    def __enter__(self):
        return self

    def __exit__(self, *args) -> bool:
        return False


def _entry_for(payload: bytes, **overrides) -> dict:
    import hashlib

    entry = gguf(sha256=hashlib.sha256(payload).hexdigest(), size_bytes=len(payload))
    entry.update(overrides)
    return entry


def test_fetch_downloads_and_verifies(install, tmp_path: Path, monkeypatch) -> None:
    payload = b"pesos"
    install({"a": _entry_for(payload)})
    calls = []

    def fake_urlopen(request, timeout=60):
        calls.append(request)
        return FakeResponse(payload)

    monkeypatch.setattr(catalog.urllib.request, "urlopen", fake_urlopen)
    messages: list[str] = []

    target = catalog.fetch("a", dest=tmp_path / "dest", progress=messages.append)

    assert target.read_bytes() == payload
    assert not (tmp_path / "dest" / "m.gguf.part").exists()
    assert calls and "descargando" in " ".join(messages)


def test_fetch_corrupt_removes_files(install, tmp_path: Path, monkeypatch) -> None:
    install({"a": _entry_for(b"pesos")})
    monkeypatch.setattr(
        catalog.urllib.request, "urlopen", lambda request, timeout=60: FakeResponse(b"otros")
    )
    dest = tmp_path / "dest"

    with pytest.raises(catalog.CatalogError, match="sha256"):
        catalog.fetch("a", dest=dest, progress=lambda message: None)

    assert not (dest / "m.gguf").exists()
    assert not (dest / "m.gguf.part").exists()


def test_fetch_requires_license_acceptance_before_network(
    install, tmp_path: Path, monkeypatch
) -> None:
    install({"a": gguf(acceptance_required=True, license_url="https://example.com/lic")})

    def boom(*args, **kwargs):
        raise AssertionError("no debe tocar la red")

    monkeypatch.setattr(catalog.urllib.request, "urlopen", boom)

    with pytest.raises(catalog.CatalogError, match="--accept-license"):
        catalog.fetch("a", dest=tmp_path / "dest", progress=lambda message: None)


def test_fetch_gated_requires_hf_token(install, tmp_path: Path, monkeypatch) -> None:
    install({"a": gguf(gated=True)})
    monkeypatch.delenv("HF_TOKEN", raising=False)

    with pytest.raises(catalog.CatalogError, match="HF_TOKEN"):
        catalog.fetch("a", dest=tmp_path / "dest", progress=lambda message: None)


def test_fetch_sends_token_header(install, tmp_path: Path, monkeypatch) -> None:
    payload = b"pesos"
    install({"a": _entry_for(payload, gated=True)})
    seen: list[dict] = []

    def fake_urlopen(request, timeout=60):
        seen.append(request.headers)
        return FakeResponse(payload)

    monkeypatch.setattr(catalog.urllib.request, "urlopen", fake_urlopen)

    catalog.fetch("a", dest=tmp_path / "dest", token="secreto", progress=lambda m: None)

    assert seen[0].get("Authorization") == "Bearer secreto"


def test_fetch_skips_download_when_valid(install, tmp_path: Path, monkeypatch) -> None:
    payload = b"pesos"
    install({"a": _entry_for(payload)})
    dest = tmp_path / "dest"
    dest.mkdir()
    (dest / "m.gguf").write_bytes(payload)

    def boom(*args, **kwargs):
        raise AssertionError("no debe descargar de nuevo")

    monkeypatch.setattr(catalog.urllib.request, "urlopen", boom)

    assert catalog.fetch("a", dest=dest, progress=lambda m: None) == dest / "m.gguf"


def test_release_helpers_skip_non_redistributable() -> None:
    files = catalog.redistributable_files()

    assert "qwen2.5-3b-instruct-q4_k_m.gguf" not in files
    assert {
        "NuExtract-1.5-tiny.Q4_K_M.gguf",
        "Phi-4-mini-instruct-Q4_K_M.gguf",
        "Llama-3.2-3B-Instruct-Q4_K_M.gguf",
        "qwen2.5-0.5b-instruct-q4_k_m.gguf",
    } <= set(files)


def test_release_license_files_exist() -> None:
    root = Path(__file__).resolve().parents[1]

    licenses = catalog.license_files()

    assert licenses
    for relative in licenses:
        assert (root / relative).is_file(), relative
