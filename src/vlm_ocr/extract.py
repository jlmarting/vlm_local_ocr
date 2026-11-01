from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any

from .annotations import (
    SOURCE_ALIASES,
    FieldHint,
    field_map,
    leaf_paths,
    normalize_label,
)
from .layout import group_rows
from .types import LayoutBlock

THOUSANDS_RE = re.compile(r"^-?\d{1,3}(?:\.\d{3})+$")


@dataclass(frozen=True)
class SourceCell:
    """Etiqueta y columna con las que se resolvió un campo."""

    label: str
    source: str | None = None


@dataclass
class Assignment:
    data: dict
    matched: list[str] = field(default_factory=list)
    unmatched: list[str] = field(default_factory=list)
    pending: list[str] = field(default_factory=list)
    sources: dict[str, SourceCell] = field(default_factory=dict)


_CURRENCY_RE = re.compile(
    r"[$€£¥]|\b(?:EUR|USD|GBP|MXN|ARS|CLP|COP|JPY|KRW|SAR|AED)\b", re.IGNORECASE
)


def parse_number(raw: str) -> float | None:
    """Número en formato español (``1.234,56``) o simple; admite moneda."""
    text = _CURRENCY_RE.sub("", raw).strip().replace(" ", "")
    if not text:
        return None
    if "," in text:
        text = text.replace(".", "").replace(",", ".")
    elif THOUSANDS_RE.fullmatch(text):
        text = text.replace(".", "")
    try:
        return float(text)
    except ValueError:
        return None


def _center(block: LayoutBlock) -> float:
    return (block.box[0] + block.box[2]) / 2


def _overlap(block: LayoutBlock, span: tuple[float, float]) -> float:
    return max(0.0, min(block.box[2], span[1]) - max(block.box[0], span[0]))


def _set(data: dict, path: str, value: Any) -> None:
    *parents, leaf = path.split(".")
    current = data
    for parent in parents:
        current = current.setdefault(parent, {})
    current[leaf] = value


def detect_columns(row: list[LayoutBlock]) -> dict[str, tuple[float, float]] | None:
    """Columnas de una fila de cabecera, por sinónimos de ``x-source``."""
    columns: dict[str, tuple[float, float]] = {}
    for block in row:
        source = SOURCE_ALIASES.get(normalize_label(block.text))
        if source is None:
            continue
        columns.setdefault(source, (block.box[0], block.box[2]))
    return columns if len(columns) >= 2 else None


def _detect_header(row: list[LayoutBlock]) -> dict[str, tuple[float, float]] | None:
    return detect_columns(row)


def _column_for(
    cell: LayoutBlock, columns: dict[str, tuple[float, float]] | None
) -> str | None:
    if not columns:
        return None
    best = max(columns.items(), key=lambda item: _overlap(cell, item[1]), default=None)
    if best is None or _overlap(cell, best[1]) <= 0:
        return None
    return best[0]


def _value_cell(
    hint: FieldHint,
    candidates: list[LayoutBlock],
    columns: dict[str, tuple[float, float]] | None,
    label_position: float = 0.0,
) -> LayoutBlock | None:
    numbers = [block for block in candidates if parse_number(block.text) is not None]
    geometric = columns is not None and any(
        block.box[2] > block.box[0] for block in candidates
    )
    if hint.source and columns and hint.source in columns:
        span = columns[hint.source]
        best = max(candidates, key=lambda block: _overlap(block, span), default=None)
        if best is not None and _overlap(best, span) > 0:
            return best
        if geometric:
            return None
    if hint.source in ("base", "porcentaje", "cuota") and len(numbers) >= 3:
        return numbers[{"base": 0, "porcentaje": 1, "cuota": 2}[hint.source]]
    if hint.source:
        return numbers[0] if len(numbers) == 1 else None
    if len(candidates) == 1:
        return candidates[0]
    right = [block for block in numbers if _center(block) >= label_position - 2]
    if right:
        return min(right, key=lambda block: _center(block) - label_position)
    return None


def _coerce(hint: FieldHint, block: LayoutBlock, label: str) -> Any:
    number = parse_number(block.text)
    if hint.kind == "string":
        if hint.join_label is True:
            return f"{label} {block.text}".strip()
        if hint.join_label is False:
            return block.text
        if number is not None and any(char.isalpha() for char in label):
            return f"{label} {block.text}".strip()
        return block.text
    if hint.kind in ("integer", "number"):
        return number
    return number if number is not None else block.text


def _expand_piped(blocks: list[LayoutBlock]) -> list[LayoutBlock]:
    """Da geometría sintética a bloques sin caja, separando celdas unidas con ``" | "``."""
    expanded: list[LayoutBlock] = []
    for index, block in enumerate(blocks):
        if block.box != (0.0, 0.0, 0.0, 0.0):
            expanded.append(block)
            continue
        parts = block.text.split(" | ") if " | " in block.text else [block.text]
        for column, part in enumerate(parts):
            x0 = column * 100.0
            expanded.append(
                LayoutBlock(
                    page=block.page,
                    text=part.strip(),
                    confidence=block.confidence,
                    box=(x0, index * 20.0, x0 + 90.0, index * 20.0 + 10.0),
                )
            )
    return expanded


