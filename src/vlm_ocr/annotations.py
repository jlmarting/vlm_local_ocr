from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any

SOURCE_ALIASES = {
    "UNIDADES": "unidades",
    "IMPORTE": "importe",
    "DEVENGADO": "devengado",
    "A DEDUCIR": "a_deducir",
    "DEDUCIR": "a_deducir",
    "BASE": "base",
    "BASES": "base",
    "BASES %": "base",
    "%": "porcentaje",
    "PORCENTAJE": "porcentaje",
    "CUOTA": "cuota",
}


@dataclass(frozen=True)
class FieldHint:
    """Un campo del contrato con su etiqueta en el documento y su columna."""

    path: str
    labels: tuple[str, ...]
    source: str | None
    kind: str | None


def normalize_label(text: str) -> str:
    """Mayúsculas, sin acentos, sin paréntesis y con espacios colapsados."""
    decomposed = unicodedata.normalize("NFKD", text)
    plain = "".join(char for char in decomposed if not unicodedata.combining(char))
    plain = re.sub(r"\([^)]*\)", " ", plain.upper())
    plain = re.sub(r"[^A-Z0-9%]+", " ", plain)
    return " ".join(plain.split())


def _kind(schema: dict) -> str | None:
    declared = schema.get("type")
    if isinstance(declared, list):
        for item in declared:
            if item != "null":
                return item
        return None
    return declared if isinstance(declared, str) else None


def _walk(schema: Any, path: str = ""):
    if not isinstance(schema, dict):
        return
    labels = schema.get("x-labels")
    if isinstance(labels, list) and labels:
        yield FieldHint(
            path=path,
            labels=tuple(str(label) for label in labels),
            source=schema.get("x-source"),
            kind=_kind(schema),
        )
    properties = schema.get("properties")
    if isinstance(properties, dict):
        for key, sub in properties.items():
            yield from _walk(sub, f"{path}.{key}" if path else key)


def field_map(schema: dict) -> list[FieldHint]:
    """Recorre el esquema y devuelve los campos anotados, en orden de documento."""
    return list(_walk(schema))


def has_annotations(schema: dict) -> bool:
    return any(True for _ in _walk(schema))


def leaf_paths(schema: Any, path: str = "") -> list[str]:
    """Rutas de todas las hojas del esquema (propiedades sin ``properties``)."""
    if not isinstance(schema, dict):
        return [path] if path else []
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        return [path] if path else []
    leaves: list[str] = []
    for key, sub in properties.items():
        leaves.extend(leaf_paths(sub, f"{path}.{key}" if path else key))
    return leaves
