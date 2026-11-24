from __future__ import annotations

import json
from pathlib import Path

import pytest

from vlm_ocr import catalog, cli
from vlm_ocr.types import PageInput

EXAMPLE = {"cliente": "ACME", "total": 1.5}


def gguf(**overrides) -> dict:
    entry = {
        "name": "Modelo de prueba",
        "kind": "gguf",
        "file": "m.gguf",
        "url": "https://example.com/m.gguf",
        "sha256": "a" * 64,
        "size_bytes": 10,
        "license": "MIT",
    }
    entry.update(overrides)
    return entry


def vision_entry(**overrides) -> dict:
    return gguf(
        vision=True,
        mmproj_file="mm.gguf",
        mmproj_url="https://example.com/mm.gguf",
        mmproj_sha256="b" * 64,
        mmproj_size_bytes=5,
        **overrides,
    )


class FakeRunner:
    load_time_ms = 1.0

    def complete(self, prompt, max_tokens):
        return "Línea A\nLínea B", None, "stop"

    def estimate_tokens(self, prompt) -> int:
        return 1


@pytest.fixture
def install(monkeypatch, tmp_path: Path):
    def _install(models: dict) -> Path:
        pack = tmp_path / "pack.json"
        pack.write_text(json.dumps({"version": 1, "models": models}), encoding="utf-8")
        monkeypatch.setattr(catalog, "packaged_catalog_path", lambda: pack)
        monkeypatch.setattr(catalog, "user_catalog_path", lambda: tmp_path / "nada.json")
        directory = tmp_path / "models"
        directory.mkdir(exist_ok=True)
        monkeypatch.setattr(catalog, "search_dirs", lambda: [directory])
        return directory

    return _install


def _contract(tmp_path: Path) -> Path:
    path = tmp_path / "contrato.json"
    path.write_text(json.dumps(EXAMPLE), encoding="utf-8")
    return path


def _raster_page(monkeypatch) -> None:
    monkeypatch.setattr(
        cli, "ingest", lambda path, dpi=200: [PageInput(0, None, b"png")]
    )


def _downloaded(models: Path, *files: str) -> None:
    for name in files:
        (models / name).write_bytes(b"")


def test_vision_without_model_errors(tmp_path: Path, capsys, monkeypatch) -> None:
    _raster_page(monkeypatch)

    code = cli.main([str(tmp_path / "doc.pdf"), "--vision"])

    assert code == 2
    assert "--vision necesita un modelo con visión" in capsys.readouterr().err


def test_vision_with_model_without_vision_errors(
    tmp_path: Path, capsys, monkeypatch, install
) -> None:
    models = install({"llama32-3b": gguf()})
    _downloaded(models, "m.gguf")
    _raster_page(monkeypatch)

    code = cli.main([str(tmp_path / "doc.pdf"), "--vision", "--model", "llama32-3b"])

    assert code == 2
    assert "no declara visión" in capsys.readouterr().err


def test_vision_with_prompt_errors(tmp_path: Path, capsys, monkeypatch, install) -> None:
    models = install({"v": vision_entry()})
    _downloaded(models, "m.gguf", "mm.gguf")

    code = cli.main([str(tmp_path / "doc.pdf"), "--vision", "--model", "v", "--prompt", "x"])

    assert code == 2
    assert "no se combina con --prompt" in capsys.readouterr().err


def test_vision_produces_contract_json_and_report(
    tmp_path: Path, capsys, monkeypatch, install
) -> None:
    models = install({"v": vision_entry()})
    _downloaded(models, "m.gguf", "mm.gguf")
    _raster_page(monkeypatch)
    monkeypatch.setattr(cli, "runner_for", lambda ref, n_ctx=4096: FakeRunner())
    captured: list[str] = []

    def fake_infer(text, *args, **kwargs):
        captured.append(text)
        return EXAMPLE

    monkeypatch.setattr(cli, "infer_contract", fake_infer)
    report_path = tmp_path / "report.json"

    code = cli.main(
        [
            str(tmp_path / "doc.pdf"),
            "--format", "json",
            "--contract", str(_contract(tmp_path)),
            "--vision",
            "--model", "v",
            "--metrics-out", str(report_path),
        ]
    )

    assert code == 0
    assert "Línea A" in captured[0]
    payload = json.loads(capsys.readouterr().out)
    assert payload == EXAMPLE
    report = json.loads(report_path.read_text())
    assert report["ocr"]["engine"] == "vision"
    assert report["vision"] == {"pages": 1, "time_ms": report["vision"]["time_ms"]}
    assert report["ocr"]["mean_confidence"] is None


def test_vision_markdown_output(tmp_path: Path, capsys, monkeypatch, install) -> None:
    models = install({"v": vision_entry()})
    _downloaded(models, "m.gguf", "mm.gguf")
    _raster_page(monkeypatch)
    monkeypatch.setattr(cli, "runner_for", lambda ref, n_ctx=4096: FakeRunner())

    code = cli.main(
        [str(tmp_path / "doc.pdf"), "--format", "md", "--vision", "--model", "v"]
    )

    assert code == 0
    assert "Línea A" in capsys.readouterr().out


def test_vision_with_no_llm_errors(tmp_path: Path, capsys, monkeypatch, install) -> None:
    models = install({"v": vision_entry()})
    _downloaded(models, "m.gguf", "mm.gguf")

    code = cli.main(
        [str(tmp_path / "doc.pdf"), "--vision", "--model", "v", "--no-llm"]
    )

    assert code == 2
    assert "--no-llm" in capsys.readouterr().err
