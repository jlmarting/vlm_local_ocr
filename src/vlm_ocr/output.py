from __future__ import annotations

import json
from typing import Any

from .types import LayoutBlock


def to_markdown(blocks: list[LayoutBlock]) -> str:
    """Renderiza los bloques como Markdown, separando páginas."""
    if not blocks:
        return ""

    pages: dict[int, list[str]] = {}
    for block in blocks:
        pages.setdefault(block.page, []).append(block.text)

    return "\n\n---\n\n".join(
        "\n".join(lines) for _, lines in sorted(pages.items())
    )


def to_json_payload(data: Any, blocks: list[LayoutBlock] | None = None) -> str:
    """Serializa el contrato; con bloques, lo envuelve junto al layout."""
    if blocks is None:
        payload: Any = data
    else:
        payload = {
            "data": data,
            "layout": [
                {"page": block.page, "text": block.text, "box": list(block.box)}
                for block in blocks
            ],
        }
    return json.dumps(payload, ensure_ascii=False, indent=2)

