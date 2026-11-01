from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, fields
from importlib import resources
from pathlib import Path
from typing import Any

CATALOG_VERSION = 1
PROMPT_STYLES = ("chat", "nuextract")
KINDS = ("gguf", "ollama")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class CatalogError(Exception):
    """Catálogo inválido, alias desconocido o modelo no disponible."""


@dataclass(frozen=True)
class ModelEntry:
    alias: str
    name: str
    kind: str
    license: str
    params: str | None = None
    file: str | None = None
    url: str | None = None
    sha256: str | None = None
    size_bytes: int | None = None
    context: int | None = None
    license_url: str | None = None
    license_file: str | None = None
    redistributable: bool = False
    acceptance_required: bool = False
    gated: bool = False
    profile: str | None = None
    prompt_style: str = "chat"
    prompt_hints: str | None = None
    model: str | None = None
    base_url: str | None = None
    api_key_env: str | None = None
    requires_key: bool = False
    default: bool = False


def packaged_catalog_path() -> Path:
    """Ruta del catálogo que viaja dentro del paquete."""
    return Path(str(resources.files("vlm_ocr").joinpath("catalog.json")))


def user_catalog_path() -> Path:
    """Catálogo de usuario: añade o pisa alias sin tocar el paquete."""
    return Path.home() / ".config" / "vlm-local-ocr" / "catalog.json"


def load_catalog(path: Path | str | None = None) -> dict[str, ModelEntry]:
    """Carga y valida el catálogo; con overlay de usuario cuando no se da ruta."""
    explicit = path is not None
    source = Path(path) if explicit else packaged_catalog_path()
    raw = _read_json(source, "catálogo")
    _check_version(raw, source)

    models = raw.get("models")
    if not isinstance(models, dict):
        raise CatalogError(f"el catálogo no tiene un objeto 'models': {source}")

    if not explicit:
        overlay = user_catalog_path()
        if overlay.is_file():
            extra = _read_json(overlay, "catálogo de usuario")
            _check_version(extra, overlay)
            extra_models = extra.get("models")
            if not isinstance(extra_models, dict):
                raise CatalogError(f"el catálogo de usuario no tiene 'models': {overlay}")
            models = {**models, **extra_models}

    return {str(alias): build_entry(str(alias), data) for alias, data in models.items()}


def build_entry(alias: str, data: Any) -> ModelEntry:
    """Convierte un diccionario del catálogo en ``ModelEntry`` validada."""
    if not isinstance(data, dict):
        raise CatalogError(f"{alias}: la entrada debe ser un objeto JSON")
    for key in ("name", "kind", "license"):
        if not _text(data.get(key)):
            raise CatalogError(f"{alias}: falta '{key}'")

    kind = str(data["kind"])
    if kind not in KINDS:
        raise CatalogError(f"{alias}: tipo desconocido {kind!r} (usa {' o '.join(KINDS)})")

    prompt_style = str(data.get("prompt_style") or "chat")
    if prompt_style not in PROMPT_STYLES:
        raise CatalogError(f"{alias}: prompt_style desconocido {prompt_style!r}")

    if kind == "gguf":
        for key in ("file", "url", "sha256"):
            if not _text(data.get(key)):
                raise CatalogError(f"{alias}: un modelo gguf requiere '{key}'")
        sha = str(data["sha256"])
        if not _SHA256_RE.match(sha):
            raise CatalogError(f"{alias}: sha256 inválido (64 hex): {sha!r}")
        size = data.get("size_bytes")
        if not isinstance(size, int) or isinstance(size, bool) or size <= 0:
            raise CatalogError(f"{alias}: size_bytes debe ser un entero positivo")
    else:
        for key in ("model", "base_url"):
            if not _text(data.get(key)):
                raise CatalogError(f"{alias}: un modelo ollama requiere '{key}'")
        if bool(data.get("requires_key")) and not _text(data.get("api_key_env")):
            raise CatalogError(f"{alias}: requires_key exige 'api_key_env'")

    values: dict[str, Any] = {"alias": alias}
    for field in fields(ModelEntry):
        if field.name == "alias" or field.name in values:
            continue
        if field.name in data:
            values[field.name] = data[field.name]
    values["name"] = str(data["name"])
    values["kind"] = kind
    values["license"] = str(data["license"])
    values["prompt_style"] = prompt_style
    values["redistributable"] = bool(data.get("redistributable", False))
    values["acceptance_required"] = bool(data.get("acceptance_required", False))
    values["gated"] = bool(data.get("gated", False))
    values["requires_key"] = bool(data.get("requires_key", False))
    values["default"] = bool(data.get("default", False))
    return ModelEntry(**_coerce(values))


