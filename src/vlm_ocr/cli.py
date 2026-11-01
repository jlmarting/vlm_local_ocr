from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

from . import catalog, extract, homologate, inputs, metrics, templates, verify
from .annotations import field_map, has_annotations
from .bench import run_bench
from .contract import (
    ContractError,
    infer_contract,
    load_contract,
    load_instructions,
    subschema,
    validate_payload,
)
from .errors import InputError
from .ingest import ingest
from .layout import native_blocks, rows_text
from .ocr import ocr_pages
from .output import to_json_payload, to_markdown, to_text_json

TEMPLATE_MIN_COVERAGE = 0.75


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
        help="alias del catálogo o ruta a un .gguf; si se omite, el modelo por defecto",
    )
    parser.add_argument(
        "--profile",
        help="perfil local del catálogo (fast, balanced, quality, extract)",
    )
    parser.add_argument(
        "--instructions",
        type=Path,
        help="instrucciones de ajuste para el contrato (por defecto <contrato>.prompt.md)",
    )
    parser.add_argument(
        "--input-format",
        choices=["pdf", "png", "jpg", "jpeg", "tiff", "bmp", "webp", "txt", "text"],
        help="tipo del documento cuando llega por stdin (se detecta solo si se omite)",
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
        "--homologate",
        action="store_true",
        help="registra la variante del documento tras una extracción buena",
    )
    parser.add_argument(
        "--homologate-partial",
        action="store_true",
        help="permite homologar aunque queden campos sin localizar",
    )
    parser.add_argument(
        "--homologate-report",
        type=Path,
        help="escribe el mapa aprendido sin guardarlo (inspección)",
    )
    parser.add_argument(
        "--templates-dir",
        type=Path,
        help="directorio de variantes (por defecto, el de datos del usuario)",
    )
    parser.add_argument(
        "--no-template",
        action="store_true",
        help="ignora las variantes registradas",
    )
    parser.add_argument(
        "--n-ctx",
        type=int,
        default=4096,
        help="contexto del modelo en tokens (por defecto 4096); súbelo si el prompt no cabe",
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        help="techo de tokens de salida; por defecto, el del catálogo o la fórmula",
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


def _row_blocks(
    path: Path,
    pages,
    blocks,
    lang: str,
    *,
    kind: str | None = None,
    data: bytes | None = None,
):
    """Bloques con caja: celdas nativas del PDF + OCR ya calculado de las rasterizadas."""
    document_kind = kind or path.suffix.lower().lstrip(".")
    if document_kind != "pdf":
        return blocks
    raster = {page.index for page in pages if page.image_png is not None}
    native = native_blocks(path) if data is None else native_blocks(path, data=data)
    return native + [block for block in blocks if block.page in raster]


def _elapsed_ms(start: float) -> float:
    return round((time.perf_counter() - start) * 1000, 1)


def default_model_path() -> Path | None:
    """Anclaje del modelo por defecto (los tests lo parchean)."""
    ref = catalog.default_ref()
    return ref.path if ref is not None else None


def _resolve_model(args: argparse.Namespace) -> catalog.ModelRef | None:
    """Precedencia: --model > --profile > --no-llm > modelo por defecto."""
    if args.model is not None:
        return catalog.resolve(args.model)
    if args.profile is not None:
        return catalog.by_profile(args.profile)
    if args.no_llm:
        return None
    path = default_model_path()
    return catalog.ref_for_path(path) if path is not None else None


def _no_model_message() -> str:
    alias = catalog.default_alias()
    hint = f"vlm-ocr models fetch {alias}" if alias else "vlm-ocr models list"
    return (
        "no hay modelo: usa --model <alias|ruta>, --profile <perfil> "
        f"o descárgalo con `{hint}`"
    )


def _missing_key(model_ref: catalog.ModelRef | None) -> str | None:
    """Mensaje de error si un modelo remoto exige key y no está en el entorno."""
    if model_ref is None or not model_ref.is_remote or not model_ref.entry.requires_key:
        return None
    env = model_ref.entry.api_key_env or "OLLAMA_API_KEY"
    if os.environ.get(env):
        return None
    return f"falta la API key del proveedor remoto: export {env}=..."


def _model_problem(model_ref: catalog.ModelRef | None) -> str | None:
    """Motivo por el que el modelo no se puede usar, o None si está listo."""
    if model_ref is None:
        return _no_model_message()
    if model_ref.path is not None and not model_ref.path.is_file():
        return f"no existe el modelo: {model_ref.path}"
    return _missing_key(model_ref)


def _human_size(size: int | None) -> str:
    return f"{size / (1024 ** 3):.2f} GB" if size else "—"


def _homologate_report(path: Path, payload: dict) -> None:
    try:
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    except OSError as exc:
        print(f"aviso: no se pudo escribir el informe de homologación: {exc}", file=sys.stderr)


def _models_list(args: argparse.Namespace) -> int:
    entries = catalog.load_catalog()
    rows: list[dict[str, object]] = []
    for alias in sorted(entries):
        entry = entries[alias]
        path = catalog.find_downloaded(entry)
        if entry.kind != "gguf":
            status = "remoto"
        elif path is None:
            status = "—"
        elif args.verify:
            status = "verificado" if catalog.verify_file(entry, path) else "hash incorrecto"
        else:
            status = "presente"
        rows.append(
            {
                "alias": alias,
                "name": entry.name,
                "kind": entry.kind,
                "size_bytes": entry.size_bytes,
                "license": entry.license,
                "profile": entry.profile or "—",
                "status": status,
                "path": str(path) if path is not None else None,
            }
        )
    if args.json:
        print(json.dumps(rows, ensure_ascii=False))
        return 0
    header = ("ALIAS", "NOMBRE", "TAMAÑO", "LICENCIA", "PERFIL", "ESTADO")
    cells = [
        (
            str(row["alias"]),
            str(row["name"]),
            _human_size(row["size_bytes"]),
            str(row["license"]),
            str(row["profile"]),
            str(row["status"]),
        )
        for row in rows
    ]
    widths = [len(value) for value in header]
    for row in cells:
        widths = [max(width, len(value)) for width, value in zip(widths, row)]
    for row in [header, *cells]:
        print("  ".join(value.ljust(width) for value, width in zip(row, widths)).rstrip())
    return 0


def _templates_rows(entries: list[templates.Template]) -> list[dict[str, object]]:
    return [
        {
            "contract_hash": entry.contract_hash,
            "digest": entry.digest,
            "version": entry.version,
            "fields_mapped": len(entry.map),
            "fields_unlocated": len(entry.unlocated),
            "updated_at": entry.updated_at,
        }
        for entry in entries
    ]


def _templates_list(args: argparse.Namespace) -> int:
    rows = _templates_rows(templates.all_templates(directory=args.templates_dir))
    if args.json:
        print(json.dumps(rows, ensure_ascii=False))
        return 0
    header = ("CONTRATO", "DIGEST", "VER", "MAPA", "SIN_LOC", "ACTUALIZADO")
    cells = [
        (
            str(row["contract_hash"])[:12],
            str(row["digest"])[:12],
            str(row["version"]),
            str(row["fields_mapped"]),
            str(row["fields_unlocated"]),
            str(row["updated_at"]),
        )
        for row in rows
    ]
    widths = [len(value) for value in header]
    for row in cells:
        widths = [max(width, len(value)) for width, value in zip(widths, row)]
    for row in [header, *cells]:
        print("  ".join(value.ljust(width) for value, width in zip(row, widths)).rstrip())
    return 0


def _templates_find(digest: str, directory: Path | str | None) -> templates.Template:
    matches = templates.find_templates(digest, directory=directory)
    if not matches:
        raise catalog.CatalogError(f"no hay variante que empiece por «{digest}»")
    if len(matches) > 1:
        options = ", ".join(match.digest[:12] for match in matches)
        raise catalog.CatalogError(f"prefijo ambiguo «{digest}»: {options}")
    return matches[0]


def _templates_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="vlm-ocr templates", description="Variantes homologadas.")
    commands = parser.add_subparsers(dest="command")
    listing = commands.add_parser("list", help="lista las variantes registradas")
    listing.add_argument("--json", action="store_true", help="salida JSON")
    listing.add_argument("--templates-dir", type=Path, help="directorio de variantes")
    showing = commands.add_parser("show", help="muestra una variante (por prefijo de digest)")
    showing.add_argument("digest")
    showing.add_argument("--templates-dir", type=Path, help="directorio de variantes")
    dropping = commands.add_parser("drop", help="elimina una variante (por prefijo de digest)")
    dropping.add_argument("digest")
    dropping.add_argument("--yes", action="store_true", help="confirma el borrado")
    dropping.add_argument("--templates-dir", type=Path, help="directorio de variantes")
    return parser


