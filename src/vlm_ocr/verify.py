from __future__ import annotations

import re
import unicodedata
from typing import Any

from .annotations import field_map
from .extract import parse_number

MAX_MESSAGE_VALUE = 60
_MIN_TEXT_CHARS = 2
_ISO_DATE_RE = re.compile(r"^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})$")
_DAY_FIRST_RE = re.compile(r"^(\d{1,2})[-/.](\d{1,2})[-/.](\d{2,4})$")
_TIME_RE = re.compile(r"^(\d{1,2}):(\d{2})(?::\d{2})?$")
_TEXT_DATE_RE = re.compile(
    r"\b(?:\d{4}[-/.]\d{1,2}[-/.]\d{1,2}|\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4})\b"
)


def normalize(text: str) -> str:
    """Minúsculas, sin acentos ni puntuación y con espacios colapsados."""
    decomposed = unicodedata.normalize("NFKD", text)
    plain = "".join(char for char in decomposed if not unicodedata.combining(char))
    plain = re.sub(r"[^0-9a-z]+", " ", plain.lower())
    return re.sub(r"\s+", " ", plain).strip()


def _year(value: int) -> int:
    return value + 2000 if value < 100 else value


def _date_candidates(value: str) -> set[tuple[int, int, int]]:
    """Fechas posibles del valor; con día/mes ambiguos, ambas orientaciones."""
    text = value.strip()
    match = _ISO_DATE_RE.match(text)
    if match:
        candidate = (int(match.group(1)), int(match.group(2)), int(match.group(3)))
        return {candidate} if _valid_date(candidate) else set()
    match = _DAY_FIRST_RE.match(text)
    if match:
        first, second, year = int(match.group(1)), int(match.group(2)), _year(int(match.group(3)))
        options = {(year, first, second), (year, second, first)}
        return {option for option in options if _valid_date(option)}
    return set()


def _valid_date(candidate: tuple[int, int, int]) -> bool:
    year, month, day = candidate
    return 1 <= month <= 12 and 1 <= day <= 31 and 1900 <= year <= 2999


def _dates_in(text: str) -> set[tuple[int, int, int]]:
    dates: set[tuple[int, int, int]] = set()
    for token in _TEXT_DATE_RE.findall(text):
        dates |= _date_candidates(token)
    return dates


def _time_candidates(value: str) -> set[str]:
    match = _TIME_RE.match(value.strip())
    if not match:
        return set()
    hour, minute = int(match.group(1)), int(match.group(2))
    return {f"{hour:02d}{minute:02d}", f"{hour}{minute:02d}"}


def _digits(text: str) -> str:
    return re.sub(r"\D", "", text)


def _short(value: str) -> str:
    return value if len(value) <= MAX_MESSAGE_VALUE else value[: MAX_MESSAGE_VALUE - 1] + "…"


def _walk(data: Any, path: str = ""):
    if isinstance(data, dict):
        for key, value in data.items():
            yield from _walk(value, f"{path}.{key}" if path else key)
        return
    if isinstance(data, list):
        for index, item in enumerate(data):
            yield from _walk(item, f"{path}[{index}]")
        return
    yield path, data


def _numbers_in(text: str) -> set[float]:
    numbers: set[float] = set()
    for token in re.findall(r"-?\d[\d.,]*", text):
        value = parse_number(token.rstrip(".,"))
        if value is not None:
            numbers.add(round(value, 2))
    return numbers


def literal_errors(data: Any, text: str) -> list[dict]:
    """Valores del resultado que no aparecen literalmente en el texto."""
    numbers = _numbers_in(text)
    plain = normalize(text)
    dates = _dates_in(text)
    digits = _digits(text)
    errors: list[dict] = []
    for path, value in _walk(data):
        if isinstance(value, bool) or value is None:
            continue
        if isinstance(value, int | float):
            if round(float(value), 2) not in numbers:
                errors.append(
                    {
                        "kind": "literal",
                        "field": path,
                        "message": f"el valor {value} no aparece en el texto",
                    }
                )
            continue
        if not isinstance(value, str):
            continue
        stripped = value.strip()
        if not stripped:
            continue

        candidates = _date_candidates(stripped)
        if candidates:
            if not candidates & dates:
                errors.append(
                    {
                        "kind": "literal",
                        "field": path,
                        "message": f"la fecha {_short(stripped)} no aparece en el texto",
                    }
                )
            continue

        times = _time_candidates(stripped)
        if times:
            if not any(candidate in digits for candidate in times):
                errors.append(
                    {
                        "kind": "literal",
                        "field": path,
                        "message": f"la hora {_short(stripped)} no aparece en el texto",
                    }
                )
            continue

        normalized = normalize(stripped)
        if len(normalized.replace(" ", "")) < _MIN_TEXT_CHARS:
            continue
        if normalized not in plain:
            errors.append(
                {
                    "kind": "literal",
                    "field": path,
                    "message": f"el valor «{_short(stripped)}» no aparece en el texto",
                }
            )
    return errors


def field_coverage(data: Any, contract: dict, kind: str) -> tuple[int, int]:
    """(resueltos, total) sobre los campos de primer nivel del contrato."""
    if kind == "schema":
        paths = [hint.path for hint in field_map(contract)]
    elif kind == "example":
        paths = list(contract)
    else:
        return (0, 0)
    filled = sum(1 for path in paths if _get(data, path) is not None)
    return (filled, len(paths))


def _get(data: Any, dotted: str) -> Any:
    current = data
    for key in dotted.split("."):
        if not isinstance(current, dict) or key not in current:
            return None
        current = current[key]
    return current
