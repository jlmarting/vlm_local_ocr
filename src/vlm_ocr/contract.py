from __future__ import annotations

import json
import re
from pathlib import Path
from time import perf_counter
from typing import Any

import jsonschema

_NUMBER_RE = re.compile(r"^-?\d+(?:\.\d+)?$")
_EN_NUMBER_RE = re.compile(r"^-?\d{1,3}(?:,\d{3})+(?:\.\d+)?$")
_CURRENCY_RE = re.compile(
    r"(EUR|USD|GBP|MXN|ARS|CLP|COP|JPY|KRW|SAR|AED|[$€£¥])", re.IGNORECASE
)
MAX_INSTRUCTIONS_CHARS = 4000
MAX_PROMPT_CHARS = 4000
CONTEXT_MARGIN_TOKENS = 64
MIN_OUTPUT_TOKENS = 256


from .catalog import ModelRef, ad_hoc
from .errors import ContractError
from .inputs import is_stdin
from .llmrun import BuiltPrompt, Runner, runner_for
from .promptstyles import (
    build_free_prompt,
    build_prompt,
    build_repair_prompt,
    normalize_numbers,
)


def load_contract(
    path: Path | str, *, data: bytes | None = None
) -> tuple[dict, str]:
    """Carga un contrato desde fichero o bytes de stdin y detecta su tipo."""
    contract_path = Path(path)
    where = "stdin" if data is not None else str(contract_path)
    if data is not None:
        text = _decode(data, f"el contrato no es UTF-8 válido: {where}")
    else:
        if not contract_path.exists():
            raise ContractError(f"no existe el contrato: {contract_path}")
        try:
            text = contract_path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise ContractError(
                f"el contrato no es UTF-8 válido: {contract_path}"
            ) from exc
        except OSError as exc:
            raise ContractError(
                f"no se pudo leer el contrato {contract_path}: {exc}"
            ) from exc
    return _parse_contract(text, where)


def _decode(data: bytes, message: str) -> str:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ContractError(message) from exc


def _parse_contract(text: str, where: str) -> tuple[dict, str]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ContractError(
            f"contrato JSON inválido en {where} (línea {exc.lineno}): {exc.msg}"
        ) from exc
    if not isinstance(data, dict):
        raise ContractError("el contrato debe ser un objeto JSON")
    kind = "schema" if ("$schema" in data or "$defs" in data) else "example"
    return data, kind


def sidecar_path(contract_path: Path | str) -> Path:
    """Devuelve la ruta del sidecar de instrucciones para un contrato."""
    return Path(contract_path).with_suffix(".prompt.md")


def load_instructions(
    contract_path: Path | str,
    explicit: Path | str | None = None,
    *,
    data: bytes | None = None,
) -> str | None:
    """Lee las instrucciones de ajuste (explícitas, sidecar o stdin). None si no hay."""
    if data is not None:
        return _instructions_from_bytes(data)
    if explicit is not None:
        path = Path(explicit)
        if is_stdin(path):
            raise ContractError("las instrucciones por stdin no se han leído")
        if not path.exists():
            raise ContractError(f"no existe el fichero de instrucciones: {path}")
    else:
        if is_stdin(contract_path):
            return None
        path = sidecar_path(contract_path)
        if not path.exists():
            return None

    if path.stat().st_size > MAX_INSTRUCTIONS_CHARS * 4:
        raise ContractError(
            f"las instrucciones superan {MAX_INSTRUCTIONS_CHARS} caracteres ({path})"
        )
    try:
        text = path.read_text(encoding="utf-8").strip()
    except UnicodeDecodeError as exc:
        raise ContractError(f"las instrucciones no son UTF-8 válido: {path}") from exc
    except OSError as exc:
        raise ContractError(f"no se pudieron leer las instrucciones {path}: {exc}") from exc
    if not text:
        return None
    if len(text) > MAX_INSTRUCTIONS_CHARS:
        raise ContractError(
            f"las instrucciones superan {MAX_INSTRUCTIONS_CHARS} caracteres ({len(text)})"
        )
    return text


