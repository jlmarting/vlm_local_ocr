from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .contract import (
    ContractError,
    default_model_path,
    infer_contract,
    load_contract,
    load_instructions,
    validate_payload,
)
from .errors import InputError
from .ingest import ingest
from .ocr import ocr_pages
from .output import to_json_payload, to_markdown, to_text_json


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="vlm-ocr",
        description="Extrae texto de un documento y, opcionalmente, lo mapea a un contrato JSON.",
    )
    parser.add_argument("file", type=Path, help="PDF, imagen o captura")
    parser.add_argument(
        "--format",
        choices=["md", "json"],
        default="md",
        help="salida Markdown (defecto) o JSON de contrato",
    )
    parser.add_argument(
        "--contract",
        type=Path,
        help="ejemplo de payload o JSON Schema; si se omite, la salida JSON es {\"text\": ...}",
    )
    parser.add_argument(
        "--contract-kind",
        choices=["example", "schema"],
        help="fuerza la interpretación del contrato",
    )
    parser.add_argument(
        "--model",
        type=Path,
        help="modelo GGUF; si se omite, se usa el modelo por defecto si está descargado",
    )
    parser.add_argument(
        "--instructions",
        type=Path,
        help="instrucciones de ajuste para el contrato (por defecto <contrato>.prompt.md)",
    )
    parser.add_argument("--dpi", type=int, default=200, help="DPI al rasterizar PDFs")
    parser.add_argument("--lang", default="default", help="idioma del OCR")
    parser.add_argument(
        "--with-layout",
        action="store_true",
        help="envuelve la salida JSON con los boxes del OCR",
    )
    parser.add_argument("--out", type=Path, help="escribe la salida en este fichero")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    if args.instructions is not None and args.contract is None:
        print("error: --instructions requiere --contract", file=sys.stderr)
        return 2

    try:
        contract = None
        kind = None
        instructions = None
        model_path = None

        if args.format == "json" and args.contract is not None:
            contract, detected_kind = load_contract(args.contract)
            kind = args.contract_kind or detected_kind
            instructions = load_instructions(args.contract, args.instructions)
            model_path = args.model or default_model_path()
            if model_path is None:
                print(
                    "error: no hay modelo: pasa --model o descárgalo con "
                    "`uv run python scripts/fetch_models.py`",
                    file=sys.stderr,
                )
                return 2
            if not Path(model_path).is_file():
                print(f"error: no existe el modelo: {model_path}", file=sys.stderr)
                return 2

        pages = ingest(args.file, dpi=args.dpi)
        blocks = ocr_pages(pages, lang=args.lang)

        if args.format == "md":
            output = to_markdown(blocks)
        elif contract is None:
            output = to_text_json(
                to_markdown(blocks),
                blocks if args.with_layout else None,
            )
        else:
            data = infer_contract(
                to_markdown(blocks),
                contract,
                kind,
                model_path,
                instructions=instructions,
            )
            errors = validate_payload(data, contract, kind)
            if errors:
                print(
                    "error: el contrato inferido no es válido: " + "; ".join(errors),
                    file=sys.stderr,
                )
                return 2
            output = to_json_payload(data, blocks if args.with_layout else None)

        if args.out is not None:
            try:
                args.out.write_text(output, encoding="utf-8")
            except OSError as exc:
                print(f"error: no se pudo escribir {args.out}: {exc}", file=sys.stderr)
                return 1
        else:
            print(output)
        return 0
    except InputError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except ContractError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
