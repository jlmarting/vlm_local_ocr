from __future__ import annotations

from pathlib import Path

from vlm_ocr.layout import native_blocks, rows_text
from vlm_ocr.types import LayoutBlock


def _block(text: str, x0: float, y0: float, x1: float, y1: float, page: int = 0) -> LayoutBlock:
    return LayoutBlock(page, text, 1.0, (x0, y0, x1, y1))


def test_cells_on_the_same_row_are_joined_with_pipes() -> None:
    blocks = [
        _block("IMPORTE", 10.0, 10.0, 60.0, 20.0),
        _block("2.406,89", 200.0, 11.0, 250.0, 20.0),
    ]

    assert rows_text(blocks) == "IMPORTE | 2.406,89"


def test_single_cell_row_has_no_separator() -> None:
    blocks = [_block("GRUPO 3", 10.0, 10.0, 60.0, 20.0)]

    assert rows_text(blocks) == "GRUPO 3"


def test_unordered_blocks_are_sorted_by_row_then_column() -> None:
    blocks = [
        _block("2406.89", 200.0, 40.0, 250.0, 50.0),
        _block("SALARIO BASE", 10.0, 40.0, 90.0, 50.0),
        _block("ANTIGUEDAD", 10.0, 10.0, 90.0, 20.0),
    ]

    assert rows_text(blocks) == "ANTIGUEDAD\nSALARIO BASE | 2406.89"


def test_boxes_without_geometry_keep_their_order() -> None:
    blocks = [_block("primera", 0.0, 0.0, 0.0, 0.0), _block("segunda", 0.0, 0.0, 0.0, 0.0)]

    assert rows_text(blocks) == "primera\nsegunda"


def test_pages_are_separated_by_a_blank_line() -> None:
    blocks = [_block("uno", 10.0, 10.0, 50.0, 20.0, page=0), _block("dos", 10.0, 10.0, 50.0, 20.0, page=1)]

    assert rows_text(blocks) == "uno\n\ndos"


def _write_mini_pdf(path: Path, stream: bytes | None = None) -> None:
    if stream is None:
        stream = (
            b"BT /F1 12 Tf 20 160 Td (IMPORTE) Tj ET\n"
            b"BT /F1 12 Tf 200 160 Td (2406,89) Tj ET\n"
            b"BT /F1 12 Tf 20 130 Td (UNIDADES) Tj ET\n"
        )
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 200] "
            b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>"
        ),
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"endstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n" % (len(objects) + 1)
    out += b"0000000000 65535 f \n"
    for offset in offsets:
        out += b"%010d 00000 n \n" % offset
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1,
        xref,
    )
    path.write_bytes(bytes(out))


def test_native_blocks_extract_cells_with_boxes(tmp_path: Path) -> None:
    pdf = tmp_path / "mini.pdf"
    _write_mini_pdf(pdf)

    blocks = native_blocks(pdf)

    assert [block.text for block in blocks] == ["IMPORTE", "2406,89", "UNIDADES"]
    assert all(block.box != (0.0, 0.0, 0.0, 0.0) for block in blocks)
    assert rows_text(blocks) == "IMPORTE | 2406,89\nUNIDADES"


def test_native_blocks_return_empty_for_a_pdf_without_text(tmp_path: Path) -> None:
    pdf = tmp_path / "empty.pdf"
    _write_mini_pdf(pdf, stream=b"")

    assert native_blocks(pdf) == []


def test_native_blocks_from_bytes_matches_file(tmp_path: Path) -> None:
    pdf = tmp_path / "mini.pdf"
    _write_mini_pdf(pdf)

    assert native_blocks("-", data=pdf.read_bytes()) == native_blocks(pdf)
