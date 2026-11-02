from __future__ import annotations

import pytest

from vlm_ocr.serve_layout import normalize_blocks


def test_normalize_scales_native_blocks_and_keeps_ocr() -> None:
    blocks = [
        {"page": 0, "text": "nativo", "box": [10.0, 20.0, 110.0, 36.0]},
        {"page": 1, "text": "ocr", "box": [10.0, 20.0, 110.0, 36.0]},
    ]

    normalized = normalize_blocks(blocks, {0}, 200)

    assert normalized[0]["box"] == pytest.approx(
        [10.0 * 200 / 72, 20.0 * 200 / 72, 110.0 * 200 / 72, 36.0 * 200 / 72]
    )
    assert normalized[1]["box"] == [10.0, 20.0, 110.0, 36.0]


def test_normalize_does_not_mutate_the_input() -> None:
    blocks = [{"page": 0, "text": "nativo", "box": [10.0, 20.0, 110.0, 36.0]}]

    normalize_blocks(blocks, {0}, 144)

    assert blocks[0]["box"] == [10.0, 20.0, 110.0, 36.0]
