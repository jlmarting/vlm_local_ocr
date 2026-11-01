from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from .annotations import item_hints, leaf_paths_for, normalize_label
from .extract import Assignment, detect_columns, parse_number
from .layout import group_rows
from .templates import FieldMap, ItemMap, normalize_value
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


def _is_array_node(node: Any) -> bool:
    declared = node.get("type") if isinstance(node, dict) else None
    return declared == "array" or (
        isinstance(declared, list) and "array" in declared
    )


def _schema_arrays(schema: Any, path: str = ""):
    if not isinstance(schema, dict):
        return
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        return
    for key, sub in properties.items():
        full = f"{path}.{key}" if path else key
        if _is_array_node(sub):
            yield full
        else:
            yield from _schema_arrays(sub, full)


def _example_arrays(example: Any, path: str = ""):
    if isinstance(example, dict):
        for key, sub in example.items():
            full = f"{path}.{key}" if path else key
            if isinstance(sub, list):
                yield full
            else:
                yield from _example_arrays(sub, full)


def _array_paths(contract: dict, kind: str) -> list[str]:
    if kind == "schema":
        return list(_schema_arrays(contract))
    if kind == "example":
        return list(_example_arrays(contract))
    return []


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


def _match_text(value: str, cell: LayoutBlock) -> bool:
    return _value_contains(value, cell.text) or normalize_value(value) == normalize_value(
        cell.text
    )


def _infer_item_map(
    items: list[dict], blocks: list[LayoutBlock]
) -> ItemMap | None:
    rows = group_rows([block for block in blocks if block.text.strip()])
    cursor = 0
    matched: list[tuple[int, dict, LayoutBlock, LayoutBlock | None]] = []

    for item in items:
        strings = [value for value in item.values() if isinstance(value, str) and value]
        numbers = [
            value
            for value in item.values()
            if isinstance(value, int | float) and not isinstance(value, bool)
        ]
        found = None
        for index in range(cursor, len(rows)):
            row = rows[index]
            text_cells = _text_cells(row)
            if not text_cells:
                continue
            product_cell = next(
                (
                    cell
                    for cell in text_cells
                    if any(_match_text(value, cell) for value in strings)
                ),
                None,
            )
            if product_cell is None:
                continue
            price_cell = _right_number(row, text_cells)
            quantity_match = re.match(r"^(\d+)\s+", product_cell.text)
            quantity = int(quantity_match.group(1)) if quantity_match else None
            if price_cell is not None:
                if not any(_value_matches(value, price_cell.text) for value in numbers):
                    continue
            else:
                possible_prices = [
                    value
                    for value in numbers
                    if not (
                        quantity is not None
                        and isinstance(value, int)
                        and not isinstance(value, bool)
                        and value == quantity
                    )
                ]
                if possible_prices:
                    continue
            found = (index, item, product_cell, price_cell)
            break
        if found is None:
            return None
        matched.append(found)
        cursor = found[0] + 1

    first_with_price = next((entry for entry in matched if entry[3] is not None), None)
    if first_with_price is None:
        return None
    _, first_item, first_product, first_price = first_with_price
    assert first_price is not None

    product_prop = next(
        (
            prop
            for prop, value in first_item.items()
            if isinstance(value, str)
            and _match_text(value, first_product)
            and not any(_match_text(value, cell) for cell in _text_cells([]))
        ),
        None,
    )
    if product_prop is None:
        product_prop = next(
            (
                prop
                for prop, value in first_item.items()
                if isinstance(value, str) and _match_text(value, first_product)
            ),
            None,
        )
    price_prop = next(
        (
            prop
            for prop, value in first_item.items()
            if isinstance(value, int | float)
            and not isinstance(value, bool)
            and _value_matches(value, first_price.text)
        ),
        None,
    )
    if product_prop is None or price_prop is None:
        return None

    quantity_prop = None
    quantity_match = re.match(r"^(\d+)\s+", first_product.text)
    if quantity_match:
        wanted = int(quantity_match.group(1))
        quantity_prop = next(
            (
                prop
                for prop, value in first_item.items()
                if isinstance(value, int)
                and not isinstance(value, bool)
                and value == wanted
            ),
            None,
        )

    roles = {product_prop: "text", price_prop: "number_right"}
    if quantity_prop is not None and quantity_prop != price_prop:
        roles[quantity_prop] = "quantity"
    observation_prop = next(
        (
            prop
            for prop, value in first_item.items()
            if prop not in roles and (value is None or isinstance(value, str))
        ),
        None,
    )
    if observation_prop is not None:
        roles[observation_prop] = "observation"

    last_row = matched[-1][0]
    stop_labels: tuple[str, ...] = ()
    for row in rows[last_row + 1 :]:
        text_cells = _text_cells(row)
        if not text_cells or _right_number(row, text_cells) is None:
            continue
        label = normalize_label(text_cells[0].text)
        if label:
            stop_labels = (label.split()[0],)
        break

    return ItemMap(columns=roles, stop_labels=stop_labels, start_labels=())


def learn_items(
    data: dict,
    blocks: list[LayoutBlock],
    contract: dict,
    kind: str,
    assignment: Assignment | None = None,
) -> tuple[dict[str, ItemMap], list[str]]:
    """Aprende el mapa de items de una extracción buena; ``unlocated`` bloquea."""
    hints = {hint.path: hint for hint in item_hints(contract)} if kind == "schema" else {}
    learned: dict[str, ItemMap] = {}
    unlocated: list[str] = []
    for path in _array_paths(contract, kind):
        hint = hints.get(path)
        if hint is not None:
            learned[path] = ItemMap(
                columns=dict(hint.columns),
                stop_labels=hint.stop_labels,
                start_labels=hint.start_labels,
            )
            continue
        items = get_path(data, path)
        if not isinstance(items, list) or not items:
            continue
        inferred = _infer_item_map(items, blocks)
        if inferred is None:
            unlocated.append(path)
        else:
            learned[path] = inferred
    return learned, sorted(unlocated)


def learn_map(
    data: dict,
    blocks: list[LayoutBlock],
    contract: dict,
    kind: str,
    assignment: Assignment | None = None,
) -> tuple[dict[str, FieldMap], list[str], list[str]]:
    """Aprende el mapa de una extracción buena: etiquetas + columnas, sin valores."""
    arrays = set(_array_paths(contract, kind))
    leaves = [path for path in leaf_paths_for(contract, kind) if path not in arrays]
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
