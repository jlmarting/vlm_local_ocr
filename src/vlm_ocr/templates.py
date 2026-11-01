from __future__ import annotations

import hashlib
import json
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from . import paths
from .annotations import (
    SOURCE_ALIASES,
    leaf_paths_for,
    leaf_types_for,
    normalize_label,
)
from .extract import detect_columns
from .layout import group_rows
from .types import LayoutBlock

FORMAT_VERSION = 2
BANDS = 20
MIN_SCORE = 0.85
MIN_MARGIN = 0.05
SCORE_LABELS = 0.75
SCORE_COLUMNS = 0.25


@dataclass(frozen=True)
class RowMark:
    """Una etiqueta relevante en una posición horizontal relativa."""

    label: str
    x_band: int
    page: int


@dataclass(frozen=True)
class Fingerprint:
    """Huella de una variante: secuencia de etiquetas relevantes + columnas."""

    digest: str
    rows: tuple[RowMark, ...]
    columns: tuple[str, ...]


@dataclass(frozen=True)
class FieldMap:
    """Cómo se localizó un campo: sus etiquetas, su columna y si une etiqueta+valor."""

    labels: tuple[str, ...]
    source: str | None = None
    join_label: bool | None = None


@dataclass(frozen=True)
class ItemMap:
    """Cómo se localiza un array repetido: roles por propiedad y stop/inicio."""

    columns: dict[str, str]
    stop_labels: tuple[str, ...]
    start_labels: tuple[str, ...]


@dataclass(frozen=True)
class Template:
    """Una variante de una tipología (el hash del contrato)."""

    contract_hash: str
    fingerprint: Fingerprint
    map: dict[str, FieldMap] = field(default_factory=dict)
    items: dict[str, ItemMap] = field(default_factory=dict)
    absent: tuple[str, ...] = ()
    unlocated: tuple[str, ...] = ()
    version: int = 1
    created_at: str = ""
    updated_at: str = ""

    @property
    def digest(self) -> str:
        return self.fingerprint.digest


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def contract_hash(contract: dict) -> str:
    """Hash canónico del contrato: identifica la tipología y caduca las variantes."""
    return hashlib.sha256(_canonical(contract).encode("utf-8")).hexdigest()


def _digest(rows: tuple[RowMark, ...], columns: tuple[str, ...]) -> str:
    payload = {
        "format": FORMAT_VERSION,
        "rows": [
            {"label": row.label, "x": row.x_band, "page": row.page} for row in rows
        ],
        "columns": list(columns),
    }
    return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()


def signature(blocks: list[LayoutBlock], labels: Iterable[str]) -> Fingerprint | None:
    """Huella relevante: solo etiquetas del mapa + cabeceras, en orden de lectura.

    No entran valores, coordenadas absolutas ni filas irrelevantes (membrete,
    observaciones, tags). La banda horizontal es relativa a la caja de lo relevante.
    """
    wanted = {normalize_label(label) for label in labels if label}
    if not wanted:
        return None

    rows = group_rows([block for block in blocks if block.text.strip()])
    relevant_by_page: dict[int, list[LayoutBlock]] = {}
    marked: list[tuple[int, float, float, str]] = []
    columns: list[str] = []

    for row in rows:
        detected = detect_columns(row)
        if detected:
            for source, span in sorted(detected.items(), key=lambda item: item[1][0]):
                if source not in columns:
                    columns.append(source)
        for block in row:
            normalized = normalize_label(block.text)
            is_label = normalized in wanted
            is_header = normalized in SOURCE_ALIASES
            if is_label or is_header:
                relevant_by_page.setdefault(block.page, []).append(block)
            if is_label:
                marked.append(
                    (block.page, block.box[0], block.box[2], normalized)
                )

    if not marked:
        return None

    bounds = {
        page: (
            min(block.box[0] for block in items),
            max(block.box[2] for block in items),
        )
        for page, items in relevant_by_page.items()
    }

    marks: list[RowMark] = []
    for page, left, right, normalized in marked:
        page_left, page_right = bounds[page]
        width = max(1.0, page_right - page_left)
        center = (left + right) / 2
        band = min(BANDS - 1, max(0, int(BANDS * (center - page_left) / width)))
        marks.append(RowMark(label=normalized, x_band=band, page=page))

    columns_tuple = tuple(dict.fromkeys(columns))
    return Fingerprint(
        digest=_digest(tuple(marks), columns_tuple),
        rows=tuple(marks),
        columns=columns_tuple,
    )


