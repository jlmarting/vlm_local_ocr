from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any

from .annotations import (
    SOURCE_ALIASES,
    ColumnSpec,
    FieldHint,
    ItemHint,
    field_map,
    item_hints,
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


@dataclass(frozen=True)
class ItemExtraction:
    """Resultado de extraer un array de líneas repetidas."""

    items: list[dict] | None
    candidates: int
    parsed: int


_QUANTITY_RE = re.compile(r"^(\d+)\s+(.+)$")
_MERGED_ITEM_RE = re.compile(r"^\d+\s+.+\s+\d+[.,]\d{2}$")


def _has_prefix(text: str, labels: tuple[str, ...]) -> bool:
    normalized = normalize_label(text)
    for label in labels:
        wanted = normalize_label(label)
        if wanted and (normalized == wanted or normalized.startswith(f"{wanted} ")):
            return True
    return False


def _text_cells(row: list[LayoutBlock]) -> list[LayoutBlock]:
    return [
        block
        for block in row
        if block.text.strip() and parse_number(block.text) is None
    ]


def _right_number(row: list[LayoutBlock], text_cells: list[LayoutBlock]) -> LayoutBlock | None:
    numbers = [block for block in row if parse_number(block.text) is not None]
    if not numbers or not text_cells:
        return None
    price = max(numbers, key=lambda block: block.box[0])
    left_edge = max(block.box[2] for block in text_cells)
    return price if price.box[0] >= left_edge - 2 else None


def _item_values(
    hint: ItemHint, text: str, price: float | None, quantity: int | None
) -> dict:
    values: dict[str, Any] = {}
    for prop, role in hint.columns.items():
        if role == "text":
            values[prop] = text
        elif role == "quantity":
            values[prop] = quantity
        elif role == "number_right":
            values[prop] = price
        elif role == "observation":
            values[prop] = None
    return values


def _coerce_column(text: str, kind: str) -> Any:
    if not text:
        return None
    if kind in ("number", "integer"):
        number = parse_number(text)
        if number is None:
            return None
        if kind == "integer":
            return int(number) if float(number).is_integer() else None
        return number
    return text


def extract_columns(blocks: list[LayoutBlock], hint: ItemHint) -> ItemExtraction:
    """Extrae una lista por columnas libres (x0/x1 relativos a la región)."""
    rows = group_rows(_expand_piped([block for block in blocks if block.text.strip()]))
    start_index: int | None = None
    for index, row in enumerate(rows):
        if any(
            _has_prefix(block.text, hint.start_labels)
            for block in _text_cells(row)
        ):
            start_index = index + 1
            break
    if start_index is None:
        return ItemExtraction(None, 0, 0)

    data_rows: list[list[LayoutBlock]] = []
    for row in rows[start_index:]:
        if any(
            _has_prefix(block.text, hint.stop_labels)
            for block in _text_cells(row)
        ):
            break
        if any(block.text.strip() for block in row):
            data_rows.append(row)
    if not data_rows:
        return ItemExtraction(None, 0, 0)

    region = [
        block
        for row in data_rows
        for block in row
        if block.box[2] > block.box[0]
    ]
    if not region:
        return ItemExtraction(None, 0, 0)
    x0 = min(block.box[0] for block in region)
    x1 = max(block.box[2] for block in region)
    width = x1 - x0
    if width <= 0:
        return ItemExtraction(None, 0, 0)

    columns = [
        (prop, spec)
        for prop, spec in hint.columns.items()
        if isinstance(spec, ColumnSpec)
    ]
    items: list[dict] = []
    candidates = 0
    parsed = 0
    for row in data_rows:
        cells = [
            block
            for block in row
            if block.text.strip() and block.box[2] > block.box[0]
        ]
        if not cells:
            continue
        candidates += 1
        values: dict[str, Any] = {}
        for prop, spec in columns:
            picked = [
                block
                for block in cells
                if spec.x0
                <= ((block.box[0] + block.box[2]) / 2 - x0) / width
                <= spec.x1
            ]
            picked.sort(key=lambda block: block.box[0])
            text = " ".join(block.text.strip() for block in picked).strip()
            values[prop] = _coerce_column(text, spec.type)
        if any(value is not None for value in values.values()):
            parsed += 1
        items.append(values)

    if candidates == 0 or parsed / candidates < 0.75:
        return ItemExtraction(None, candidates, parsed)
    return ItemExtraction(items, candidates, parsed)


def extract_items(blocks: list[LayoutBlock], hint: ItemHint) -> ItemExtraction:
    """Extrae un array de líneas repetidas: item + observaciones + stop."""
    if hint.mode == "columns":
        return extract_columns(blocks, hint)
    rows = group_rows(_expand_piped([block for block in blocks if block.text.strip()]))
    quantity_declared = "quantity" in hint.columns.values()
    start = 0

    def item_like(row: list[LayoutBlock]) -> bool:
        text_cells = _text_cells(row)
        if not text_cells:
            return False
        if any(_has_prefix(block.text, hint.stop_labels) for block in text_cells):
            return False
        if _right_number(row, text_cells) is not None:
            return True
        if quantity_declared:
            text = " ".join(block.text.strip() for block in text_cells)
            return bool(_QUANTITY_RE.match(text))
        return False

    if hint.start_labels:
        found = None
        for index, row in enumerate(rows):
            if any(_has_prefix(block.text, hint.start_labels) for block in _text_cells(row)):
                found = index
                break
        if found is None:
            return ItemExtraction(None, 0, 0)
        start = found + 1
    else:
        found = next((index for index, row in enumerate(rows) if item_like(row)), None)
        if found is None:
            return ItemExtraction(None, 0, 0)
        start = found

    observation_prop = next(
        (prop for prop, role in hint.columns.items() if role == "observation"), None
    )
    items: list[dict] = []
    candidates = 0
    parsed = 0

    for row in rows[start:]:
        text_cells = _text_cells(row)
        if not text_cells:
            continue
        if any(_has_prefix(block.text, hint.stop_labels) for block in text_cells):
            break

        price_cell = _right_number(row, text_cells)
        if price_cell is not None:
            left = [block for block in text_cells if block.box[2] <= price_cell.box[0] + 2]
            text = " ".join(block.text.strip() for block in left).strip()
            if not text:
                continue
            quantity = None
            product = text
            if quantity_declared:
                match = _QUANTITY_RE.match(text)
                if match:
                    quantity = int(match.group(1))
                    product = match.group(2).strip()
            candidates += 1
            if not product:
                continue
            items.append(
                _item_values(hint, product, parse_number(price_cell.text), quantity)
            )
            parsed += 1
            continue

        text = " ".join(block.text.strip() for block in text_cells).strip()
        if not text:
            continue
        if _MERGED_ITEM_RE.match(text):
            return ItemExtraction(None, candidates, parsed)
        quantity = None
        product = text
        if quantity_declared:
            match = _QUANTITY_RE.match(text)
            if match:
                quantity = int(match.group(1))
                product = match.group(2).strip()
        if quantity_declared and quantity is not None:
            candidates += 1
            if not product:
                continue
            items.append(_item_values(hint, product, None, quantity))
            parsed += 1
            continue
        if observation_prop is None or not items:
            return ItemExtraction(None, candidates, parsed)
        previous = items[-1]
        current = previous.get(observation_prop)
        previous[observation_prop] = f"{current} \n{text}" if current else text

    if candidates == 0 or parsed / candidates < 0.75:
        return ItemExtraction(None, candidates, parsed)
    return ItemExtraction(items, candidates, parsed)


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

    for hint in item_hints(schema):
        result = extract_items(blocks, hint)
        if result.items is not None:
            _set(data, hint.path, result.items)
            matched.append(hint.path)
            unmatched.discard(hint.path)
            sources[hint.path] = SourceCell(label="items")
        else:
            ambiguous.add(hint.path)
            unmatched.discard(hint.path)

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
