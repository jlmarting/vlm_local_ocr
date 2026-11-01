from __future__ import annotations

import io
import json
import sys
from pathlib import Path

from vlm_ocr import cli

SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {"total": {"type": ["number", "null"], "x-labels": ["TOTAL"]}},
    "required": ["total"],
}


def _pipe(monkeypatch, raw: bytes) -> None:
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(raw)))


def _contract_file(tmp_path: Path, payload: dict) -> Path:
    path = tmp_path / "contrato.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_stdin_text_returns_text_json(monkeypatch, capsys) -> None:
    _pipe(monkeypatch, "cafe 1,20€ coockie 2,2€ total 3,40€".encode())

    code = cli.main(["-", "--format", "json", "--input-format", "txt"])

    assert code == 0
    assert (
        json.loads(capsys.readouterr().out)["text"].strip()
        == "cafe 1,20€ coockie 2,2€ total 3,40€"
    )


def test_stdin_text_alias(monkeypatch, capsys) -> None:
    _pipe(monkeypatch, b"hola")

    code = cli.main(["-", "--input-format", "text"])

    assert code == 0
    assert "hola" in capsys.readouterr().out


def test_txt_file_without_flag(tmp_path: Path, capsys) -> None:
    path = tmp_path / "nota.txt"
    path.write_text("hola\n", encoding="utf-8")

    code = cli.main([str(path)])

    assert code == 0
    assert "hola" in capsys.readouterr().out


def test_txt_flag_with_file_warns(tmp_path: Path, capsys) -> None:
    path = tmp_path / "nota.txt"
    path.write_text("hola\n", encoding="utf-8")

    code = cli.main([str(path), "--input-format", "txt"])

    assert code == 0
    assert "se ignora" in capsys.readouterr().err


def test_stdin_text_metrics(monkeypatch, tmp_path: Path) -> None:
    raw = b"hola\n"
    _pipe(monkeypatch, raw)
    out = tmp_path / "metrics.json"

    code = cli.main(["-", "--input-format", "txt", "--metrics-out", str(out)])

    assert code == 0
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["file"]["format"] == "txt"
    assert report["file"]["pages"] == 1
    assert report["ingest"]["native_pages"] == 1
    assert report["ingest"]["rasterized_pages"] == 0


def test_text_with_annotated_contract_resolves_rows(
    tmp_path: Path, capsys
) -> None:
    path = tmp_path / "nota.txt"
    path.write_text("TOTAL | 29.35\n", encoding="utf-8")
    contract = _contract_file(tmp_path, SCHEMA)

    code = cli.main(
        [
            str(path),
            "--format",
            "json",
            "--contract",
            str(contract),
            "--contract-kind",
            "schema",
            "--no-llm",
        ]
    )

    assert code == 0
    assert json.loads(capsys.readouterr().out)["total"] == 29.35