def template_dir(explicit: Path | str | None = None) -> Path:
    """Directorio de plantillas: explícito o el de datos de la plataforma."""
    if explicit is not None:
        return Path(explicit)
    return paths.data_dir() / "templates"


def _contract_dir(contract: str, directory: Path | str | None) -> Path:
    return template_dir(directory) / contract


def _template_path(contract: str, digest: str, directory: Path | str | None) -> Path:
    return _contract_dir(contract, directory) / f"{digest}.json"


def _field_map_to_dict(value: FieldMap) -> dict[str, Any]:
    payload: dict[str, Any] = {"labels": list(value.labels), "source": value.source}
    if value.join_label is not None:
        payload["join_label"] = value.join_label
    return payload


def _field_map_from_dict(value: dict[str, Any]) -> FieldMap:
    join = value.get("join_label")
    return FieldMap(
        labels=tuple(str(label) for label in value.get("labels", [])),
        source=value.get("source"),
        join_label=join if isinstance(join, bool) else None,
    )


def template_to_dict(template: Template) -> dict[str, Any]:
    return {
        "format": FORMAT_VERSION,
        "contract_hash": template.contract_hash,
        "digest": template.digest,
        "version": template.version,
        "created_at": template.created_at,
        "updated_at": template.updated_at,
        "fingerprint": {
            "rows": [
                {"label": row.label, "x": row.x_band, "page": row.page}
                for row in template.fingerprint.rows
            ],
            "columns": list(template.fingerprint.columns),
        },
        "map": {path: _field_map_to_dict(item) for path, item in template.map.items()},
        "items": {
            path: {
                "columns": dict(item.columns),
                "stop_labels": list(item.stop_labels),
                "start_labels": list(item.start_labels),
            }
            for path, item in template.items.items()
        },
        "absent": list(template.absent),
        "unlocated": list(template.unlocated),
    }


def template_from_dict(value: dict[str, Any]) -> Template:
    fingerprint_value = value.get("fingerprint", {})
    rows = tuple(
        RowMark(
            label=str(row["label"]),
            x_band=int(row["x"]),
            page=int(row.get("page", 0)),
        )
        for row in fingerprint_value.get("rows", [])
    )
    columns = tuple(str(column) for column in fingerprint_value.get("columns", []))
    fingerprint = Fingerprint(
        digest=str(value.get("digest") or _digest(rows, columns)),
        rows=rows,
        columns=columns,
    )
    return Template(
        contract_hash=str(value["contract_hash"]),
        fingerprint=fingerprint,
        map={
            str(path): _field_map_from_dict(item)
            for path, item in value.get("map", {}).items()
        },
        items={
            str(path): ItemMap(
                columns={
                    str(prop): str(role)
                    for prop, role in item.get("columns", {}).items()
                },
                stop_labels=tuple(str(label) for label in item.get("stop_labels", [])),
                start_labels=tuple(
                    str(label) for label in item.get("start_labels", [])
                ),
            )
            for path, item in value.get("items", {}).items()
        },
        absent=tuple(str(path) for path in value.get("absent", [])),
        unlocated=tuple(str(path) for path in value.get("unlocated", [])),
        version=int(value.get("version", 1)),
        created_at=str(value.get("created_at", "")),
        updated_at=str(value.get("updated_at", "")),
    )


def list_templates(
    contract: str, *, directory: Path | str | None = None
) -> list[Template]:
    """Variantes registradas para una tipología; ignora ficheros corruptos."""
    folder = _contract_dir(contract, directory)
    if not folder.is_dir():
        return []
    templates: list[Template] = []
    for path in sorted(folder.glob("*.json")):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            template = template_from_dict(value)
        except (OSError, ValueError, KeyError, TypeError):
            continue
        if template.contract_hash == contract:
            templates.append(template)
    return templates


