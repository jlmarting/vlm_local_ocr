from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any

from .errors import ContractError

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
    join_label: bool | None = None


ITEM_ROLES = {"text", "quantity", "number_right", "observation"}


@dataclass(frozen=True)
class ItemHint:
    """Un array repetido con los roles geométricos de sus propiedades."""

    path: str
    columns: dict[str, str]
    stop_labels: tuple[str, ...]
    start_labels: tuple[str, ...]


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
        join = schema.get("x-join-label")
        yield FieldHint(
            path=path,
            labels=tuple(str(label) for label in labels),
            source=schema.get("x-source"),
            kind=_kind(schema),
            join_label=join if isinstance(join, bool) else None,
        )
    properties = schema.get("properties")
    if isinstance(properties, dict):
        for key, sub in properties.items():
            yield from _walk(sub, f"{path}.{key}" if path else key)


def field_map(schema: dict) -> list[FieldHint]:
    """Recorre el esquema y devuelve los campos anotados, en orden de documento."""
    return list(_walk(schema))


def _has_array_type(node: dict) -> bool:
    declared = node.get("type")
    return declared == "array" or (
        isinstance(declared, list) and "array" in declared
    )


def _item_hint(node: dict, path: str) -> ItemHint:
    raw_columns = node.get("x-item-columns")
    if not isinstance(raw_columns, dict) or not raw_columns:
        raise ContractError(f"{path}: x-item-columns debe ser un objeto no vacío")
    if "x-stop-labels" not in node:
        raise ContractError(f"{path}: falta x-stop-labels (puede ser una lista vacía)")
    raw_stop = node.get("x-stop-labels")
    if not isinstance(raw_stop, list):
        raise ContractError(f"{path}: x-stop-labels debe ser una lista")
    raw_start = node.get("x-item-labels", [])
    if not isinstance(raw_start, list):
        raise ContractError(f"{path}: x-item-labels debe ser una lista")

    items = node.get("items")
    properties = items.get("properties") if isinstance(items, dict) else None
    if not isinstance(properties, dict):
        raise ContractError(f"{path}: el array necesita items.properties")

    columns: dict[str, str] = {}
    seen_roles: set[str] = set()
    for prop, role in raw_columns.items():
        if not isinstance(prop, str) or prop not in properties:
            raise ContractError(f"{path}: propiedad desconocida en x-item-columns: {prop!r}")
        if not isinstance(role, str) or role not in ITEM_ROLES:
            raise ContractError(f"{path}: rol desconocido en x-item-columns: {role!r}")
        if role in seen_roles:
            raise ContractError(f"{path}: rol duplicado en x-item-columns: {role!r}")
        seen_roles.add(role)
        columns[prop] = role
    for required in ("text", "number_right"):
        if required not in seen_roles:
            raise ContractError(f"{path}: x-item-columns necesita un rol {required}")

    return ItemHint(
        path=path,
        columns=columns,
        stop_labels=tuple(str(label) for label in raw_stop),
        start_labels=tuple(str(label) for label in raw_start),
    )


def _walk_items(schema: Any, path: str = ""):
    if not isinstance(schema, dict):
        return
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        return
    for key, sub in properties.items():
        if not isinstance(sub, dict):
            continue
        full = f"{path}.{key}" if path else key
        if _has_array_type(sub) and "x-item-columns" in sub:
            yield _item_hint(sub, full)
        yield from _walk_items(sub, full)


def item_hints(schema: dict) -> list[ItemHint]:
    """Arrays anotados con roles de línea, en orden de documento."""
    return list(_walk_items(schema))


def has_item_annotations(schema: dict) -> bool:
    return any(True for _ in _walk_items(schema))


def has_annotations(schema: dict) -> bool:
    return any(True for _ in _walk(schema)) or has_item_annotations(schema)


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


def example_leaf_paths(example: Any, path: str = "") -> list[str]:
    """Rutas de las hojas de un payload de ejemplo (solo objetos anidados)."""
    if isinstance(example, dict):
        leaves: list[str] = []
        for key, sub in example.items():
            leaves.extend(example_leaf_paths(sub, f"{path}.{key}" if path else key))
        return leaves
    return [path] if path else []


def leaf_paths_for(contract: dict, kind: str) -> list[str]:
    """Hojas del contrato, sea JSON Schema o ejemplo de payload."""
    if kind == "schema":
        return leaf_paths(contract)
    if kind == "example":
        return example_leaf_paths(contract)
    return []


def _schema_leaf_types(schema: Any, path: str = "") -> dict[str, str]:
    if not isinstance(schema, dict):
        return {}
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        kind = _kind(schema)
        return {path: kind} if path and kind else {}
    types: dict[str, str] = {}
    for key, sub in properties.items():
        types.update(_schema_leaf_types(sub, f"{path}.{key}" if path else key))
    return types


def _example_leaf_types(example: Any, path: str = "") -> dict[str, str]:
    if isinstance(example, dict):
        types: dict[str, str] = {}
        for key, sub in example.items():
            types.update(_example_leaf_types(sub, f"{path}.{key}" if path else key))
        return types
    if isinstance(example, bool):
        kind = "boolean"
    elif isinstance(example, int):
        kind = "integer"
    elif isinstance(example, float):
        kind = "number"
    elif isinstance(example, list):
        kind = "array"
    else:
        kind = "string"
    return {path: kind} if path else {}


def leaf_types_for(contract: dict, kind: str) -> dict[str, str]:
    """Tipo declarado (Schema) o inferido (ejemplo) de cada hoja."""
    if kind == "schema":
        return _schema_leaf_types(contract)
    if kind == "example":
        return _example_leaf_types(contract)
    return {}