def _closest_label(label: str, known: list[str]) -> str:
    """Etiqueta conocida más parecida; tolera erratas del OCR si la ganadora es clara."""
    if label in known or not label:
        return label
    scores = sorted(
        ((SequenceMatcher(None, label, candidate).ratio(), candidate) for candidate in known),
        reverse=True,
    )
    if not scores:
        return label
    best_score, best = scores[0]
    second = scores[1][0] if len(scores) > 1 else 0.0
    if best_score >= 0.9 and second < best_score - 0.03:
        return best
    return label


def _expanded(span: tuple[float, float]) -> tuple[float, float]:
    padding = 0.1 * (span[1] - span[0]) + 4.0
    return span[0] - padding, span[1] + padding


def _cell_under(cells: list[LayoutBlock], span: tuple[float, float]) -> LayoutBlock | None:
    """Único número bajo una etiqueta; si hay varios (bloque de columnas), no se asigna."""
    low, high = _expanded(span)
    inside = [
        cell
        for cell in cells
        if parse_number(cell.text) is not None and low <= _center(cell) <= high
    ]
    return inside[0] if len(inside) == 1 else None


def assign(blocks: list[LayoutBlock], schema: dict) -> Assignment:
    """Asignación determinista: empareja etiquetas del documento con campos del contrato."""
    hints = field_map(schema)
    by_label: dict[str, list[FieldHint]] = {}
    for hint in hints:
        for label in hint.labels:
            by_label.setdefault(normalize_label(label), []).append(hint)
    known = list(by_label)

    data: dict = {}
    leaves = leaf_paths(schema)
    for path in leaves:
        _set(data, path, None)
    matched: list[str] = []
    ambiguous: set[str] = set()
    unmatched: set[str] = set(leaves)
    columns: dict[str, tuple[float, float]] | None = None
    sources: dict[str, SourceCell] = {}
    pending: list[tuple[FieldHint, tuple[float, float], int, str]] = []

    def take(hint: FieldHint, cell: LayoutBlock, label: str) -> bool:
        if hint.path in matched:
            return True
        if parse_number(cell.text) is None and hint.kind != "string":
            return False
        _set(data, hint.path, _coerce(hint, cell, label))
        matched.append(hint.path)
        unmatched.discard(hint.path)
        sources[hint.path] = SourceCell(
            label=label,
            source=hint.source if hint.source and columns and hint.source in columns else _column_for(cell, columns),
        )
        return True

    rows = group_rows(_expand_piped([block for block in blocks if block.text.strip()]))
    for index, row in enumerate(rows):
        header = _detect_header(row)
        if header is not None:
            columns = header

        for block in row:
            label = normalize_label(block.text)
            for hint in by_label.get(_closest_label(label, known), []):
                others = [item for item in row if item is not block]
                cell = _value_cell(hint, others, columns, block.box[2])
                if cell is not None:
                    if not take(hint, cell, block.text):
                        ambiguous.add(hint.path)
                        unmatched.discard(hint.path)
                elif columns is None and hint.source and len(
                    [item for item in others if parse_number(item.text) is not None]
                ) > 1:
                    ambiguous.add(hint.path)
                    unmatched.discard(hint.path)

        numbers = [block for block in row if parse_number(block.text) is not None]
        remaining = []
        for hint, span, origin, label in pending:
            wide = span[1] - span[0] > 100.0
            window = 20 if wide else 2
            cell = _cell_under(numbers, span) if index - origin <= window else None
            if cell is not None and take(hint, cell, label):
                continue
            remaining.append((hint, span, origin, label))
        pending = remaining

        for block in row:
            label = normalize_label(block.text)
            for hint in by_label.get(_closest_label(label, known), []):
                if hint.path in matched or hint.path in {item[0].path for item in pending}:
                    continue
                span = (block.box[0], block.box[2])
                if _cell_under(
                    [item for item in row if parse_number(item.text) is not None], span
                ) is not None:
                    continue
                pending.append((hint, span, index, block.text))

    return Assignment(
        data=data,
        matched=matched,
        unmatched=sorted(unmatched),
        pending=sorted(ambiguous - set(matched)),
        sources=sources,
    )


def merge(deterministic: Any, fallback: Any) -> Any:
    """Fusiona resultados: lo determinista gana; el fallback solo rellena huecos."""
    if isinstance(deterministic, dict) and isinstance(fallback, dict):
        merged = dict(fallback)
        for key, value in deterministic.items():
            merged[key] = merge(value, fallback.get(key))
        return merged
    return fallback if deterministic is None else deterministic
