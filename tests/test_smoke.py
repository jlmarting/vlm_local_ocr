from vlm_ocr import __version__
from vlm_ocr.types import LayoutBlock, PageInput


def test_package_imports() -> None:
    assert __version__ == "0.1.0"


def test_page_input_holds_text() -> None:
    page = PageInput(0, "hola", None)
    assert page.text == "hola"
    assert page.image_png is None


def test_layout_block_box_is_tuple() -> None:
    block = LayoutBlock(0, "hola", 0.9, (0.0, 0.0, 10.0, 5.0))
    x0, y0, x1, y1 = block.box
    assert (x0, y0, x1, y1) == (0.0, 0.0, 10.0, 5.0)
