from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from . import extract, metrics, verify
from .annotations import has_annotations
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
from .layout import native_blocks, rows_text
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
    parser.add_argument(
        "--text-format",
        choices=["md", "rows"],
        help="texto para el contrato: md (defecto) o filas; con contrato anotado se usan filas",
    )
    parser.add_argument(
        "--no-llm",
        action="store_true",
        help="solo asignación determinista: no carga modelo",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="los valores que no aparecen literalmente en el texto son error (exit 2)",
    )
    parser.add_argument(
        "--n-ctx",
        type=int,
        default=4096,
        help="contexto del modelo en tokens (por defecto 4096); súbelo si el prompt no cabe",
    )
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


def _row_blocks(path: Path, pages, lang: str):
    """ Bloques con caja: celdas nativas del PDF + OCR de las páginas sin texto."""
    if path.suffix.lower() != ".pdf":
        return ocr_pages(pages, lang=lang)
    blocks = native_blocks(path)
    raster = [page for page in pages if page.image_png is not None]
    if raster:
        blocks = blocks + ocr_pages(raster, lang=lang)
    return blocks


def _elapsed_ms(start: float) -> float:
    return round((time.perf_counter() - start) * 1000, 1)


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    if args.instructions is not None and args.contract is None:
        print("error: --instructions requiere --contract", file=sys.stderr)
        return 2
    if args.format == "md" and (args.contract or args.instructions or args.model):
        print(
            "error: --contract, --instructions y --model requieren --format json",
            file=sys.stderr,
        )
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

    llm_start: float | None = None
    usage_out: dict | None = None

    def fail(kind: str, message: str, code: int) -> int:
        """Informa del error y, si se pidió, emite el informe parcial de métricas."""
        print(f"error: {message}", file=sys.stderr)
        if report is not None:
            report["error"] = {"kind": kind, "message": message}
            if llm_start is not None:
                report["llm"]["time_ms"] = _elapsed_ms(llm_start)
            if usage_out:
                report["llm"].update(usage_out)
            report["total"]["time_ms"] = _elapsed_ms(start)
            try:
                metrics.emit(report, to_stderr=args.metrics, out=args.metrics_out)
            except OSError:
                pass
        return code

    try:
        contract = None
        kind = None
        instructions = None
        model_path = None

        annotated = False
        use_rows = False
        if args.format == "json" and args.contract is not None:
            contract, detected_kind = load_contract(args.contract)
            kind = args.contract_kind or detected_kind
            instructions = load_instructions(args.contract, args.instructions)
            annotated = kind == "schema" and has_annotations(contract)
            use_rows = args.text_format == "rows" or (
                args.text_format is None and annotated
            )
            if args.model is not None:
                model_path = args.model
            elif args.no_llm:
                model_path = None
            else:
                model_path = default_model_path()
            if not args.no_llm:
                if model_path is None:
                    return fail(
                        "usage",
                        "no hay modelo: pasa --model o descárgalo con "
                        "`uv run python scripts/fetch_models.py`",
                        2,
                    )
                if not Path(model_path).is_file():
                    return fail("usage", f"no existe el modelo: {model_path}", 2)
            usage_out = {} if report is not None else None
            if report is not None:
                report["llm"]["enabled"] = not args.no_llm
                if model_path is not None:
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
            input_text = to_markdown(blocks)
            assignment = None
            if use_rows:
                row_blocks = _row_blocks(args.file, pages, args.lang)
                input_text = rows_text(row_blocks)
                assignment = extract.assign(row_blocks, contract)
                if report is not None:
                    report["extract"]["deterministic"] = len(assignment.matched)
                    report["extract"]["unmatched"] = len(assignment.unmatched)
                    report["extract"]["llm"] = False

            data = assignment.data if assignment is not None else None
            needs_llm = assignment is None or bool(assignment.unmatched)
            if needs_llm:
                if args.no_llm:
                    if assignment is None:
                        return fail(
                            "usage",
                            "--no-llm requiere un contrato anotado y --text-format rows",
                            2,
                        )
                else:
                    llm_start = time.perf_counter()
                    llm_data = infer_contract(
                        input_text,
                        contract,
                        kind,
                        model_path,
                        n_ctx=args.n_ctx,
                        instructions=instructions,
                        usage_out=usage_out,
                    )
                    if report is not None:
                        report["llm"]["time_ms"] = _elapsed_ms(llm_start)
                        report["llm"].update(usage_out or {})
                        report["extract"]["llm"] = True
                    data = (
                        extract.merge(assignment.data, llm_data)
                        if assignment is not None
                        else llm_data
                    )

            literal = verify.literal_errors(data, input_text)
            if report is not None:
                report["verify"]["errors"] = literal
            for problem in literal:
                print(
                    f"aviso: {problem['field']}: {problem['message']}",
                    file=sys.stderr,
                )
            if literal and args.strict:
                return fail(
                    "verify",
                    f"{len(literal)} valores no aparecen en el texto",
                    2,
                )
            errors = validate_payload(data, contract, kind)
            if errors:
                return fail(
                    "contract", "el contrato inferido no es válido: " + "; ".join(errors), 2
                )
            output = to_json_payload(data, blocks if args.with_layout else None)

        if report is not None:
            report["output"]["format"] = args.format
            report["output"]["size_bytes"] = len(output.encode("utf-8"))

        if args.out is not None:
            try:
                args.out.write_text(output, encoding="utf-8")
            except OSError as exc:
                return fail("io", f"no se pudo escribir {args.out}: {exc}", 1)
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
        return fail("input", str(exc), 1)
    except ContractError as exc:
        return fail("contract", str(exc), 2)
    except OSError as exc:
        return fail("io", str(exc), 1)
    except KeyboardInterrupt:
        return fail("interrupted", "interrumpido por el usuario", 130)
