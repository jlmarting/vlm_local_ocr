from __future__ import annotations

from itertools import pairwise
from pathlib import Path

import pypdfium2 as pdfium

from .types import LayoutBlock

SPACE_GAP_RATIO = 0.5
CELL_GAP = 8.0
ROW_OVERLAP = 0.5
ROW_TOLERANCE = 3.0


def _is_point(block: LayoutBlock) -> bool:
    return block.box == (0.0, 0.0, 0.0, 0.0)


def _vertical_overlap(a0: float, a1: float, b0: float, b1: float) -> bool:
    height_a, height_b = a1 - a0, b1 - b0
    if height_a <= 0 or height_b <= 0:
        return abs((a0 + a1) / 2 - (b0 + b1) / 2) <= ROW_TOLERANCE
    overlap = min(a1, b1) - max(a0, b0)
    if overlap > ROW_OVERLAP * min(height_a, height_b):
        return True
    center_gap = abs((a0 + a1) / 2 - (b0 + b1) / 2)
    return center_gap <= 0.6 * max(height_a, height_b)


def group_rows(blocks: list[LayoutBlock]) -> list[list[LayoutBlock]]:
    rows: list[list[LayoutBlock]] = []
    for block in sorted(blocks, key=lambda item: (item.box[1], item.box[0])):
        for row in rows:
            anchor = row[0]
            if _vertical_overlap(anchor.box[1], anchor.box[3], block.box[1], block.box[3]):
                row.append(block)
                break
        else:
            rows.append([block])
    for row in rows:
        row.sort(key=lambda item: item.box[0])
    rows.sort(key=lambda row: (min(item.box[1] for item in row), row[0].box[0]))
    return rows


def rows_text(blocks: list[LayoutBlock]) -> str:
    """Serializa bloques en filas: celdas de la misma línea unidas con ``" | "``."""
    by_page: dict[int, list[LayoutBlock]] = {}
    for block in blocks:
        if block.text.strip():
            by_page.setdefault(block.page, []).append(block)

    pages: list[str] = []
    for page in sorted(by_page):
        page_blocks = by_page[page]
        if all(_is_point(block) for block in page_blocks):
            pages.append("\n".join(block.text for block in page_blocks))
            continue
        rows = group_rows(page_blocks)
        lines = [
            " | ".join(block.text for block in row)
            for row in rows
            if any(char.isalnum() for block in row for char in block.text)
        ]
        pages.append("\n".join(lines))
    return "\n\n".join(pages)


def _char_lines(chars: list[tuple[float, float, float, float, str]]) -> list[list[tuple]]:
    lines: list[list[tuple]] = []
    for char in sorted(chars, key=lambda item: (item[0], item[2])):
        for line in lines:
            if _vertical_overlap(line[0][0], line[0][1], char[0], char[1]):
                line.append(char)
                break
        else:
            lines.append([char])
    return lines


def _cell(page: int, chars: list[tuple[float, float, float, float, str]]) -> LayoutBlock:
    widths = sorted(char[3] - char[2] for char in chars if char[3] > char[2])
    space_gap = max(1.0, SPACE_GAP_RATIO * widths[len(widths) // 2]) if widths else 1.0
    parts = [chars[0][4]]
    for previous, char in pairwise(chars):
        if (
            char[2] - previous[3] >= space_gap
            and previous[4].isalnum()
            and char[4].isalnum()
        ):
            parts.append(" ")
        parts.append(char[4])
    return LayoutBlock(
        page=page,
        text="".join(parts).strip(),
        confidence=1.0,
        box=(
            min(char[2] for char in chars),
            min(char[0] for char in chars),
            max(char[3] for char in chars),
            max(char[1] for char in chars),
        ),
    )


def _page_cells(page: int, chars: list[tuple[float, float, float, float, str]]) -> list[LayoutBlock]:
    if not chars:
        return []
    cells: list[LayoutBlock] = []
    for line in _char_lines(chars):
        line.sort(key=lambda item: item[2])
        current = [line[0]]
        for previous, char in pairwise(line):
            if char[2] - previous[3] >= CELL_GAP:
                cells.append(_cell(page, current))
                current = [char]
            else:
                current.append(char)
        cells.append(_cell(page, current))
    cells = _merge_punctuation(cells)
    cells.sort(key=lambda block: (block.box[1], block.box[0]))
    return cells


def _merge_punctuation(cells: list[LayoutBlock]) -> list[LayoutBlock]:
    """Una celda que solo tiene signos se pega a la anterior de su fila."""
    merged: list[LayoutBlock] = []
    for cell in cells:
        if merged and cell.text and not any(char.isalnum() for char in cell.text):
            previous = merged[-1]
            tiny = (cell.box[3] - cell.box[1]) < 0.5 * (previous.box[3] - previous.box[1])
            near = 0 <= cell.box[0] - previous.box[2] <= CELL_GAP
            if (
                tiny
                and near
                and _vertical_overlap(previous.box[1], previous.box[3], cell.box[1], cell.box[3])
            ):
                merged[-1] = LayoutBlock(
                    page=previous.page,
                    text=previous.text + cell.text,
                    confidence=previous.confidence,
                    box=(
                        min(previous.box[0], cell.box[0]),
                        min(previous.box[1], cell.box[1]),
                        max(previous.box[2], cell.box[2]),
                        max(previous.box[3], cell.box[3]),
                    ),
                )
                continue
        merged.append(cell)
    return merged


def native_blocks(path: Path | str) -> list[LayoutBlock]:
    """Celdas con caja real extraídas del texto nativo de un PDF (PDFium, por carácter)."""
    blocks: list[LayoutBlock] = []
    pdf = pdfium.PdfDocument(str(path))
    try:
        for index in range(len(pdf)):
            page = pdf[index]
            textpage = page.get_textpage()
            height = page.get_size()[1]
            chars: list[tuple[float, float, float, float, str]] = []
            for position in range(textpage.count_chars()):
                char = textpage.get_text_range(position, 1)
                if not char or char.isspace():
                    continue
                left, bottom, right, top = textpage.get_charbox(position)
                chars.append((height - top, height - bottom, left, right, char))
            blocks.extend(_page_cells(index, chars))
    finally:
        pdf.close()
    return blocks
