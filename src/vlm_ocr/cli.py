from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from . import metrics
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
    parser.add_argument(
        "--metrics",
        action="store_true",
        help="emite un informe de métricas JSON por stderr",
    )
    parser.add_argument(
        "--metrics-out",
        type=Path,
        help="escribe el informe de métricas en este fichero",
    )
    return parser


def _elapsed_ms(start: float) -> float:
    return round((time.perf_counter() - start) * 1000, 1)


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    if args.instructions is not None and args.contract is None:
        print("error: --instructions requiere --contract", file=sys.stderr)
        return 2

    start = time.perf_counter()
    report = metrics.empty_report() if (args.metrics or args.metrics_out) else None
    if report is not None:
        report["file"]["path"] = str(args.file)
        report["file"]["format"] = args.file.suffix.lower().lstrip(".") or None
        try:
            report["file"]["size_bytes"] = args.file.stat().st_size
        except OSError:
            pass

    try:
        contract = None
        kind = None
        instructions = None
        model_path = None
        usage_out = None

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
            usage_out = {} if report is not None else None
            if report is not None:
                report["llm"]["enabled"] = True
                report["llm"]["model"] = Path(model_path).name

        ingest_start = time.perf_counter()
        pages = ingest(args.file, dpi=args.dpi)
        raster_pages: set[int] = set()
        if report is not None:
            report["ingest"]["time_ms"] = _elapsed_ms(ingest_start)
            report["file"]["pages"] = len(pages)
            report["ingest"]["native_pages"] = sum(
                1 for page in pages if page.text is not None
            )
            report["ingest"]["rasterized_pages"] = sum(
                1 for page in pages if page.image_png is not None
            )
            report["ingest"]["dpi"] = args.dpi
            raster_pages = {page.index for page in pages if page.image_png is not None}

        ocr_start = time.perf_counter()
        blocks = ocr_pages(pages, lang=args.lang)
        if report is not None:
            report["ocr"]["time_ms"] = _elapsed_ms(ocr_start)
            report["ocr"]["blocks"] = len(blocks)
            report["ocr"]["mean_confidence"] = metrics.mean_confidence(blocks, raster_pages)

        if args.format == "md":
            output = to_markdown(blocks)
        elif contract is None:
            output = to_text_json(
                to_markdown(blocks),
                blocks if args.with_layout else None,
            )
        else:
            llm_start = time.perf_counter()
            data = infer_contract(
                to_markdown(blocks),
                contract,
                kind,
                model_path,
                instructions=instructions,
                usage_out=usage_out,
            )
            if report is not None:
                report["llm"]["time_ms"] = _elapsed_ms(llm_start)
                report["llm"].update(usage_out or {})
            errors = validate_payload(data, contract, kind)
            if errors:
                print(
                    "error: el contrato inferido no es válido: " + "; ".join(errors),
                    file=sys.stderr,
                )
                return 2
            output = to_json_payload(data, blocks if args.with_layout else None)

        if report is not None:
            report["output"]["format"] = args.format
            report["output"]["size_bytes"] = len(output.encode("utf-8"))

        if args.out is not None:
            try:
                args.out.write_text(output, encoding="utf-8")
            except OSError as exc:
                print(f"error: no se pudo escribir {args.out}: {exc}", file=sys.stderr)
                return 1
        else:
            print(output)

        if report is not None:
            report["total"]["time_ms"] = _elapsed_ms(start)
            try:
                metrics.emit(report, to_stderr=args.metrics, out=args.metrics_out)
            except OSError as exc:
                print(
                    f"error: no se pudo escribir el informe de métricas: {exc}",
                    file=sys.stderr,
                )
                return 1
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
