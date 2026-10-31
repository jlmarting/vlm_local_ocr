from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image, ImageDraw, ImageFont
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

from vlm_ocr import cli
from vlm_ocr.extract import assign
from vlm_ocr.ingest import ingest
from vlm_ocr.layout import rows_text
from vlm_ocr.ocr import ocr_pages

FONT = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not FONT.exists(), reason=f"falta la fuente {FONT}"),
]

ROWS = [
    ("Concepto", "Unidades", "Importe", "Devengado", "A deducir"),
    ("SALARIO BASE", "30,00", "80,2297", "2.406,89", ""),
    ("ANTIGUEDAD (1,00 Unidad)", "30,00", "1,6463", "49,39", ""),
    ("KILOMETRAJE TRIBUTA+COTIZA", "", "", "12,00", ""),
    ("GTOS COMIDA EXENTOS NO PERNOCTA", "", "", "37,50", ""),
    ("RETENCION I.R.P.F.", "17,00", "2.610,2400", "", "443,74"),
    ("DESCUENTOS SEG. SOC.", "", "", "", "196,66"),
]
COLUMNS = [40, 380, 520, 680, 860]

SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "nomina": {
            "type": "object",
            "properties": {
                "devengos": {
                    "type": "object",
                    "properties": {
                        "salario_base": {
                            "type": ["number", "null"],
                            "x-labels": ["SALARIO BASE"],
                            "x-source": "devengado",
                        },
                        "antiguedad": {
                            "type": "object",
                            "properties": {
                                "unidades": {
                                    "type": ["number", "null"],
                                    "x-labels": ["ANTIGUEDAD"],
                                    "x-source": "unidades",
                                },
                                "importe": {
                                    "type": ["number", "null"],
                                    "x-labels": ["ANTIGUEDAD"],
                                    "x-source": "devengado",
                                },
                            },
                        },
                        "kilometraje_tributa": {
                            "type": ["number", "null"],
                            "x-labels": ["KILOMETRAJE TRIBUTA+COTIZA"],
                            "x-source": "devengado",
                        },
                    },
                },
                "deducciones": {
                    "type": "object",
                    "properties": {
                        "irpf": {
                            "type": "object",
                            "properties": {
                                "retencion": {
                                    "type": ["number", "null"],
                                    "x-labels": ["RETENCION I.R.P.F."],
                                    "x-source": "a_deducir",
                                }
                            },
                        },
                        "descuentos_seg_soc": {
                            "type": ["number", "null"],
                            "x-labels": ["DESCUENTOS SEG. SOC."],
                            "x-source": "a_deducir",
                        },
                    },
                },
            },
        }
    },
}


def _scan(path: Path) -> Path:
    """Imagen sintética con una tabla de nómina: hace de escaneo, sin datos reales."""
    height = 40 + 34 * len(ROWS)
    image = Image.new("RGB", (1000, height), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype(str(FONT), 20)
    for row_index, row in enumerate(ROWS):
        for column_index, text in enumerate(row):
            if text:
                draw.text(
                    (COLUMNS[column_index], 20 + row_index * 34),
                    text,
                    fill="black",
                    font=font,
                )
    image.save(path)
    return path


def test_ocr_scan_is_serialized_in_rows_and_resolved_without_llm(tmp_path: Path) -> None:
    image = _scan(tmp_path / "nomina.png")

    blocks = ocr_pages(ingest(image))
    text = rows_text(blocks)

    assert "SALARIO BASE | 30,00 | 80,2297 | 2.406,89" in text
    assert "RETENCION I.R.P.F. | 17,00 | 2.610,2400 | 443,74" in text

    assignment = assign(blocks, SCHEMA)

    devengos = assignment.data["nomina"]["devengos"]
    assert devengos["salario_base"] == 2406.89
    assert devengos["antiguedad"] == {"unidades": 30.0, "importe": 49.39}
    assert devengos["kilometraje_tributa"] == 12.0
    assert assignment.data["nomina"]["deducciones"]["irpf"]["retencion"] == 443.74
    assert assignment.data["nomina"]["deducciones"]["descuentos_seg_soc"] == 196.66
    assert assignment.pending == []


def test_cli_processes_the_scan_without_a_model(tmp_path: Path, capsys) -> None:
    image = _scan(tmp_path / "nomina.png")
    contract = tmp_path / "contrato.json"
    contract.write_text(json.dumps(SCHEMA), encoding="utf-8")
    argv = [
        str(image),
        "--format",
        "json",
        "--contract",
        str(contract),
        "--no-llm",
        "--metrics",
    ]

    code = cli.main(argv)

    assert code == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["nomina"]["devengos"]["salario_base"] == 2406.89
    report = json.loads(captured.err)
    assert report["extract"]["deterministic"] == 6
    assert report["extract"]["llm"] is False
    assert report["verify"]["errors"] == []


def _scanned_pdf(path: Path, image_path: Path) -> Path:
    """PDF sin capa de texto: la página solo lleva la imagen, como un escaneo real."""
    document = canvas.Canvas(str(path), pagesize=A4)
    width, height = A4
    document.drawImage(
        ImageReader(str(image_path)),
        36,
        height - 436,
        width=width - 72,
        height=400,
        preserveAspectRatio=True,
    )
    document.showPage()
    document.save()
    return path


def test_pdf_without_text_layer_is_rasterized_and_resolved_without_llm(
    tmp_path: Path, capsys
) -> None:
    image = _scan(tmp_path / "nomina.png")
    pdf = _scanned_pdf(tmp_path / "escaneo.pdf", image)
    contract = tmp_path / "contrato.json"
    contract.write_text(json.dumps(SCHEMA), encoding="utf-8")

    pages = ingest(pdf)
    assert pages[0].text is None
    assert pages[0].image_png is not None

    code = cli.main(
        [
            str(pdf),
            "--format",
            "json",
            "--contract",
            str(contract),
            "--no-llm",
            "--metrics",
        ]
    )

    assert code == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["nomina"]["devengos"]["salario_base"] == 2406.89
    assert payload["nomina"]["deducciones"]["irpf"]["retencion"] == 443.74
    report = json.loads(captured.err)
    assert report["ingest"]["native_pages"] == 0
    assert report["ingest"]["rasterized_pages"] == 1
    assert report["extract"]["deterministic"] == 6
    assert report["extract"]["llm"] is False
    assert report["verify"]["errors"] == []


def test_deskew_straightens_a_rotated_scan(tmp_path: Path) -> None:
    image = _scan(tmp_path / "nomina.png")
    rotated = Image.open(image).rotate(12, resample=Image.BICUBIC, expand=True, fillcolor="white")
    tilted = tmp_path / "rotada.png"
    rotated.save(tilted)

    blocks = ocr_pages(ingest(tilted))
    text = rows_text(blocks)

    assert "SALARIO BASE | 30,00 | 80,2297 | 2.406,89" in text
    assignment = assign(blocks, SCHEMA)
    assert assignment.data["nomina"]["devengos"]["salario_base"] == 2406.89
