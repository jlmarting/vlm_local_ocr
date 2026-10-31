from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from vlm_ocr.annotations import SOURCE_ALIASES, normalize_label
from vlm_ocr.extract import parse_number
from vlm_ocr.layout import group_rows, native_blocks, rows_text


def _slug(label: str) -> str:
    decomposed = unicodedata.normalize("NFKD", label)
    plain = "".join(char for char in decomposed if not unicodedata.combining(char))
    slug = re.sub(r"[^a-z0-9]+", "_", plain.lower()).strip("_")
    return slug or "campo"


def _columns(rows: list[list]) -> dict[str, tuple[float, float]]:
    for row in rows:
        found: dict[str, tuple[float, float]] = {}
        for block in row:
            source = SOURCE_ALIASES.get(normalize_label(block.text))
            if source is not None:
                found.setdefault(source, (block.box[0], block.box[2]))
        if len(found) >= 2:
            return found
    return {}


def _source_for(block, columns: dict[str, tuple[float, float]]) -> str | None:
    best = None
    best_overlap = 0.0
    for source, (x0, x1) in columns.items():
        overlap = max(0.0, min(block.box[2], x1) - max(block.box[0], x0))
        if overlap > best_overlap:
            best, best_overlap = source, overlap
    return best


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Borrador de contrato anotado (JSON Schema plano) a partir de un documento"
    )
    parser.add_argument("--doc", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    blocks = native_blocks(args.doc) if args.doc.suffix.lower() == ".pdf" else []
    rows = group_rows(blocks)
    columns = _columns(rows)

    properties: dict[str, dict] = {}
    for row in rows:
        if not row:
            continue
        label_block = min(row, key=lambda block: block.box[0])
        label = label_block.text.strip()
        if not label or any(char.isdigit() for char in label):
            continue
        others = [block for block in row if block is not label_block]
        numbers = [block for block in others if parse_number(block.text) is not None]
        if not numbers:
            continue
        value = numbers[0]
        source = _source_for(value, columns)
        key = _slug(label)
        while key in properties:
            key += "_2"
        node: dict = {"type": ["number", "null"], "x-labels": [label]}
        if source is not None:
            node["x-source"] = source
        properties[key] = node

    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": properties,
    }
    args.out.write_text(json.dumps(schema, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"borrador con {len(properties)} campos: {args.out}")
    print("Revisa nombres, anida según el contrato y ajusta x-source antes de usarlo.")
    print(rows_text(blocks)[:400])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