def _templates_main(argv: list[str]) -> int:
    parser = _templates_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "list":
            return _templates_list(args)
        if args.command == "show":
            entry = _templates_find(args.digest, args.templates_dir)
            print(json.dumps(templates.template_to_dict(entry), ensure_ascii=False, indent=2))
            return 0
        if args.command == "drop":
            entry = _templates_find(args.digest, args.templates_dir)
            if not args.yes:
                print(
                    f"error: borrar {entry.digest[:12]} es destructivo; repite con --yes",
                    file=sys.stderr,
                )
                return 2
            path = templates.drop_template(entry, directory=args.templates_dir)
            print(f"variante eliminada: {path}")
            return 0
    except catalog.CatalogError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    parser.print_help(sys.stderr)
    return 2


def _models_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="vlm-ocr models", description="Catálogo de modelos.")
    commands = parser.add_subparsers(dest="command")
    listing = commands.add_parser("list", help="lista el catálogo y su estado")
    listing.add_argument("--json", action="store_true", help="salida JSON")
    listing.add_argument(
        "--verify",
        action="store_true",
        help="verifica el sha256 (lento con modelos grandes)",
    )
    fetching = commands.add_parser("fetch", help="descarga y verifica uno o más modelos")
    fetching.add_argument("alias", nargs="+", help="alias del catálogo")
    fetching.add_argument("--dest", type=Path, help="directorio de destino")
    fetching.add_argument(
        "--accept-license",
        action="store_true",
        help="acepta la licencia del modelo (obligatorio si lo exige)",
    )
    benchmarking = commands.add_parser("bench", help="mide un modelo sobre un documento")
    benchmarking.add_argument("alias", help="alias del catálogo")
    benchmarking.add_argument("--doc", type=Path, required=True)
    benchmarking.add_argument("--contract", type=Path, required=True)
    benchmarking.add_argument("--text", type=Path, help="texto ya serializado")
    benchmarking.add_argument("--instructions", type=Path)
    benchmarking.add_argument("--n-ctx", type=int, default=4096)
    benchmarking.add_argument("--max-tokens", type=int, default=1200)
    benchmarking.add_argument("--no-grammar", action="store_true")
    benchmarking.add_argument("--out", type=Path)
    return parser


