from __future__ import annotations

from pathlib import Path

import pytest

from vlm_ocr.contract import (
    MAX_INSTRUCTIONS_CHARS,
    MAX_PROMPT_CHARS,
    ContractError,
    load_instructions,
    load_prompt,
    sidecar_path,
)


def _contract(tmp_path: Path, name: str = "factura.json") -> Path:
    path = tmp_path / name
    path.write_text("{}", encoding="utf-8")
    return path


def test_sidecar_path_uses_stem_plus_prompt(tmp_path: Path) -> None:
    assert sidecar_path(tmp_path / "factura.json") == tmp_path / "factura.prompt.md"
    assert (
        sidecar_path(tmp_path / "factura.schema.json")
        == tmp_path / "factura.schema.prompt.md"
    )


def test_missing_sidecar_returns_none(tmp_path: Path) -> None:
    assert load_instructions(_contract(tmp_path)) is None


def test_auto_detected_sidecar_is_loaded(tmp_path: Path) -> None:
    contract = _contract(tmp_path)
    (tmp_path / "factura.prompt.md").write_text("  El total va tras TOTAL:  ", encoding="utf-8")

    assert load_instructions(contract) == "El total va tras TOTAL:"


def test_explicit_instructions_override_sidecar(tmp_path: Path) -> None:
    contract = _contract(tmp_path)
    (tmp_path / "factura.prompt.md").write_text("auto", encoding="utf-8")
    explicit = tmp_path / "otro.md"
    explicit.write_text("explicito", encoding="utf-8")

    assert load_instructions(contract, explicit) == "explicito"


def test_empty_sidecar_returns_none(tmp_path: Path) -> None:
    contract = _contract(tmp_path)
    (tmp_path / "factura.prompt.md").write_text("   \n", encoding="utf-8")

    assert load_instructions(contract) is None


def test_explicit_missing_file_raises(tmp_path: Path) -> None:
    contract = _contract(tmp_path)

    with pytest.raises(ContractError, match="no existe"):
        load_instructions(contract, tmp_path / "no-existe.md")


def test_too_long_sidecar_raises(tmp_path: Path) -> None:
    contract = _contract(tmp_path)
    (tmp_path / "factura.prompt.md").write_text(
        "x" * (MAX_INSTRUCTIONS_CHARS + 1), encoding="utf-8"
    )

    with pytest.raises(ContractError, match="4000"):
        load_instructions(contract)


def test_stdin_contract_does_not_autodetect_sidecar(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "-.prompt.md").write_text("no usar", encoding="utf-8")

    assert load_instructions("-") is None


def test_instructions_from_stdin_data_are_stripped() -> None:
    assert load_instructions("c.json", "-", data=b"  ajuste  ") == "ajuste"


def test_instructions_from_stdin_respect_the_limit() -> None:
    with pytest.raises(ContractError, match="4000"):
        load_instructions("c.json", "-", data=b"x" * (MAX_INSTRUCTIONS_CHARS + 1))


def test_instructions_from_stdin_without_data_is_error() -> None:
    with pytest.raises(ContractError, match="stdin"):
        load_instructions("c.json", "-")


def test_load_prompt_inline() -> None:
    assert load_prompt("  resume el ticket  ") == "resume el ticket"


def test_load_prompt_from_stdin_with_bom() -> None:
    assert load_prompt("-", data=b"\xef\xbb\xbfresume") == "resume"


def test_load_prompt_empty_is_error() -> None:
    with pytest.raises(ContractError, match="vacío"):
        load_prompt("-", data=b"   ")


def test_load_prompt_respects_the_limit() -> None:
    with pytest.raises(ContractError, match="4000"):
        load_prompt("-", data=b"x" * (MAX_PROMPT_CHARS + 1))


def test_load_prompt_rejects_non_utf8() -> None:
    with pytest.raises(ContractError, match="UTF-8"):
        load_prompt("-", data=b"\xff")
