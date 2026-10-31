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
_EN_NUMBER_RE = re.compile(r"^-?\d{1,3}(?:,\d{3})+(?:\.\d+)?$")
_CURRENCY_RE = re.compile(
    r"(EUR|USD|GBP|MXN|ARS|CLP|COP|JPY|KRW|SAR|AED|[$€£¥])", re.IGNORECASE
)
MAX_INSTRUCTIONS_CHARS = 4000


class ContractError(RuntimeError):
    """El contrato no se pudo cargar, inferir o validar."""


def load_contract(path: Path | str) -> tuple[dict, str]:
    """Carga un contrato y decide si es JSON Schema o ejemplo de datos."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ContractError("el contrato debe ser un objeto JSON")
    kind = "schema" if ("$schema" in data or "$defs" in data) else "example"
    return data, kind


def sidecar_path(contract_path: Path | str) -> Path:
    """Devuelve la ruta del sidecar de instrucciones para un contrato."""
    return Path(contract_path).with_suffix(".prompt.md")


def load_instructions(
    contract_path: Path | str, explicit: Path | str | None = None
) -> str | None:
    """Lee las instrucciones de ajuste (explícitas o sidecar). None si no hay."""
    if explicit is not None:
        path = Path(explicit)
        if not path.exists():
            raise ContractError(f"no existe el fichero de instrucciones: {path}")
    else:
        path = sidecar_path(contract_path)
        if not path.exists():
            return None

    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return None
    if len(text) > MAX_INSTRUCTIONS_CHARS:
        raise ContractError(
            f"las instrucciones superan {MAX_INSTRUCTIONS_CHARS} caracteres ({len(text)})"
        )
    return text


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


def _numeric_value(value: Any) -> float | None:
    """Extrae un número inequívoco de un valor o string (admite moneda)."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    if not isinstance(value, str):
        return None
    cleaned = _CURRENCY_RE.sub("", value).replace("\u00a0", " ").strip()
    if _NUMBER_RE.match(cleaned):
        return float(cleaned)
    if _EN_NUMBER_RE.match(cleaned):
        return float(cleaned.replace(",", ""))
    return None


def _is_unambiguous_number(value: Any) -> bool:
    return _numeric_value(value) is not None


def _validate(value: Any, shape: Any, path: str) -> list[str]:
    if value is None:
        return []
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
    instructions: str | None = None,
) -> dict:
    """Pide al LLM local un JSON que cumpla el contrato y lo valida."""
    if Llama is None:
        raise ContractError(
            "llama-cpp-python no está instalado; instálalo para usar --format json"
        )
    llm = Llama(model_path=str(model_path), n_ctx=n_ctx, verbose=False)
    ocr_text = _truncate_text(text, max_ocr_tokens)
    messages = _build_messages(ocr_text, contract, kind, instructions)
    base_max_tokens = max(256, len(json.dumps(contract, ensure_ascii=False)) * 2)

    raw = _chat(llm, messages, contract, kind, base_max_tokens)
    data, errors = _parse_and_validate(raw, contract, kind)
    if not errors:
        return _apply_label_anchors(_coerce_numbers(data, contract), text, contract)

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
    return _apply_label_anchors(_coerce_numbers(data, contract), text, contract)


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


def _shape_template(value: Any) -> Any:
    """Sustituye valores del ejemplo por marcadores de tipo."""
    if isinstance(value, dict):
        return {key: _shape_template(sub) for key, sub in value.items()}
    if isinstance(value, list):
        return [_shape_template(value[0])] if value else []
    if isinstance(value, bool):
        return "<boolean>"
    if isinstance(value, int | float):
        return "<number>"
    if isinstance(value, str):
        return "<string>"
    return value


