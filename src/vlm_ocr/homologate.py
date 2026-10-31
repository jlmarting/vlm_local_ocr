from __future__ import annotations

from datetime import datetime
from typing import Any

from .annotations import leaf_paths_for, normalize_label
from .extract import Assignment, detect_columns, parse_number
from .layout import group_rows
from .templates import FieldMap, normalize_value
from .types import LayoutBlock


def get_path(data: Any, path: str) -> Any:
    current = data
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def _overlap(cell: LayoutBlock, span: tuple[float, float]) -> float:
    return max(0.0, min(cell.box[2], span[1]) - max(cell.box[0], span[0]))


def _source_for(
    cell: LayoutBlock, columns: dict[str, tuple[float, float]] | None
) -> str | None:
    if not columns:
        return None
    best = max(columns.items(), key=lambda item: _overlap(cell, item[1]), default=None)
    if best is None or _overlap(cell, best[1]) <= 0:
        return None
    return best[0]


DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d", "%d.%m.%Y")


def _as_date(text: str):
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text.strip(), fmt).date()
        except ValueError:
            continue
    return None


def _value_matches(value: Any, text: str) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, int | float):
        parsed = parse_number(text)
        if parsed is None:
            return False
        return abs(parsed - float(value)) <= max(0.005, abs(float(value)) * 1e-6)
    if isinstance(value, str):
        if normalize_value(value) == normalize_value(text):
            return True
        left, right = _as_date(value), _as_date(text)
        return left is not None and left == right
    return False


def _value_contains(value: str, text: str) -> bool:
    wanted = normalize_value(value)
    candidate = normalize_value(text)
    if not wanted or not candidate:
        return False
    return wanted in candidate or candidate in wanted


def _join_label(value: Any, label: str) -> bool:
    """¿El valor aprendido incluye la etiqueta además de la celda?"""
    if not isinstance(value, str):
        return False
    normalized_value = normalize_value(value)
    normalized_label = normalize_value(label)
    return (
        bool(normalized_label)
        and normalized_value != normalized_label
        and normalized_value.startswith(normalized_label)
    )


def _label_for(row: list[LayoutBlock], cell: LayoutBlock) -> LayoutBlock | None:
    candidates = [
        block
        for block in row
        if block is not cell
        and block.text.strip()
        and parse_number(block.text) is None
    ]
    if not candidates:
        return None
    left = [block for block in candidates if block.box[2] <= cell.box[0] + 1]
    if left:
        return max(left, key=lambda block: block.box[2])
    return min(candidates, key=lambda block: block.box[0])


def _locate(
    value: Any, rows: list[tuple[list[LayoutBlock], dict[str, tuple[float, float]] | None]]
) -> tuple[LayoutBlock, list[LayoutBlock], dict[str, tuple[float, float]] | None] | None:
    exact: list[
        tuple[LayoutBlock, list[LayoutBlock], dict[str, tuple[float, float]] | None]
    ] = []
    for row, columns in rows:
        for cell in row:
            if _value_matches(value, cell.text):
                exact.append((cell, row, columns))
    candidates = exact
    if not candidates and isinstance(value, str):
        loose: list[
            tuple[LayoutBlock, list[LayoutBlock], dict[str, tuple[float, float]] | None]
        ] = []
        for row, columns in rows:
            text_blocks = [
                block
                for block in row
                if block.text.strip() and parse_number(block.text) is None
            ]
            leftmost = (
                min(text_blocks, key=lambda block: block.box[0])
                if text_blocks
                else None
            )
            for cell in row:
                if not _value_contains(value, cell.text):
                    continue
                if cell is leftmost and any(
                    other is not cell and _value_contains(value, other.text)
                    for other in row
                ):
                    continue
                loose.append((cell, row, columns))
        candidates = loose
    return candidates[0] if len(candidates) == 1 else None


def learn_map(
    data: dict,
    blocks: list[LayoutBlock],
    contract: dict,
    kind: str,
    assignment: Assignment | None = None,
) -> tuple[dict[str, FieldMap], list[str], list[str]]:
    """Aprende el mapa de una extracción buena: etiquetas + columnas, sin valores."""
    leaves = leaf_paths_for(contract, kind)
    rows: list[
        tuple[list[LayoutBlock], dict[str, tuple[float, float]] | None]
    ] = []
    columns: dict[str, tuple[float, float]] | None = None
    for row in group_rows([block for block in blocks if block.text.strip()]):
        detected = detect_columns(row)
        if detected:
            columns = detected
        rows.append((row, columns))

    learned: dict[str, FieldMap] = {}
    absent: list[str] = []
    unlocated: list[str] = []

    for path in leaves:
        value = get_path(data, path)
        if value is None:
            absent.append(path)
            continue
        if assignment is not None and path in assignment.sources:
            source = assignment.sources[path]
            if source.label.strip():
                learned[path] = FieldMap(
                    labels=(source.label,),
                    source=source.source,
                    join_label=_join_label(value, source.label),
                )
                continue
        found = _locate(value, rows)
        if found is None:
            unlocated.append(path)
            continue
        cell, row, row_columns = found
        label = _label_for(row, cell)
        if label is None or not normalize_label(label.text):
            unlocated.append(path)
            continue
        learned[path] = FieldMap(
            labels=(label.text,),
            source=_source_for(cell, row_columns),
            join_label=_join_label(value, label.text),
        )

    return learned, sorted(absent), sorted(unlocated)