def all_templates(*, directory: Path | str | None = None) -> list[Template]:
    """Todas las variantes de todas las tipologías del directorio."""
    root = template_dir(directory)
    if not root.is_dir():
        return []
    templates: list[Template] = []
    for folder in sorted(root.iterdir()):
        if folder.is_dir():
            templates.extend(list_templates(folder.name, directory=directory))
    return templates


def find_templates(prefix: str, *, directory: Path | str | None = None) -> list[Template]:
    """Variantes cuyo digest empieza por ``prefix``."""
    return [template for template in all_templates(directory=directory) if template.digest.startswith(prefix)]


def drop_template(template: Template, *, directory: Path | str | None = None) -> Path:
    """Elimina el fichero de la variante (el histórico no se toca)."""
    path = _template_path(template.contract_hash, template.digest, directory)
    path.unlink()
    return path


def save_template(
    fingerprint: Fingerprint, template: Template, *, directory: Path | str | None = None
) -> Template:
    """Guarda la variante; si ya existe, versiona y archiva la anterior."""
    path = _template_path(template.contract_hash, fingerprint.digest, directory)
    path.parent.mkdir(parents=True, exist_ok=True)

    version = 1
    created = _now()
    if path.is_file():
        try:
            previous = template_from_dict(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError, KeyError, TypeError):
            previous = None
        if previous is not None:
            version = previous.version + 1
            created = previous.created_at or created
            history = path.parent / "history"
            history.mkdir(parents=True, exist_ok=True)
            (history / f"{fingerprint.digest}.v{previous.version}.json").write_text(
                json.dumps(template_to_dict(previous), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

    saved = Template(
        contract_hash=template.contract_hash,
        fingerprint=fingerprint,
        map=template.map,
        items=template.items,
        absent=template.absent,
        unlocated=template.unlocated,
        version=version,
        created_at=created,
        updated_at=_now(),
    )
    path.write_text(
        json.dumps(template_to_dict(saved), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return saved


def _similar(left: str, right: str) -> bool:
    return SequenceMatcher(None, left, right).ratio() >= 0.9


def _sequence_coverage(document: list[str], stored: list[str]) -> float:
    if not stored:
        return 0.0
    matcher = SequenceMatcher(None, stored, document)
    matched = sum(block.size for block in matcher.get_matching_blocks())
    return matched / len(stored)


def score_template(blocks: list[LayoutBlock], template: Template) -> float:
    """Similitud estructural de un documento con una variante (0..1)."""
    labels: list[str] = []
    for item in template.map.values():
        for label in item.labels:
            normalized = normalize_label(label)
            if normalized and normalized not in labels:
                labels.append(normalized)
    for item in template.items.values():
        for label in (*item.start_labels, *item.stop_labels):
            normalized = normalize_label(label)
            if normalized and normalized not in labels:
                labels.append(normalized)
    if not labels:
        return 0.0

    fingerprint = signature(blocks, labels)
    if fingerprint is not None and fingerprint.digest == template.digest:
        return 1.0

    document = [
        normalize_label(block.text)
        for block in blocks
        if block.text.strip()
    ]
    sequence = [row.label for row in fingerprint.rows] if fingerprint else []
    wanted = set(labels)
    stored_rows = [row for row in template.fingerprint.rows if row.label in wanted]
    stored_sequence = [row.label for row in stored_rows]
    sequence_coverage = _sequence_coverage(sequence, stored_sequence)

    x_coverage = 0.0
    if fingerprint is not None and stored_rows:
        stored = {(row.page, row.label): row for row in stored_rows}
        hits = 0
        for row in fingerprint.rows:
            reference = stored.get((row.page, row.label))
            if reference is not None and reference.x_band == row.x_band:
                hits += 1
        x_coverage = hits / len(stored_rows)

    sources = {item.source for item in template.map.values() if item.source}
    if sources:
        document_sources: set[str] = set()
        for row in group_rows([block for block in blocks if block.text.strip()]):
            detected = detect_columns(row)
            if detected:
                document_sources.update(detected)
        column_coverage = len(sources & document_sources) / len(sources)
        coverage = (
            SCORE_LABELS * sequence_coverage
            + (1.0 - SCORE_LABELS - SCORE_COLUMNS) * x_coverage
            + SCORE_COLUMNS * column_coverage
        )
    else:
        coverage = 0.8 * sequence_coverage + 0.2 * x_coverage

    # Tolerancia a erratas del OCR en una etiqueta aislada.
    if coverage < MIN_SCORE and sequence and sequence_coverage >= 0.75:
        fuzzy = sum(
            1 for label in labels if any(_similar(label, text) for text in document)
        ) / len(labels)
        coverage = max(coverage, 0.8 * fuzzy + 0.2 * x_coverage)

    return round(min(1.0, coverage), 4)


def best_template(
    blocks: list[LayoutBlock],
    contract: str,
    *,
    directory: Path | str | None = None,
    threshold: float = MIN_SCORE,
) -> tuple[Template, float] | None:
    """Mejor variante para el documento; exige umbral y margen sobre la segunda."""
    candidates = [
        (score_template(blocks, template), template)
        for template in list_templates(contract, directory=directory)
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0], reverse=True)
    best_score, best = candidates[0]
    if best_score < threshold:
        return None
    if len(candidates) > 1 and best_score - candidates[1][0] < MIN_MARGIN:
        return None
    return best, best_score


def _contract_node(contract: dict, path: str) -> dict | None:
    node: Any = contract
    for part in path.split("."):
        properties = node.get("properties") if isinstance(node, dict) else None
        if not isinstance(properties, dict) or part not in properties:
            return None
        node = properties[part]
    return node if isinstance(node, dict) else None


def _hint_node(root: dict, path: str) -> dict | None:
    node: Any = root
    for part in path.split("."):
        properties = node.get("properties") if isinstance(node, dict) else None
        if not isinstance(properties, dict) or part not in properties:
            return None
        node = properties[part]
    return node if isinstance(node, dict) else None


def hint_from_template(template: Template, contract: dict, kind: str = "schema") -> dict:
    """Esquema sintético anotado con el mapa aprendido, para reutilizar ``assign``."""
    paths = leaf_paths_for(contract, kind)
    types = leaf_types_for(contract, kind)
    root: dict[str, Any] = {"type": "object", "properties": {}}
    for path in paths:
        parts = path.split(".")
        node = root
        for part in parts[:-1]:
            properties = node.setdefault("properties", {})
            node = properties.setdefault(
                part, {"type": "object", "properties": {}}
            )
        leaf_type = types.get(path) or "string"
        leaf: dict[str, Any] = {"type": [leaf_type, "null"]}
        learned = template.map.get(path)
        if learned is not None and learned.labels:
            leaf["x-labels"] = list(learned.labels)
            if learned.source:
                leaf["x-source"] = learned.source
            if learned.join_label is not None:
                leaf["x-join-label"] = learned.join_label
        node.setdefault("properties", {})[parts[-1]] = leaf

    for path, item in template.items.items():
        hint_node = _hint_node(root, path)
        contract_node = _contract_node(contract, path)
        if hint_node is None or contract_node is None:
            continue
        hint_node["x-item-columns"] = dict(item.columns)
        hint_node["x-stop-labels"] = list(item.stop_labels)
        if item.start_labels:
            hint_node["x-item-labels"] = list(item.start_labels)
        if "items" in contract_node:
            hint_node["items"] = contract_node["items"]

    return root


def normalize_value(text: str) -> str:
    """Normalización para comparar valores de texto (sin acentos ni puntuación)."""
    decomposed = unicodedata.normalize("NFKD", text)
    plain = "".join(char for char in decomposed if not unicodedata.combining(char))
    plain = plain.casefold()
    cleaned = "".join(char if char.isalnum() else " " for char in plain)
    return " ".join(cleaned.split())
