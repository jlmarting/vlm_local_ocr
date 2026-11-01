from __future__ import annotations

import json
from pathlib import Path

import pytest

from vlm_ocr import catalog, cli
from vlm_ocr.types import LayoutBlock, PageInput

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


def _mock_pipeline(monkeypatch) -> None:
    blocks = [LayoutBlock(0, "texto de prueba", 1.0, (0.0, 0.0, 1.0, 1.0))]
    monkeypatch.setattr(cli, "ingest", lambda path, dpi=200: [PageInput(0, "texto", None)])
    monkeypatch.setattr(cli, "ocr_pages", lambda pages, lang="default": blocks)


def _contract(tmp_path: Path) -> Path:
    path = tmp_path / "contrato.json"
    path.write_text(json.dumps(EXAMPLE), encoding="utf-8")
    return path


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


def test_unknown_alias_lists_available(tmp_path: Path, monkeypatch, capsys, install) -> None:
    _mock_pipeline(monkeypatch)
    install({"llama32-3b": gguf(file="l.gguf", default=True)})

    code = cli.main(
        [str(_contract(tmp_path).parent / "doc.pdf"), "--format", "json",
         "--contract", str(_contract(tmp_path)), "--model", "noexiste"]
    )

    assert code == 2
    err = capsys.readouterr().err
    assert "alias desconocido" in err
    assert "llama32-3b" in err


def test_profile_selects_alias(tmp_path: Path, monkeypatch, capsys, install) -> None:
    _mock_pipeline(monkeypatch)
    models = install({"qwen05b": gguf(profile="fast")})
    (models / "m.gguf").write_bytes(b"")
    captured: list[catalog.ModelRef] = []
    monkeypatch.setattr(cli, "infer_contract", lambda *a, **k: captured.append(a[3]) or EXAMPLE)

    code = cli.main(
        [str(_contract(tmp_path).parent / "doc.pdf"), "--format", "json",
         "--contract", str(_contract(tmp_path)), "--profile", "fast"]
    )

    assert code == 0
    assert captured[0].label == "qwen05b"


def test_model_beats_profile(tmp_path: Path, monkeypatch, capsys, install) -> None:
    _mock_pipeline(monkeypatch)
    models = install(
        {
            "qwen05b": gguf(profile="fast"),
            "otro": gguf(file="o.gguf"),
        }
    )
    (models / "m.gguf").write_bytes(b"")
    (models / "o.gguf").write_bytes(b"")
    captured: list[catalog.ModelRef] = []
    monkeypatch.setattr(cli, "infer_contract", lambda *a, **k: captured.append(a[3]) or EXAMPLE)

    code = cli.main(
        [str(_contract(tmp_path).parent / "doc.pdf"), "--format", "json",
         "--contract", str(_contract(tmp_path)), "--profile", "fast", "--model", "otro"]
    )

    assert code == 0
    assert captured[0].label == "otro"


def test_profile_not_downloaded_points_to_fetch(
    tmp_path: Path, monkeypatch, capsys, install
) -> None:
    _mock_pipeline(monkeypatch)
    install({"nuextract-tiny": gguf(file="n.gguf", profile="extract")})

    code = cli.main(
        [str(_contract(tmp_path).parent / "doc.pdf"), "--format", "json",
         "--contract", str(_contract(tmp_path)), "--profile", "extract"]
    )

    assert code == 2
    assert "models fetch nuextract-tiny" in capsys.readouterr().err


def test_missing_default_points_to_fetch(tmp_path: Path, monkeypatch, capsys, install) -> None:
    _mock_pipeline(monkeypatch)
    install({"llama32-3b": gguf(file="l.gguf", default=True)})

    code = cli.main(
        [str(_contract(tmp_path).parent / "doc.pdf"), "--format", "json",
         "--contract", str(_contract(tmp_path))]
    )

    assert code == 2
    err = capsys.readouterr().err
    assert "models fetch llama32-3b" in err


def test_metrics_report_provider_and_alias(
    tmp_path: Path, monkeypatch, capsys, install
) -> None:
    _mock_pipeline(monkeypatch)
    models = install({"llama32-3b": gguf(file="l.gguf", default=True)})
    (models / "l.gguf").write_bytes(b"")
    monkeypatch.setattr(cli, "infer_contract", lambda *a, **k: EXAMPLE)

    code = cli.main(
        [str(_contract(tmp_path).parent / "doc.pdf"), "--format", "json",
         "--contract", str(_contract(tmp_path)), "--metrics"]
    )

    assert code == 0
    report = json.loads(capsys.readouterr().err.strip().splitlines()[-1])
    assert report["llm"]["model"] == "llama32-3b"
    assert report["llm"]["provider"] == "gguf"


def test_profile_requires_json_format(tmp_path: Path, monkeypatch, capsys) -> None:
    def boom(*args, **kwargs):
        raise AssertionError("no debe procesar el fichero")

    monkeypatch.setattr(cli, "ingest", boom)
    source = tmp_path / "doc.pdf"
    source.write_bytes(b"")

    assert cli.main([str(source), "--profile", "fast"]) == 2
    assert "--format json" in capsys.readouterr().err


def test_models_list_prints_a_row_per_alias(capsys, install) -> None:
    install({"a": gguf(), "b": gguf(file="b.gguf")})

    assert cli.main(["models", "list"]) == 0

    out = capsys.readouterr().out
    assert "ALIAS" in out
    assert "\na " in out or out.splitlines()[1].split()[0] == "a"
    assert "b" in out


def test_models_list_json_has_six_real_entries(capsys) -> None:
    assert cli.main(["models", "list", "--json"]) == 0

    rows = json.loads(capsys.readouterr().out)
    assert len(rows) == 6
    assert {row["alias"] for row in rows} >= {"llama32-3b", "nuextract-tiny"}


def test_models_list_marks_downloaded(capsys, install) -> None:
    models = install({"a": gguf()})
    (models / "m.gguf").write_bytes(b"")

    cli.main(["models", "list", "--json"])

    rows = {row["alias"]: row for row in json.loads(capsys.readouterr().out)}
    assert rows["a"]["status"] == "presente"


def test_models_list_verify_detects_bad_hash(capsys, install) -> None:
    models = install({"a": gguf()})
    (models / "m.gguf").write_bytes(b"contenido que no casa")

    cli.main(["models", "list", "--json", "--verify"])

    rows = {row["alias"]: row for row in json.loads(capsys.readouterr().out)}
    assert rows["a"]["status"] == "hash incorrecto"


def test_models_without_command_shows_help(capsys) -> None:
    assert cli.main(["models"]) == 2
    assert "list" in capsys.readouterr().err
