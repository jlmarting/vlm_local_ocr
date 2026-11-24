from __future__ import annotations

import json
from pathlib import Path
from time import perf_counter
from typing import Any

from .catalog import ModelRef
from .contract import _truncate_text, load_contract, load_instructions
from .ingest import ingest
from .llmrun import runner_for
from .ocr import ocr_pages
from .output import to_markdown
from .promptstyles import build_prompt, schema_from
from .vision import transcribe_pages


def run_bench(
    ref: ModelRef,
    *,
    doc: Path,
    contract_path: Path,
    text: Path | None = None,
    instructions: Path | None = None,
    n_ctx: int = 4096,
    max_tokens: int = 1200,
    grammar: bool = True,
    vision: bool = False,
) -> dict:
    """Mide una pasada del modelo sobre un documento y devuelve el registro."""
    contract, kind = load_contract(contract_path)
    sidecar = load_instructions(contract_path, instructions)
    runner = runner_for(ref, n_ctx)
    if text is not None:
        source = Path(text).read_text(encoding="utf-8")
        engine = "text"
    else:
        pages = ingest(doc)
        if vision:
            source = to_markdown(transcribe_pages(pages, runner, max_tokens=max_tokens))
            engine = "vision"
        else:
            source = to_markdown(ocr_pages(pages))
            engine = "ocr"

    prompt = build_prompt(ref, _truncate_text(source, 1500), contract, kind, sidecar)
    if not grammar:
        prompt.response_format = {"type": "json_object"}
    elif kind != "schema":
        prompt.response_format = {"type": "json_object", "schema": schema_from(contract)}

    start = perf_counter()
    raw, usage, finish = runner.complete(prompt, max_tokens)
    elapsed_ms = (perf_counter() - start) * 1000

    try:
        data: Any = json.loads(raw)
        valid = True
    except json.JSONDecodeError:
        data = None
        valid = False

    completion = (usage or {}).get("completion_tokens") or 0
    uses_grammar = grammar and ref.entry.prompt_style == "chat"
    return {
        "model": ref.label,
        "engine": engine,
        "doc": Path(doc).name if doc is not None else None,
        "mode": "grammar" if uses_grammar else "json",
        "valid_json": valid,
        "finish_reason": finish,
        "load_ms": runner.load_time_ms,
        "time_ms": round(elapsed_ms, 1),
        "prompt_tokens": (usage or {}).get("prompt_tokens"),
        "completion_tokens": (usage or {}).get("completion_tokens"),
        "tokens_per_second": (
            round(completion / (elapsed_ms / 1000), 2) if completion and elapsed_ms > 0 else None
        ),
        "chars": len(raw),
        "data": data,
        "raw": None if valid else raw[:400],
    }