def _build_messages(
    ocr_text: str, contract: dict, kind: str, instructions: str | None = None
) -> list[dict]:
    ocr_text = _normalize_numbers(ocr_text)
    label = "JSON Schema" if kind == "schema" else "shape"
    header = "SCHEMA" if kind == "schema" else "SHAPE"
    shape = contract if kind == "schema" else _shape_template(contract)
    task_block = (
        f"TASK-SPECIFIC INSTRUCTIONS:\n{instructions}\n\n" if instructions else ""
    )
    prompt = (
        "You extract structured data from OCR text.\n"
        "Example:\n"
        'OCR TEXT: "ID: A-100. Date: 2024-01-02."\n'
        'SHAPE: {"id": "<string>", "date": "<string>", "note": "<string>"}\n'
        'OUTPUT: {"id": "A-100", "date": "2024-01-02", "note": null}\n\n'
        f"Return ONLY a JSON value that conforms to the {label}. "
        "Markers like <string> and <number> describe the required type; never output them literally. "
        "Do not invent values; use null when the information is absent.\n"
        "Copy values literally from the OCR text. Do not perform calculations: no sums, subtotals, "
        "percentage applications, averages, or derived figures. Formatting a written number or date is "
        "allowed, but never compute a value that is not written in the text. "
        "Always include every key from the shape. If a value is not explicitly written, output null for that "
        "key instead of computing or copying it from another field.\n"
        "Rules: output numbers as JSON numbers, not strings. "
        "A comma is the decimal separator and a dot is a thousands separator: "
        "'1.234,56' or '50,00' become 1234.56 and 50.00; never drop the decimal comma. "
        "No currency symbols. Dates use YYYY-MM-DD when possible; copy names and identifiers verbatim. "
        "Take every value from the OCR text and never reuse the same value for two different fields "
        "(for example, do not use the date as an invoice number). "
        "Extract the minimal literal value for each field: do not include the field label, "
        "neighboring fields, or unrelated text. "
        "Match each field to the value that follows its label or a direct synonym. "
        "Do not use a number that belongs to a different label (for example, do not use a unit "
        "        price or a quantity as the total).\n\n"
        f"{task_block}"
        f"{header}:\n{json.dumps(shape, ensure_ascii=False, indent=2)}\n\n"
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


def _coerce_numbers(value: Any, shape: Any) -> Any:
    """Convierte strings numéricos inequívocos al tipo numérico del ejemplo."""
    if shape is None:
        return value
    if isinstance(shape, dict) and isinstance(value, dict):
        return {
            key: _coerce_numbers(sub, shape[key]) if key in shape else sub
            for key, sub in value.items()
        }
    if isinstance(shape, list) and isinstance(value, list):
        if not shape:
            return value
        options = _distinct_shapes(shape)
        coerced = []
        for item in value:
            chosen = next(
                (option for option in options if not _validate(item, option, "$")),
                options[0],
            )
            coerced.append(_coerce_numbers(item, chosen))
        return coerced
    if isinstance(shape, float) and not isinstance(value, bool):
        number = _numeric_value(value)
        if number is not None:
            return number
    if isinstance(shape, int) and not isinstance(shape, bool):
        number = _numeric_value(value)
        if number is not None and float(number).is_integer():
            return int(number)
    return value


def _label_number(text: str, label: str) -> float | None:
    """Busca ``etiqueta: número`` en el texto y devuelve el número."""
    pattern = re.compile(
        rf"(?i)\b{re.escape(label.replace('_', ' '))}\b\s*[:=]?\s*(-?\d[\d.,]*)",
    )
    match = pattern.search(text)
    if match is None:
        return None
    return _numeric_value(_normalize_numbers(match.group(1)))


def _apply_label_anchors(data: Any, text: str, contract: dict) -> Any:
    """Si el campo numérico aparece etiquetado, prevalece el literal etiquetado."""
    if not isinstance(data, dict) or not isinstance(contract, dict):
        return data
    anchored = dict(data)
    for field, shape in contract.items():
        if isinstance(shape, bool) or not isinstance(shape, int | float):
            continue
        value = _label_number(text, field)
        if value is None:
            continue
        anchored[field] = int(value) if isinstance(shape, int) else value
    return anchored