def _coerce(values: dict[str, Any]) -> dict[str, Any]:
    """Recorta textos opcionales y normaliza tipos declarados del catálogo."""
    out = dict(values)
    for key in (
        "params",
        "file",
        "url",
        "sha256",
        "context",
        "license_url",
        "license_file",
        "profile",
        "prompt_hints",
        "model",
        "base_url",
        "api_key_env",
        "size_bytes",
    ):
        if key in out and out[key] is None:
            out.pop(key)
    return out


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _check_version(raw: Any, source: Path) -> None:
    if not isinstance(raw, dict):
        raise CatalogError(f"el catálogo debe ser un objeto JSON: {source}")
    version = raw.get("version")
    if version != CATALOG_VERSION:
        raise CatalogError(
            f"versión de catálogo no soportada: {version!r} (se espera {CATALOG_VERSION})"
        )


def _read_json(path: Path, label: str) -> Any:
    if not path.is_file():
        raise CatalogError(f"no existe el {label}: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except UnicodeDecodeError as exc:
        raise CatalogError(f"el {label} no es UTF-8 válido: {path}") from exc
    except json.JSONDecodeError as exc:
        raise CatalogError(f"{label} JSON inválido en {path} (línea {exc.lineno}): {exc.msg}") from exc
    except OSError as exc:
        raise CatalogError(f"no se pudo leer el {label} {path}: {exc}") from exc


@dataclass(frozen=True)
class ModelRef:
    """Modelo resuelto: entrada del catálogo y, si es local, su fichero."""

    entry: ModelEntry
    path: Path | None = None

    @property
    def label(self) -> str:
        return self.entry.alias

    @property
    def is_remote(self) -> bool:
        return self.entry.kind != "gguf"


def search_dirs() -> list[Path]:
    """Dónde se buscan los GGUF: repo, directorio actual y datos del usuario."""
    repo_models = Path(__file__).resolve().parents[2] / "models"
    return [
        repo_models,
        Path.cwd() / "models",
        Path.home() / ".local" / "share" / "vlm-local-ocr" / "models",
    ]


def sha256_file(path: Path | str) -> str:
    """sha256 de un fichero, por bloques de 1 MiB."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_file(entry: ModelEntry, path: Path | str) -> bool:
    """¿El fichero coincide con el sha256 del catálogo?"""
    if not entry.sha256:
        return False
    return sha256_file(path) == entry.sha256


def find_downloaded(entry: ModelEntry) -> Path | None:
    """Primer fichero del modelo que aparezca en los directorios de búsqueda."""
    if entry.kind != "gguf" or not entry.file:
        return None
    for directory in search_dirs():
        candidate = Path(directory) / entry.file
        if candidate.is_file():
            return candidate
    return None


def ad_hoc(path: Path | str) -> ModelRef:
    """Entrada sintética para una ruta explícita a un GGUF."""
    target = Path(path)
    entry = ModelEntry(
        alias=target.name,
        name=str(target),
        kind="gguf",
        license="desconocida",
        file=target.name,
        prompt_style="chat",
    )
    return ModelRef(entry, target)


def ref_for_path(path: Path | str) -> ModelRef:
    """ModelRef de la entrada cuyo fichero es ``path``; si no casa, entrada ad-hoc."""
    target = Path(path)
    for entry in load_catalog().values():
        if entry.kind != "gguf" or entry.file != target.name:
            continue
        found = find_downloaded(entry)
        if found is not None and found.resolve() == target.resolve():
            return ModelRef(entry, found)
    return ad_hoc(target)


def resolve(value: str) -> ModelRef:
    """Alias del catálogo o ruta a un .gguf; el alias gana siempre."""
    entries = load_catalog()
    if value in entries:
        entry = entries[value]
        if entry.kind == "gguf":
            found = find_downloaded(entry)
            if found is None:
                raise CatalogError(
                    f"el modelo {value} no está descargado: vlm-ocr models fetch {value}"
                )
            return ModelRef(entry, found)
        return ModelRef(entry)
    if value.lower().endswith(".gguf") or Path(value).is_file():
        return ad_hoc(value)
    disponibles = ", ".join(sorted(entries))
    raise CatalogError(
        f"alias desconocido: {value}. Alias disponibles: {disponibles}. "
        "También se admite una ruta .gguf"
    )


def by_profile(profile: str) -> ModelRef:
    """Modelo local con ese perfil; nunca resuelve a un proveedor remoto."""
    entries = load_catalog()
    candidates = [entry for entry in entries.values() if entry.kind == "gguf" and entry.profile == profile]
    if not candidates:
        available = sorted(
            {entry.profile for entry in entries.values() if entry.kind == "gguf" and entry.profile}
        )
        raise CatalogError(
            f"perfil desconocido: {profile!r}. Perfiles disponibles: {', '.join(available) or '—'}"
        )
    if len(candidates) > 1:
        aliases = ", ".join(sorted(entry.alias for entry in candidates))
        raise CatalogError(f"perfil ambiguo {profile!r}: {aliases}")
    entry = candidates[0]
    found = find_downloaded(entry)
    if found is None:
        raise CatalogError(
            f"el modelo {entry.alias} no está descargado: vlm-ocr models fetch {entry.alias}"
        )
    return ModelRef(entry, found)


def default_ref() -> ModelRef | None:
    """Modelo por defecto, solo si está descargado."""
    entry = _default_entry()
    if entry is None:
        return None
    found = find_downloaded(entry)
    return ModelRef(entry, found) if found is not None else None


def default_alias() -> str | None:
    """Alias del modelo por defecto, exista o no en disco."""
    entry = _default_entry()
    return entry.alias if entry is not None else None


def _default_entry() -> ModelEntry | None:
    for entry in load_catalog().values():
        if entry.default:
            return entry
    return None


def default_dest() -> Path:
    """Destino por defecto: ``models/`` del repo si es un checkout; si no, datos de usuario."""
    repo_root = Path(__file__).resolve().parents[2]
    if (repo_root / "pyproject.toml").is_file():
        return repo_root / "models"
    return Path.home() / ".local" / "share" / "vlm-local-ocr" / "models"


def fetch(
    alias: str,
    *,
    dest: Path | str | None = None,
    accept_license: bool = False,
    token: str | None = None,
    progress: Callable[[str], None] | None = None,
) -> Path:
    """Descarga el GGUF del alias, verifica su sha256 y lo deja en ``dest``."""
    entries = load_catalog()
    if alias not in entries:
        disponibles = ", ".join(sorted(entries))
        raise CatalogError(f"alias desconocido: {alias}. Alias disponibles: {disponibles}")
    entry = entries[alias]
    if entry.kind != "gguf":
        raise CatalogError(f"{alias} es un modelo remoto: no hay nada que descargar")
    if entry.acceptance_required and not accept_license:
        raise CatalogError(
            f"la licencia de {alias} requiere aceptación explícita ({entry.license_url}); "
            "repite con --accept-license"
        )
    token = token or os.environ.get("HF_TOKEN")
    if entry.gated and not token:
        raise CatalogError(
            f"{alias} es un repositorio gated: acepta la licencia en Hugging Face y "
            "exporta HF_TOKEN"
        )

    directory = Path(dest) if dest is not None else default_dest()
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / str(entry.file)
    say = progress or (lambda message: print(message))

    if target.is_file():
        if verify_file(entry, target):
            say(f"modelo ya presente y verificado: {target}")
            return target
        say(f"hash incorrecto en {target}; se vuelve a descargar")
        target.unlink()

    headers = {"Authorization": f"Bearer {token}"} if token else {}
    request = urllib.request.Request(str(entry.url), headers=headers)
    temporary = target.with_suffix(target.suffix + ".part")
    say(f"descargando {entry.url}")
    try:
        with urllib.request.urlopen(request, timeout=60) as response, temporary.open("wb") as out:
            total = int(response.headers.get("Content-Length") or 0) or entry.size_bytes or 0
            done = 0
            printed = -1
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                out.write(chunk)
                done += len(chunk)
                if total:
                    percent = done * 100 // total
                    if percent // 5 != printed // 5:
                        printed = percent
                        say(f"{percent}% ({done // (1024 * 1024)} MB de {total // (1024 * 1024)} MB)")
    except urllib.error.HTTPError as exc:
        temporary.unlink(missing_ok=True)
        if exc.code == 401:
            raise CatalogError(
                f"401 al descargar {entry.url}: acepta la licencia en Hugging Face y "
                "exporta HF_TOKEN"
            ) from exc
        raise CatalogError(f"error HTTP {exc.code} al descargar {entry.url}") from exc
    except urllib.error.URLError as exc:
        temporary.unlink(missing_ok=True)
        raise CatalogError(f"no se pudo descargar {entry.url}: {exc.reason}") from exc

    if not verify_file(entry, temporary):
        temporary.unlink(missing_ok=True)
        raise CatalogError(f"sha256 no coincide para {alias}: descarga corrupta")
    temporary.rename(target)
    say(f"modelo listo: {target}")
    return target


def redistributable_files() -> list[str]:
    """GGUF del catálogo que pueden viajar dentro del release."""
    return sorted(
        entry.file
        for entry in load_catalog().values()
        if entry.redistributable and entry.kind == "gguf" and entry.file
    )


def license_files() -> list[str]:
    """Textos de licencia que deben acompañar a los modelos redistribuibles."""
    return sorted(
        {
            entry.license_file
            for entry in load_catalog().values()
            if entry.redistributable and entry.license_file
        }
    )