def _instructions_from_bytes(data: bytes) -> str | None:
    if len(data) > MAX_INSTRUCTIONS_CHARS * 4:
        raise ContractError(
            f"las instrucciones superan {MAX_INSTRUCTIONS_CHARS} caracteres (stdin)"
        )
    text = _decode(data, "las instrucciones no son UTF-8 válido: stdin").strip()
    if not text:
        return None
    if len(text) > MAX_INSTRUCTIONS_CHARS:
        raise ContractError(
            f"las instrucciones superan {MAX_INSTRUCTIONS_CHARS} caracteres ({len(text)})"
        )
    return text


def load_prompt(path: Path | str, *, data: bytes | None = None) -> str:
    """Lee el prompt de una tarea libre desde fichero o stdin."""
    where = "stdin" if data is not None else str(path)
    if data is not None:
        if len(data) > MAX_PROMPT_CHARS * 4:
            raise ContractError(
                f"el prompt supera {MAX_PROMPT_CHARS} caracteres (stdin)"
            )
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise ContractError(f"el prompt no es UTF-8 válido: {where}") from exc
    else:
        prompt_path = Path(path)
        if not prompt_path.exists():
            raise ContractError(f"no existe el prompt: {prompt_path}")
        if prompt_path.stat().st_size > MAX_PROMPT_CHARS * 4:
            raise ContractError(
                f"el prompt supera {MAX_PROMPT_CHARS} caracteres ({prompt_path})"
            )
        try:
            text = prompt_path.read_text(encoding="utf-8-sig")
        except UnicodeDecodeError as exc:
            raise ContractError(f"el prompt no es UTF-8 válido: {prompt_path}") from exc
        except OSError as exc:
            raise ContractError(f"no se pudo leer el prompt {prompt_path}: {exc}") from exc

    text = text.strip()
    if not text:
        raise ContractError(f"el prompt está vacío: {where}")
    if len(text) > MAX_PROMPT_CHARS:
        raise ContractError(
            f"el prompt supera {MAX_PROMPT_CHARS} caracteres ({len(text)})"
        )
    return text


def validate_payload(data: Any, contract: dict, kind: str) -> list[str]:
    """Devuelve la lista de errores estructurales; vacía significa válido."""
    if kind == "schema":
        try:
            validator_cls = jsonschema.validators.validator_for(
                contract, default=jsonschema.Draft202012Validator
            )
            validator_cls.check_schema(contract)
            validator = validator_cls(contract)
            errors = sorted(validator.iter_errors(data), key=lambda error: str(list(error.path)))
        except jsonschema.exceptions.SchemaError as exc:
            raise ContractError(f"JSON Schema inválido: {exc.message}") from exc
        except Exception as exc:
            raise ContractError(f"error validando el JSON Schema: {exc}") from exc
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
        number = _numeric_value(value)
        ok = number is not None and float(number).is_integer()
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
    model: ModelRef | Path | str,
    *,
    n_ctx: int = 4096,
    max_ocr_tokens: int = 1500,
    instructions: str | None = None,
    max_output_tokens: int | None = None,
    usage_out: dict[str, Any] | None = None,
) -> dict:
    """Pide al LLM local un JSON que cumpla el contrato y lo valida.

    ``usage_out``, si se pasa, se rellena con carga, intentos y tokens; sin él
    (uso normal) no se mide nada.
    """
    ref = model if isinstance(model, ModelRef) else ad_hoc(model)
    runner: Runner = runner_for(n_ctx=n_ctx, ref=ref)
    if usage_out is not None:
        usage_out["load_time_ms"] = runner.load_time_ms
    generation_start = perf_counter()
    attempts = 0
    totals: dict[str, int] = {}
    seen_usage = False

    ocr_text = _truncate_text(text, max_ocr_tokens)
    prompt = build_prompt(ref, ocr_text, contract, kind, instructions)
    requested = (
        max_output_tokens
        or ref.entry.max_tokens
        or max(256, len(json.dumps(contract, ensure_ascii=False)) * 2)
    )
    limit = n_ctx if not ref.is_remote else (ref.entry.context or n_ctx)

    raw, usage, finish_reason, budget = _chat_with_budget(runner, prompt, requested, limit)
    attempts += 1
    seen_usage = _accumulate_usage(totals, usage) or seen_usage
    _finish_usage(usage_out, attempts, totals, seen_usage, generation_start, finish_reason, budget)
    if finish_reason == "length":
        raise ContractError(_truncated_message(usage, budget))
    data, errors = _parse_and_validate(raw, contract, kind)
    if not errors:
        return _validated_final(data, contract, kind, text)
    if ref.entry.prompt_style != "chat":
        raise ContractError("el modelo no produjo un contrato válido: " + "; ".join(errors))

    repair_prompt = build_repair_prompt(ref, prompt, raw, errors)
    raw_retry, usage, finish_reason, budget = _chat_with_budget(
        runner, repair_prompt, requested, limit
    )
    attempts += 1
    seen_usage = _accumulate_usage(totals, usage) or seen_usage
    _finish_usage(usage_out, attempts, totals, seen_usage, generation_start, finish_reason, budget)
    if finish_reason == "length":
        raise ContractError(_truncated_message(usage, budget))
    data, errors = _parse_and_validate(raw_retry, contract, kind)
    if errors:
        raise ContractError("el modelo no produjo un contrato válido: " + "; ".join(errors))
    return _validated_final(data, contract, kind, text)


