from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .contract import ContractError, infer_contract, load_contract, validate_payload
from .ingest import ingest
from .ocr import ocr_pages
from .output import to_json_payload, to_markdown


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
    parser.add_argument("--contract", type=Path, help="ejemplo de payload o JSON Schema")
    parser.add_argument(
        "--contract-kind",
        choices=["example", "schema"],
        help="fuerza la interpretación del contrato",
    )
    parser.add_argument("--model", type=Path, help="modelo GGUF para inferir el contrato")
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

    if args.format == "json":
        if args.contract is None:
            print("error: --format json requiere --contract", file=sys.stderr)
            return 2
        if args.model is None:
            print("error: --format json requiere --model", file=sys.stderr)
            return 2

    try:
        pages = ingest(args.file, dpi=args.dpi)
        blocks = ocr_pages(pages, lang=args.lang)

        if args.format == "md":
            output = to_markdown(blocks)
        else:
            contract, detected_kind = load_contract(args.contract)
            kind = args.contract_kind or detected_kind
            data = infer_contract(
                to_markdown(blocks),
                contract,
                kind,
                args.model,
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
            args.out.write_text(output, encoding="utf-8")
        else:
            print(output)
        return 0
    except FileNotFoundError as exc:
        print(f"error: no existe el fichero: {exc}", file=sys.stderr)
        return 1
    except (ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except ContractError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