def _models_main(argv: list[str]) -> int:
    parser = _models_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "list":
            return _models_list(args)
        if args.command == "fetch":
            for alias in args.alias:
                catalog.fetch(alias, dest=args.dest, accept_license=args.accept_license)
            return 0
        if args.command == "bench":
            record = run_bench(
                catalog.resolve(args.alias),
                doc=args.doc,
                contract_path=args.contract,
                text=args.text,
                instructions=args.instructions,
                n_ctx=args.n_ctx,
                max_tokens=args.max_tokens,
                grammar=not args.no_grammar,
            )
            line = json.dumps(record, ensure_ascii=False)
            print(line)
            if args.out is not None:
                args.out.open("a", encoding="utf-8").write(line + "\n")
            return 0
    except catalog.CatalogError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except ContractError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    parser.print_help(sys.stderr)
    return 2


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "models":
        return _models_main(argv[1:])
    if argv and argv[0] == "templates":
        return _templates_main(argv[1:])
    args = _build_parser().parse_args(argv)

    if args.max_tokens is not None and args.max_tokens <= 0:
        print("error: --max-tokens debe ser un entero positivo", file=sys.stderr)
        return 2

    stdin_uses = [
        name
        for name, value in (
            ("documento", args.file),
            ("--contract", args.contract),
            ("--instructions", args.instructions),
        )
        if value is not None and inputs.is_stdin(value)
    ]
    if len(stdin_uses) > 1:
        print(
            "error: solo una entrada puede ser '-' (documento, --contract, --instructions)",
            file=sys.stderr,
        )
        return 2
    if stdin_uses and inputs.stdin_is_tty():
        print(
            "error: stdin es un terminal; usa una tubería o un fichero",
            file=sys.stderr,
        )
        return 2

    if args.instructions is not None and args.contract is None:
        print("error: --instructions requiere --contract", file=sys.stderr)
        return 2
    if args.format == "md" and (
        args.contract or args.instructions or args.model or args.profile
    ):
        print(
            "error: --contract, --instructions, --model y --profile requieren --format json",
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
        model_ref: catalog.ModelRef | None = None

        annotated = False
        use_rows = False
        templates_enabled = False
        template_contract_hash: str | None = None
        variants: list[templates.Template] = []
        if args.format == "json" and args.contract is not None:
            contract_data = (
                inputs.read_stdin_bytes() if inputs.is_stdin(args.contract) else None
            )
            if contract_data is None:
                contract, detected_kind = load_contract(args.contract)
            else:
                contract, detected_kind = load_contract(
                    args.contract, data=contract_data
                )
            kind = args.contract_kind or detected_kind
            instructions_data = (
                inputs.read_stdin_bytes()
                if args.instructions is not None and inputs.is_stdin(args.instructions)
                else None
            )
            instructions = load_instructions(
                args.contract, args.instructions, data=instructions_data
            )
            annotated = kind == "schema" and has_annotations(contract)
            use_rows = args.text_format == "rows" or (
                args.text_format is None and annotated
            )
            templates_enabled = not args.no_template
            if templates_enabled:
                template_contract_hash = templates.contract_hash(contract)
                variants = templates.list_templates(
                    template_contract_hash, directory=args.templates_dir
                )
            model_ref = _resolve_model(args)
            missing_key = _missing_key(model_ref)
            if missing_key is not None and not args.no_llm:
                return fail("usage", missing_key, 2)
            if (
                model_ref is not None
                and model_ref.entry.prompt_style != "chat"
                and not args.no_llm
                and (instructions or model_ref.entry.prompt_hints)
            ):
                print(
                    "aviso: el estilo del modelo no usa instrucciones ni notas; se omiten",
                    file=sys.stderr,
                )
            if not args.no_llm and not use_rows and not templates_enabled:
                problem = _model_problem(model_ref)
                if problem is not None:
                    return fail("usage", problem, 2)
            usage_out = {} if report is not None else None
            if report is not None and model_ref is not None:
                report["llm"]["model"] = model_ref.label
                report["llm"]["provider"] = model_ref.entry.kind

        document_data = None
        document_kind = None
        if inputs.is_stdin(args.file):
            document_data = inputs.read_stdin_bytes()
            if not document_data:
                return fail("input", "el documento por stdin está vacío", 1)
            if args.input_format is not None:
                aliases = {"jpeg": "jpg", "text": "txt"}
                document_kind = aliases.get(args.input_format, args.input_format)
            else:
                document_kind = inputs.detect_document_kind(document_data)
                if document_kind is None:
                    return fail(
                        "input",
                        "no se reconoce el tipo del documento por stdin; "
                        "usa --input-format",
                        1,
                    )
            if report is not None:
                report["file"]["size_bytes"] = len(document_data)
                report["file"]["format"] = document_kind
        elif args.input_format is not None:
            print("aviso: --input-format se ignora con ficheros", file=sys.stderr)

        ingest_start = time.perf_counter()
        if document_data is None:
            pages = ingest(args.file, dpi=args.dpi)
        else:
            pages = ingest(
                args.file, dpi=args.dpi, data=document_data, kind=document_kind
            )
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
            template = None
            template_data = None
            template_covered: set[str] = set()
            contract_assignment = None
            row_blocks = None

            need_rows = use_rows or (
                templates_enabled
                and (bool(variants) or args.homologate or args.homologate_report is not None)
            )
            if need_rows:
                row_blocks = _row_blocks(
                    args.file,
                    pages,
                    blocks,
                    args.lang,
                    kind=document_kind,
                    data=document_data,
                )
            if use_rows and row_blocks is not None:
                input_text = rows_text(row_blocks)

            if variants and row_blocks is not None and template_contract_hash is not None:
                found = templates.best_template(
                    row_blocks,
                    template_contract_hash,
                    directory=args.templates_dir,
                )
                if found is not None:
                    candidate, candidate_score = found
                    hint = templates.hint_from_template(candidate, contract, kind)
                    candidate_assignment = extract.assign(row_blocks, hint)
                    mapped = len(candidate.map)
                    coverage = (
                        len(candidate_assignment.matched) / mapped if mapped else 0.0
                    )
                    if mapped and coverage >= TEMPLATE_MIN_COVERAGE:
                        template = candidate
                        assignment = candidate_assignment
                        template_data = candidate_assignment.data
                        template_covered = set(candidate_assignment.matched)
                        if annotated:
                            contract_assignment = extract.assign(row_blocks, contract)
                            template_data = extract.merge(
                                candidate_assignment.data, contract_assignment.data
                            )
                            template_covered |= set(contract_assignment.matched)
                        input_text = rows_text(row_blocks)
                        if report is not None:
                            report["template"].update(
                                {
                                    "found": True,
                                    "digest": candidate.digest,
                                    "score": round(candidate_score, 4),
                                    "version": candidate.version,
                                    "coverage": round(coverage, 2),
                                }
                            )
                            report["extract"]["coverage"] = round(coverage, 2)
                            report["extract"]["deterministic"] = len(template_covered)
                            report["extract"]["unmatched"] = len(assignment.unmatched)
                            report["extract"]["pending"] = len(assignment.pending)
                            report["extract"]["llm"] = False
                    else:
                        if report is not None:
                            report["template"]["drift"] = True
                        print(
                            "aviso: la variante registrada ya no cubre el documento "
                            f"({len(candidate_assignment.matched)}/{mapped}); se usa el LLM.",
                            file=sys.stderr,
                        )

            if template is None and use_rows and row_blocks is not None:
                input_text = rows_text(row_blocks)
                if annotated:
                    assignment = extract.assign(row_blocks, contract)
                    annotated_fields = len(field_map(contract))
                    coverage = (
                        len(assignment.matched) / annotated_fields
                        if annotated_fields
                        else 1.0
                    )
                    if annotated_fields and coverage < 0.75:
                        print(
                            f"aviso: cobertura baja: {len(assignment.matched)}/"
                            f"{annotated_fields} campos anotados (¿escaneo de baja calidad?)",
                            file=sys.stderr,
                        )
                        if args.strict:
                            return fail(
                                "verify",
                                f"cobertura baja: {len(assignment.matched)}/"
                                f"{annotated_fields} campos anotados",
                                2,
                            )
                    if report is not None:
                        report["extract"]["coverage"] = round(coverage, 2)
                        report["extract"]["deterministic"] = len(assignment.matched)
                        report["extract"]["unmatched"] = len(assignment.unmatched)
                        report["extract"]["pending"] = len(assignment.pending)
                        report["extract"]["llm"] = False

            if template is not None:
                data = template_data
            else:
                data = assignment.data if assignment is not None else None
            missing: list[str] = []
            if template is not None and assignment is not None:
                contract_pending = (
                    set(contract_assignment.pending)
                    if contract_assignment is not None
                    else set()
                )
                missing = sorted(
                    (set(template.unlocated) | set(assignment.pending) | contract_pending)
                    - template_covered
                )
            elif assignment is not None:
                missing = list(assignment.pending)
            needs_llm = assignment is None or bool(missing)

            if needs_llm:
                if args.no_llm:
                    if assignment is None:
                        return fail(
                            "usage",
                            "--no-llm requiere un contrato anotado, una variante o "
                            "--text-format rows",
                            2,
                        )
                else:
                    problem = _model_problem(model_ref)
                    if problem is not None:
                        return fail("usage", problem, 2)
                    if model_ref.is_remote:
                        print(
                            "aviso: el texto del documento se enviará a "
                            f"{model_ref.entry.base_url}",
                            file=sys.stderr,
                        )
                    if report is not None:
                        report["llm"]["enabled"] = True
                    llm_start = time.perf_counter()
                    prompt_contract = (
                        subschema(contract, missing, kind) if missing else contract
                    )
                    llm_data = infer_contract(
                        input_text,
                        prompt_contract,
                        kind,
                        model_ref,
                        n_ctx=args.n_ctx,
                        instructions=instructions,
                        max_output_tokens=args.max_tokens,
                        usage_out=usage_out,
                    )
                    if report is not None:
                        report["llm"]["time_ms"] = _elapsed_ms(llm_start)
                        report["llm"].update(usage_out or {})
                        report["extract"]["llm"] = True
                    data = (
                        extract.merge(data, llm_data)
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

            if args.homologate or args.homologate_report is not None:
                if not templates_enabled or row_blocks is None:
                    print(
                        "aviso: --homologate requiere plantillas habilitadas y filas",
                        file=sys.stderr,
                    )
                else:
                    learned, absent, unlocated = homologate.learn_map(
                        data, row_blocks, contract, kind, assignment
                    )
                    literal_fields = {problem["field"] for problem in literal}
                    for path in literal_fields:
                        learned.pop(path, None)
                    if literal_fields:
                        unlocated = sorted(set(unlocated) | literal_fields)
                        print(
                            "aviso: no se homologan "
                            f"{len(literal_fields)} campos con valores no literales; "
                            "quedarán para el LLM.",
                            file=sys.stderr,
                        )
                    blockers = sorted(set(unlocated))
                    labels = [
                        label for item in learned.values() for label in item.labels
                    ]
                    fingerprint = templates.signature(row_blocks, labels)
                    blocked = bool(blockers) and not args.homologate_partial
                    saved = None
                    if fingerprint is None:
                        if args.homologate:
                            print(
                                "aviso: no se pudo aprender el mapa; no se homologa",
                                file=sys.stderr,
                            )
                    elif blocked:
                        print(
                            "aviso: no se homologa: "
                            f"{len(blockers)} campos sin localizar "
                            f"({', '.join(blockers)}); usa --homologate-partial "
                            "para guardar solo los localizados",
                            file=sys.stderr,
                        )
                    elif args.homologate:
                        saved = templates.save_template(
                            fingerprint,
                            templates.Template(
                                contract_hash=template_contract_hash
                                or templates.contract_hash(contract),
                                fingerprint=fingerprint,
                                map=learned,
                                absent=tuple(absent),
                                unlocated=tuple(unlocated),
                            ),
                            directory=args.templates_dir,
                        )
                    if report is not None:
                        report["template"].update(
                            {
                                "fields_mapped": len(learned),
                                "fields_unlocated": len(unlocated),
                                "blocked": blocked,
                            }
                        )
                        if saved is not None:
                            report["template"].update(
                                {
                                    "found": True,
                                    "homologated": True,
                                    "digest": saved.digest,
                                    "version": saved.version,
                                }
                            )
                    if args.homologate_report is not None:
                        _homologate_report(
                            args.homologate_report,
                            {
                                "contract_hash": template_contract_hash
                                or templates.contract_hash(contract),
                                "digest": fingerprint.digest if fingerprint else None,
                                "labels": labels,
                                "map": {
                                    path: {
                                        "labels": list(item.labels),
                                        "source": item.source,
                                        "join_label": item.join_label,
                                    }
                                    for path, item in learned.items()
                                },
                                "absent": list(absent),
                                "unlocated": list(unlocated),
                                "blockers": blockers,
                                "blocked": blocked,
                                "saved": saved is not None,
                            },
                        )

            if (
                templates_enabled
                and not args.homologate
                and args.homologate_report is None
                and template is None
                and not literal
                and sys.stderr.isatty()
            ):
                print(
                    "aviso: documento no homologado; usa --homologate para "
                    "registrar esta variante",
                    file=sys.stderr,
                )

            if report is not None and contract is not None:
                filled, total = verify.field_coverage(data, contract, kind)
                report["extract"]["fields_total"] = total
                report["extract"]["fields_filled"] = filled
                report["extract"]["coverage_contract"] = (
                    round(filled / total, 2) if total else None
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
    except catalog.CatalogError as exc:
        return fail("usage", str(exc), 2)
    except ContractError as exc:
        return fail("contract", str(exc), 2)
    except OSError as exc:
        return fail("io", str(exc), 1)
    except KeyboardInterrupt:
        return fail("interrupted", "interrumpido por el usuario", 130)
