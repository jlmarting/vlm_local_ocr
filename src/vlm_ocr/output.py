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


def _layout(blocks: list[LayoutBlock]) -> list[dict]:
    return [
        {"page": block.page, "text": block.text, "box": list(block.box)}
        for block in blocks
    ]


def to_json_payload(data: Any, blocks: list[LayoutBlock] | None = None) -> str:
    """Serializa el contrato; con bloques, lo envuelve junto al layout."""
    if blocks is None:
        payload: Any = data
    else:
        payload = {"data": data, "layout": _layout(blocks)}
    return json.dumps(payload, ensure_ascii=False, indent=2)


def to_text_json(text: str, blocks: list[LayoutBlock] | None = None) -> str:
    """Serializa solo el texto extraído; con bloques, añade el layout."""
    payload: dict[str, Any] = {"text": text}
    if blocks is not None:
        payload["layout"] = _layout(blocks)
    return json.dumps(payload, ensure_ascii=False, indent=2)


def to_answer_json(text: str, answer: str) -> str:
    """Serializa texto y respuesta libre del LLM."""
    payload = {"text": text, "answer": answer}
    return json.dumps(payload, ensure_ascii=False, indent=2)