def infer_answer(
    text: str,
    task: str,
    model: ModelRef | Path | str,
    *,
    n_ctx: int = 4096,
    max_ocr_tokens: int = 1500,
    max_output_tokens: int | None = None,
    usage_out: dict[str, Any] | None = None,
) -> str:
    """Aplica una tarea libre al texto con el LLM, sin contrato ni verificación."""
    ref = model if isinstance(model, ModelRef) else ad_hoc(model)
    if ref.entry.prompt_style != "chat":
        raise ContractError("el estilo del modelo no admite --prompt; usa --contract")
    runner: Runner = runner_for(n_ctx=n_ctx, ref=ref)
    if usage_out is not None:
        usage_out["load_time_ms"] = runner.load_time_ms
    generation_start = perf_counter()
    prompt = build_free_prompt(ref, _truncate_text(text, max_ocr_tokens), task)
    requested = max_output_tokens or ref.entry.max_tokens or 1200
    limit = n_ctx if not ref.is_remote else (ref.entry.context or n_ctx)
    raw, usage, finish_reason, budget = _chat_with_budget(
        runner, prompt, requested, limit
    )
    totals: dict[str, int] = {}
    seen_usage = _accumulate_usage(totals, usage)
    _finish_usage(
        usage_out, 1, totals, seen_usage, generation_start, finish_reason, budget
    )
    if finish_reason == "length":
        written = (usage or {}).get("completion_tokens") or budget
        raise ContractError(
            f"respuesta truncada por límite de tokens ({written} de {budget}); "
            "sube --max-tokens o --n-ctx"
        )
    answer = raw.strip()
    if not answer:
        raise ContractError("el modelo devolvió una respuesta vacía")
    return answer


def _token_budget(
    prompt_tokens: int,
    limit: int,
    requested: int,
    *,
    margin: int = CONTEXT_MARGIN_TOKENS,
    minimum: int = MIN_OUTPUT_TOKENS,
) -> int | None:
    """Tokens que caben para la respuesta; ``None`` si el prompt no deja hueco viable."""
    available = limit - prompt_tokens - margin
    if available < minimum:
        return None
    return min(requested, available)


def _chat_with_budget(
    runner: Runner,
    prompt: BuiltPrompt,
    requested: int,
    limit: int,
) -> tuple[str, dict[str, Any] | None, str | None, int]:
    """Llama al modelo con ``max_tokens`` ajustado al contexto disponible."""
    prompt_tokens = runner.estimate_tokens(prompt)
    budget = _token_budget(prompt_tokens, limit, requested)
    if budget is None:
        raise ContractError(
            f"el prompt ocupa ~{prompt_tokens} tokens y no deja hueco en el contexto "
            f"({limit}): reduce el contrato o el texto, o sube --max-tokens / --n-ctx"
        )
    content, usage, finish_reason = runner.complete(prompt, budget)
    return content, usage, finish_reason, budget


