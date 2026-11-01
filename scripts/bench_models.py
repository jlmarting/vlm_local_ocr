from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from vlm_ocr import catalog
from vlm_ocr.bench import run_bench
from vlm_ocr.errors import ContractError


def main() -> int:
    parser = argparse.ArgumentParser(description="Banco de modelos para contratos JSON")
    parser.add_argument("--model", required=True, help="alias del catálogo o ruta .gguf")
    parser.add_argument("--doc", type=Path, required=True)
    parser.add_argument("--text", type=Path, help="texto ya serializado (prueba de concepto)")
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--instructions", type=Path)
    parser.add_argument("--n-ctx", type=int, default=4096)
    parser.add_argument("--max-tokens", type=int, default=1200)
    parser.add_argument("--no-grammar", action="store_true")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()

    try:
        record = run_bench(
            catalog.resolve(args.model),
            doc=args.doc,
            contract_path=args.contract,
            text=args.text,
            instructions=args.instructions,
            n_ctx=args.n_ctx,
            max_tokens=args.max_tokens,
            grammar=not args.no_grammar,
        )
    except (catalog.CatalogError, ContractError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    line = json.dumps(record, ensure_ascii=False)
    print(line)
    if args.out is not None:
        with args.out.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
