from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import jsonschema

try:
    from llama_cpp import Llama
except ImportError:  # permite usar el modo Markdown sin el motor LLM
    Llama = None  # type: ignore[assignment]

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


def infer_contract(
    text: str,
    contract: dict,
    kind: str,
    model_path: Path | str,
    *,
    n_ctx: int = 4096,
    max_ocr_tokens: int = 1500,
) -> dict:
    """Pide al LLM local un JSON que cumpla el contrato y lo valida."""
    if Llama is None:
        raise ContractError(
            "llama-cpp-python no está instalado; instálalo para usar --format json"
        )
    llm = Llama(model_path=str(model_path), n_ctx=n_ctx, verbose=False)
    ocr_text = _truncate_text(text, max_ocr_tokens)
    messages = _build_messages(ocr_text, contract, kind)
    base_max_tokens = max(256, len(json.dumps(contract, ensure_ascii=False)) * 2)

    raw = _chat(llm, messages, contract, kind, base_max_tokens)
    data, errors = _parse_and_validate(raw, contract, kind)
    if not errors:
        return data

    repair_messages = [
        *messages,
        {"role": "assistant", "content": raw},
        {
            "role": "user",
            "content": (
                "Your previous answer was invalid. Errors: "
                + "; ".join(errors)
                + ". Return ONLY the corrected JSON."
            ),
        },
    ]
    raw_retry = _chat(llm, repair_messages, contract, kind, base_max_tokens * 2)
    data, errors = _parse_and_validate(raw_retry, contract, kind)
    if errors:
        raise ContractError("el modelo no produjo un contrato válido: " + "; ".join(errors))
    return data


def _truncate_text(text: str, max_ocr_tokens: int) -> str:
    limit = max(1, max_ocr_tokens) * 4
    if len(text) <= limit:
        return text
    return text[:limit]


def _normalize_numbers(text: str) -> str:
    """Normaliza el formato numérico europeo para que el modelo no lo confunda."""
    text = re.sub(r"(?<=\d)\.(?=\d{3}(?:\D|$))", "", text)
    text = re.sub(r"(?<=\d),(?=\d{1,2}(?:\D|$))", ".", text)
    return text


def _build_messages(ocr_text: str, contract: dict, kind: str) -> list[dict]:
    ocr_text = _normalize_numbers(ocr_text)
    label = "JSON Schema" if kind == "schema" else "example"
    header = "SCHEMA" if kind == "schema" else "EXAMPLE"
    prompt = (
        f"You extract structured data from OCR text.\n"
        f"Return ONLY a JSON value that conforms to the {label}. "
        "Do not invent values; use null when the information is absent.\n"
        "Rules: output numbers as JSON numbers, not strings. "
        "A comma is the decimal separator and a dot is a thousands separator: "
        "'1.234,56' or '50,00' become 1234.56 and 50.00; never drop the decimal comma. "
        "No currency symbols. Dates use YYYY-MM-DD when possible; copy names and identifiers verbatim.\n\n"
        f"{header}:\n{json.dumps(contract, ensure_ascii=False, indent=2)}\n\n"
        f"OCR TEXT:\n{ocr_text}\n"
    )
    return [{"role": "user", "content": prompt}]


def _chat(
    llm: Llama,
    messages: list[dict],
    contract: dict,
    kind: str,
    max_tokens: int,
) -> str:
    response_format: dict[str, Any] = {"type": "json_object"}
    if kind == "schema":
        response_format["schema"] = contract
    response = llm.create_chat_completion(
        messages=messages,
        temperature=0,
        max_tokens=max_tokens,
        response_format=response_format,
    )
    return response["choices"][0]["message"]["content"]


def _parse_and_validate(raw: str, contract: dict, kind: str) -> tuple[Any, list[str]]:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        return None, [f"la respuesta no es JSON válido ({exc.msg})"]
    return data, validate_payload(data, contract, kind)