def _truncated_message(usage: dict[str, Any] | None, budget: int) -> str:
    written = (usage or {}).get("completion_tokens") or budget
    return (
        f"respuesta truncada por límite de tokens ({written} de {budget}): "
        "el modelo no cerró el JSON; reduce el contrato o sube --max-tokens / --n-ctx"
    )


def _accumulate_usage(totals: dict[str, int], usage: dict[str, Any] | None) -> bool:
    """Suma los tokens de un intento; devuelve si el backend informó de ``usage``."""
    if not usage:
        return False
    found = False
    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
        value = usage.get(key)
        if value is not None:
            totals[key] = totals.get(key, 0) + int(value)
            found = True
    return found


def _finish_usage(
    usage_out: dict[str, Any] | None,
    attempts: int,
    totals: dict[str, int],
    seen_usage: bool,
    generation_start: float,
    finish_reason: str | None = None,
    budget: int | None = None,
) -> None:
    """Cierra el bloque de uso: intentos, tokens, velocidad, techo y motivo de parada."""
    if usage_out is None:
        return
    usage_out["attempts"] = attempts
    usage_out["finish_reason"] = finish_reason
    usage_out["max_tokens"] = budget
    if not seen_usage:
        usage_out["prompt_tokens"] = None
        usage_out["completion_tokens"] = None
        usage_out["total_tokens"] = None
        usage_out["tokens_per_second"] = None
        return
    usage_out["prompt_tokens"] = totals.get("prompt_tokens")
    usage_out["completion_tokens"] = totals.get("completion_tokens")
    usage_out["total_tokens"] = totals.get("total_tokens")
    completion = totals.get("completion_tokens") or 0
    seconds = perf_counter() - generation_start
    usage_out["tokens_per_second"] = (
        round(completion / seconds, 2) if completion and seconds > 0 else None
    )


def _truncate_text(text: str, max_ocr_tokens: int) -> str:
    limit = max(1, max_ocr_tokens) * 4
    if len(text) <= limit:
        return text
    return text[:limit]


def _parse_and_validate(raw: str, contract: dict, kind: str) -> tuple[Any, list[str]]:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        return None, [f"la respuesta no es JSON válido ({exc.msg})"]
    return data, validate_payload(data, contract, kind)


def _validated_final(data: Any, contract: dict, kind: str, text: str) -> Any:
    final = _apply_label_anchors(_coerce_numbers(data, contract), text, contract)
    errors = validate_payload(final, contract, kind)
    if errors:
        raise ContractError("el contrato final no es válido: " + "; ".join(errors))
    return final


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
    return _numeric_value(normalize_numbers(match.group(1)))


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
        if isinstance(shape, int):
            if not float(value).is_integer():
                continue
            anchored[field] = int(value)
        else:
            anchored[field] = value
    return anchored


def _prune_schema(node: Any, wanted: set[str], prefix: str = "") -> Any:
    if not isinstance(node, dict):
        return node
    properties = node.get("properties")
    if not isinstance(properties, dict):
        return node
    kept: dict[str, Any] = {}
    for key, sub in properties.items():
        full = f"{prefix}.{key}" if prefix else key
        if full in wanted:
            kept[key] = sub
        elif any(path.startswith(full + ".") for path in wanted):
            kept[key] = _prune_schema(sub, wanted, full)
    result = {key: value for key, value in node.items() if key != "properties"}
    result["properties"] = kept
    required = result.get("required")
    if isinstance(required, list):
        result["required"] = [item for item in required if item in kept]
    return result


def subschema(contract: dict, paths: list[str], kind: str) -> dict:
    """Reduce el contrato a las rutas pedidas, conservando anidamiento y ``required``."""
    wanted = {path for path in paths if path}
    if not wanted:
        return contract
    if kind == "schema":
        return _prune_schema(contract, wanted)
    if kind == "example":
        # El validador de ejemplo es estricto con campos extra; podar el payload haría
        # que el LLM devolviera el contrato completo y fallara. Se pide el contrato entero.
        return contract
    raise ContractError(f"tipo de contrato desconocido: {kind!r}")
