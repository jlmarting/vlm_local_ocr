"""Resolución de rutas de datos y configuración por plataforma.

Un solo punto de decisión: plantillas, catálogo de usuario y modelos descargados
preguntan aquí. La guarda de compatibilidad prefiere el directorio legado (XDG)
mientras exista con contenido y el nuevo esté vacío, para no perder datos.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Mapping
from pathlib import Path

APP = "vlm-local-ocr"


def _with_defaults(
    platform: str | None,
    env: Mapping[str, str] | None,
    home: Path | None,
) -> tuple[str, Mapping[str, str], Path]:
    return (
        sys.platform if platform is None else platform,
        os.environ if env is None else env,
        Path.home() if home is None else Path(home),
    )


def _xdg_data_root(env: Mapping[str, str], home: Path) -> Path:
    base = env.get("XDG_DATA_HOME")
    return Path(base) if base else home / ".local" / "share"


def _new_data_dir(platform: str, env: Mapping[str, str], home: Path) -> Path:
    if platform == "win32":
        base = env.get("LOCALAPPDATA")
        if base:
            return Path(base) / APP
    elif platform == "darwin":
        return home / "Library" / "Application Support" / APP
    return _xdg_data_root(env, home) / APP


def _legacy_data_dir(env: Mapping[str, str], home: Path) -> Path:
    return _xdg_data_root(env, home) / APP


def _new_config_dir(platform: str, env: Mapping[str, str], home: Path) -> Path:
    if platform == "win32":
        base = env.get("APPDATA")
        if base:
            return Path(base) / APP
    elif platform == "darwin":
        return home / "Library" / "Application Support" / APP
    return home / ".config" / APP


def _legacy_config_dir(env: Mapping[str, str], home: Path) -> Path:
    return home / ".config" / APP


def _has_content(path: Path) -> bool:
    if not path.exists():
        return False
    if path.is_file():
        return True
    try:
        return any(path.iterdir())
    except OSError:
        return False


def _resolve(new: Path, legacy: Path) -> Path:
    if new != legacy and _has_content(legacy) and not _has_content(new):
        return legacy
    return new


def data_dir(
    platform: str | None = None,
    env: Mapping[str, str] | None = None,
    home: Path | None = None,
) -> Path:
    """Directorio de datos: plantillas homologadas y modelos descargados."""
    platform, env, home = _with_defaults(platform, env, home)
    return _resolve(_new_data_dir(platform, env, home), _legacy_data_dir(env, home))


def config_dir(
    platform: str | None = None,
    env: Mapping[str, str] | None = None,
    home: Path | None = None,
) -> Path:
    """Directorio de configuración: overlay del catálogo de usuario."""
    platform, env, home = _with_defaults(platform, env, home)
    return _resolve(_new_config_dir(platform, env, home), _legacy_config_dir(env, home))
