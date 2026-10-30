from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import jsonschema

_NUMBER_RE = re.compile(r"^-?\d+(?:\.\d+)?$")


class ContractError(RuntimeError):
    """El contrato no se pudo cargar, inferir o validar."""


def load_contract(path: Path | str) -> tuple[dict, str]:
    """Carga un contrato y decide si es JSON Schema o ejemplo de datos."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ContractError("el contrato debe ser un objeto JSON")
    kind = "schema" if ("$schema" in data or "$defs" in data) else "example"
    return data, kind


def validate_payload(data: Any, contract: dict, kind: str) -> list[str]:
    """Devuelve la lista de errores estructurales; vacía significa válido."""
    if kind == "schema":
        validator = jsonschema.Draft202012Validator(contract)
        errors = sorted(validator.iter_errors(data), key=lambda error: list(error.path))
        return [f"{_format_path(error.path)}: {error.message}" for error in errors]
    if kind != "example":
        raise ContractError(f"tipo de contrato desconocido: {kind!r}")
    return _validate(data, contract, "$")


def _format_path(parts: Any) -> str:
    path = "$"
    for part in parts:
        path += f"[{part}]" if isinstance(part, int) else f".{part}"
    return path


def _type_name(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "str"
    if isinstance(value, list):
        return "list"
    if isinstance(value, dict):
        return "dict"
    return type(value).__name__


def _is_unambiguous_number(value: Any) -> bool:
    return isinstance(value, str) and bool(_NUMBER_RE.match(value.strip()))


def _validate(value: Any, shape: Any, path: str) -> list[str]:
    if shape is None:
        return []

    if isinstance(shape, dict):
        if not isinstance(value, dict):
            return [f"{path}: se esperaba objeto, llegó {_type_name(value)}"]
        errors: list[str] = []
        for key, subshape in shape.items():
            child = f"{path}.{key}"
            if key not in value:
                errors.append(f"{child}: falta campo requerido")
            else:
                errors.extend(_validate(value[key], subshape, child))
        for key in value:
            if key not in shape:
                errors.append(f"{path}.{key}: campo extra no permitido")
        return errors

    if isinstance(shape, list):
        if not isinstance(value, list):
            return [f"{path}: se esperaba lista, llegó {_type_name(value)}"]
        if not shape:
            return []
        options = _distinct_shapes(shape)
        errors = []
        for index, item in enumerate(value):
            item_path = f"{path}[{index}]"
            item_errors = _validate_against_options(item, options, item_path)
            errors.extend(item_errors)
        return errors

    return _validate_scalar(value, shape, path)


def _distinct_shapes(shapes: list[Any]) -> list[Any]:
    seen: set[str] = set()
    options: list[Any] = []
    for shape in shapes:
        key = json.dumps(shape, sort_keys=True, ensure_ascii=False)
        if key not in seen:
            seen.add(key)
            options.append(shape)
    return options


def _validate_against_options(value: Any, options: list[Any], path: str) -> list[str]:
    first_errors: list[str] | None = None
    for option in options:
        errors = _validate(value, option, path)
        if not errors:
            return []
        if first_errors is None:
            first_errors = errors
    return first_errors or [f"{path}: no coincide con ningún elemento del ejemplo"]


def _validate_scalar(value: Any, shape: Any, path: str) -> list[str]:
    if isinstance(shape, bool):
        ok = isinstance(value, bool)
    elif isinstance(shape, int):
        ok = isinstance(value, int) and not isinstance(value, bool)
        ok = ok or _is_unambiguous_number(value)
    elif isinstance(shape, float):
        ok = (isinstance(value, int | float) and not isinstance(value, bool)) or _is_unambiguous_number(value)
    elif isinstance(shape, str):
        ok = isinstance(value, str)
    else:
        ok = True
        if _type_name(value) != _type_name(shape):
            return [f"{path}: tipo no soportado en el ejemplo: {_type_name(shape)}"]

    if not ok:
        return [f"{path}: se esperaba {_type_name(shape)}, llegó {_type_name(value)}"]
    return []
