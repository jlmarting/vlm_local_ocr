from __future__ import annotations

from vlm_ocr.output import to_markdown
from vlm_ocr.types import LayoutBlock


def test_markdown_contains_text_and_page_separator() -> None:
    blocks = [
        LayoutBlock(0, "primera pagina", 1.0, (0, 0, 0, 0)),
        LayoutBlock(1, "segunda pagina", 1.0, (0, 0, 0, 0)),
    ]

    markdown = to_markdown(blocks)

    assert "primera pagina" in markdown
    assert "segunda pagina" in markdown
    assert "\n\n---\n\n" in markdown


def test_markdown_empty_returns_empty_string() -> None:
    assert to_markdown([]) == ""
