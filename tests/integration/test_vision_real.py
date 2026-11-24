from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image, ImageDraw, ImageFont

from vlm_ocr import catalog, cli

MODELS = Path(__file__).resolve().parents[2] / "models"
MODEL = MODELS / "LFM3-VL-2B-Q4_K_M.gguf"
MMPROJ = MODELS / "mmproj-LFM3-VL-2B-Q8_0.gguf"
FONT = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not MODEL.exists(), reason=f"falta el modelo {MODEL.name}"),
    pytest.mark.skipif(not MMPROJ.exists(), reason=f"falta el proyector {MMPROJ.name}"),
    pytest.mark.skipif(not FONT.exists(), reason=f"falta la fuente {FONT}"),
]


def _scan(path: Path) -> Path:
    image = Image.new("RGB", (800, 300), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype(str(FONT), 32)
    draw.text((40, 60), "Factura ACME S.L.", fill="black", font=font)
    draw.text((40, 120), "Total: 123,45 EUR", fill="black", font=font)
    draw.text((40, 180), "Fecha: 2026-11-24", fill="black", font=font)
    image.save(path)
    return path


def test_lfm3_vl_transcribes_a_scan(tmp_path: Path, capsys, monkeypatch) -> None:
    monkeypatch.setattr(catalog, "user_catalog_path", lambda: tmp_path / "nada.json")
    scan = _scan(tmp_path / "scan.png")

    code = cli.main(
        [str(scan), "--format", "md", "--vision", "--model", "lfm3-vl-2b"]
    )

    assert code == 0
    out = capsys.readouterr().out.lower()
    assert "acme" in out
    assert "123" in out
