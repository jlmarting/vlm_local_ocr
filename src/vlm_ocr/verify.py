from __future__ import annotations

import re
from typing import Any

from .extract import parse_number


def _walk(data: Any, path: str = ""):
    if isinstance(data, dict):
        for key, value in data.items():
            yield from _walk(value, f"{path}.{key}" if path else key)
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
    """Valores numéricos del resultado que no aparecen literalmente en el texto."""
    numbers = _numbers_in(text)
    errors: list[dict] = []
    for path, value in _walk(data):
        if isinstance(value, bool) or not isinstance(value, int | float):
            continue
        if round(float(value), 2) not in numbers:
            errors.append(
                {
                    "kind": "literal",
                    "field": path,
                    "message": f"el valor {value} no aparece en el texto",
                }
            )
    return errors
