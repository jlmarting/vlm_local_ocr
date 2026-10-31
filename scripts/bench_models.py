from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

from llama_cpp import Llama

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from vlm_ocr.contract import (
    _build_messages,
    _truncate_text,
    load_contract,
    load_instructions,
)
from vlm_ocr.ingest import ingest
from vlm_ocr.ocr import ocr_pages
from vlm_ocr.output import to_markdown


def _scalar(value: Any) -> dict:
    if isinstance(value, bool):
        return {"type": "boolean"}
    if isinstance(value, int | float):
        return {"type": "number"}
    return {"type": "string"}


def schema_from(example: Any) -> dict:
    """Esquema del ejemplo con ``anyOf`` para anulables.

    La forma ``"type": ["number", "null"]`` degrada en silencio a la gramática JSON
    genérica de llama.cpp (comprobado), así que los nulos van por ``anyOf``.
    """
    if isinstance(example, dict):
        return {
            "type": "object",
            "properties": {key: schema_from(sub) for key, sub in example.items()},
            "required": list(example),
            "additionalProperties": False,
        }
    if isinstance(example, list):
        return {
            "type": "array",
            "items": schema_from(example[0]) if example else {},
        }
    return {"anyOf": [_scalar(example), {"type": "null"}]}


def main() -> int:
    parser = argparse.ArgumentParser(description="Banco de modelos para contratos JSON")
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--doc", type=Path, required=True)
    parser.add_argument("--text", type=Path, help="texto ya serializado (prueba de concepto)")
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--instructions", type=Path)
    parser.add_argument("--n-ctx", type=int, default=4096)
    parser.add_argument("--max-tokens", type=int, default=1200)
    parser.add_argument("--no-grammar", action="store_true")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()

    contract, kind = load_contract(args.contract)
    instructions = load_instructions(args.contract, args.instructions)
    if args.text is not None:
        text = args.text.read_text(encoding="utf-8")
    else:
        pages = ingest(args.doc)
        text = to_markdown(ocr_pages(pages))
    messages = _build_messages(_truncate_text(text, 1500), contract, kind, instructions)

    response_format: dict[str, Any] = {"type": "json_object"}
    if not args.no_grammar:
        response_format["schema"] = schema_from(contract)

    load_start = time.perf_counter()
    llm = Llama(model_path=str(args.model), n_ctx=args.n_ctx, verbose=False)
    load_ms = (time.perf_counter() - load_start) * 1000

    start = time.perf_counter()
    response = llm.create_chat_completion(
        messages=messages,
        temperature=0,
        max_tokens=args.max_tokens,
        response_format=response_format,
    )
    elapsed_ms = (time.perf_counter() - start) * 1000

    choice = response["choices"][0]
    raw = choice["message"]["content"]
    usage = response.get("usage") or {}
    try:
        data = json.loads(raw)
        valid = True
    except json.JSONDecodeError:
        data = None
        valid = False

    completion = usage.get("completion_tokens") or 0
    record = {
        "model": args.model.name,
        "doc": args.doc.name,
        "mode": "json" if args.no_grammar else "grammar",
        "valid_json": valid,
        "finish_reason": choice.get("finish_reason"),
        "load_ms": round(load_ms, 1),
        "time_ms": round(elapsed_ms, 1),
        "prompt_tokens": usage.get("prompt_tokens"),
        "completion_tokens": usage.get("completion_tokens"),
        "tokens_per_second": round(completion / (elapsed_ms / 1000), 2)
        if completion and elapsed_ms > 0
        else None,
        "chars": len(raw),
        "data": data,
        "raw": None if valid else raw[:400],
    }
    line = json.dumps(record, ensure_ascii=False)
    print(line)
    if args.out is not None:
        with args.out.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
