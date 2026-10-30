from __future__ import annotations

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
