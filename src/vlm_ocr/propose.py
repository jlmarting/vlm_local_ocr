from __future__ import annotations

import re
import unicodedata
from typing import Any

from .annotations import SOURCE_ALIASES, normalize_label
from .layout import rows_text
from .types import LayoutBlock

PROPOSAL_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "fields": {
            "type": "array",
            "maxItems": 30,
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "type": {"type": "string"},
                    "labels": {"type": "array", "items": {"type": "string"}},
                    "source": {"type": ["string", "null"]},
                },
                "required": ["name", "type", "labels", "source"],
                "additionalProperties": False,
            },
        },
        "lists": {
            "type": "array",
            "maxItems": 3,
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "text_prop": {"type": "string"},
                    "quantity_prop": {"type": ["string", "null"]},
                    "number_prop": {"type": "string"},
                    "observation_prop": {"type": ["string", "null"]},
                    "start_labels": {"type": "array", "items": {"type": "string"}},
                    "stop_labels": {"type": "array", "items": {"type": "string"}},
                },
                "required": [
                    "name",
                    "text_prop",
                    "quantity_prop",
                    "number_prop",
                    "observation_prop",
                    "start_labels",
                    "stop_labels",
                ],
                "additionalProperties": False,
            },
        },
    },
    "required": ["fields", "lists"],
    "additionalProperties": False,
}

PROPOSAL_INSTRUCTIONS = (
    "Devuelve SOLO un JSON con dos listas: \"fields\" y \"lists\". "
    "Ejemplo para un ticket: "
    '{"fields": [{"name": "total", "type": "number", "labels": ["TOTAL"], '
    '"source": null}], "lists": [{"name": "pedido", "text_prop": "producto", '
    '"quantity_prop": "cantidad", "number_prop": "precio", '
    '"observation_prop": null, "start_labels": [], "stop_labels": ["TOTAL"]}]}. '
    "Ejemplo para una tabla de nómina: "
    '{"fields": [{"name": "salario_base", "type": "number", "labels": '
    '["SALARIO BASE"], "source": "devengado"}, {"name": "irpf", "type": '
    '"number", "labels": ["RETENCION I.R.P.F."], "source": "a_deducir"}], '
    '"lists": []}. '
    "Reglas: "
    "- fields: campos escalares. labels son textos LITERALES que aparecen en el "
    "documento junto al valor. source es una columna de tabla (unidades, importe, "
    "devengado, a_deducir, base, porcentaje, cuota) o null. "
    "- lists: una entrada por cada tabla repetida (ticket, factura). text_prop, "
    "quantity_prop, number_prop y observation_prop son NOMBRES DE PROPIEDAD "
    "(producto, cantidad, precio, observaciones), nunca valores del documento. "
    "quantity_prop y observation_prop pueden ser null. start_labels y "
    "stop_labels son etiquetas literales donde empieza y termina la lista "
    "(TOTAL, SUBTOTAL, IVA...). "
    "- No propongas las cabeceras de la tabla (Concepto, Unidades, Importe, "
    "Devengado, A deducir, Descripción...) como campos; úsalas solo para elegir "
    "source. "
    "- Máximo 20 campos y 2 listas; si hay más, prioriza los más importantes. "
    "- No repitas nombres. No inventes etiquetas. Si no hay listas, "
    'devuelve "lists": []. Los nombres van en snake_case, sin acentos.'
)

VALID_SOURCES = {
    "unidades",
    "importe",
    "devengado",
    "a_deducir",
    "base",
    "porcentaje",
    "cuota",
}

TYPE_MAP = {
    "text": "text",
    "texto": "text",
    "string": "text",
    "str": "text",
    "number": "number",
    "numero": "number",
    "número": "number",
    "float": "number",
    "decimal": "number",
    "integer": "integer",
    "int": "integer",
    "entero": "integer",
    "date": "date",
    "fecha": "date",
}


def _slug(value: Any, fallback: str) -> str:
    text = str(value or "")
    decomposed = unicodedata.normalize("NFKD", text)
    plain = "".join(char for char in decomposed if not unicodedata.combining(char))
    slug = re.sub(r"[^a-z0-9]+", "_", plain.lower()).strip("_")
    return slug or fallback


def _unique(base: str, used: set[str]) -> str:
    candidate = base
    index = 2
    while candidate in used:
        candidate = f"{base}_{index}"
        index += 1
    used.add(candidate)
    return candidate


def _literal_labels(labels: Any, haystack: str) -> list[str]:
    if not isinstance(labels, list):
        return []
    found: list[str] = []
    seen: set[str] = set()
    for label in labels:
        if not isinstance(label, str):
            continue
        needle = normalize_label(label)
        if not needle or needle not in haystack or needle in seen:
            continue
        if not any(char.isalpha() for char in label):
            continue
        seen.add(needle)
        found.append(label.strip())
    return found


def _source(value: Any, allowed: set[str]) -> str:
    if not isinstance(value, str):
        return ""
    key = re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")
    return key if key in VALID_SOURCES and key in allowed else ""


def _header_labels(text: str) -> set[str]:
    headers: set[str] = set()
    for line in text.splitlines():
        cells = [normalize_label(cell) for cell in line.split("|")]
        cells = [cell for cell in cells if cell]
        if sum(1 for cell in cells if cell in SOURCE_ALIASES) >= 2:
            headers.update(cells)
    return headers


def _detected_sources(text: str) -> set[str]:
    found: set[str] = set()
    for line in text.splitlines():
        cells = [normalize_label(cell) for cell in line.split("|")]
        aliases = {
            SOURCE_ALIASES[cell] for cell in cells if cell in SOURCE_ALIASES
        }
        if len(aliases) >= 2:
            found |= aliases
    return found


def _type(value: Any) -> str:
    key = str(value or "").strip().lower()
    return TYPE_MAP.get(key, "text")


def _enabled(value: Any) -> bool:
    return (
        isinstance(value, str)
        and bool(value.strip())
        and value.strip().lower() != "null"
    )


def rows_text_from_ocr(ocr: dict) -> str:
    blocks: list[LayoutBlock] = []
    for raw in ocr.get("blocks") or []:
        if not isinstance(raw, dict):
            continue
        box = raw.get("box") or (0.0, 0.0, 0.0, 0.0)
        try:
            coordinates = tuple(float(value) for value in box)
        except (TypeError, ValueError):
            continue
        if len(coordinates) != 4:
            continue
        blocks.append(
            LayoutBlock(
                page=int(raw.get("page", 0) or 0),
                text=str(raw.get("text", "")),
                confidence=0.0,
                box=coordinates,
            )
        )
    if blocks:
        rendered = rows_text(blocks)
        if rendered.strip():
            return rendered
    return str(ocr.get("text") or "")


def proposal_fields(payload: Any, text: str) -> list[dict]:
    if not isinstance(payload, dict):
        return []
    haystack = normalize_label(text or "")
    allowed_sources = _detected_sources(text or "")
    headers = _header_labels(text or "")
    used: set[str] = set()
    seen_lists: set[tuple] = set()
    result: list[dict] = []

    raw_fields = payload.get("fields")
    if isinstance(raw_fields, list):
        for item in raw_fields:
            if not isinstance(item, dict):
                continue
            labels = _literal_labels(item.get("labels"), haystack)
            if not labels:
                continue
            if all(normalize_label(label) in headers for label in labels):
                continue
            raw_name = str(item.get("name") or "").strip().lower()
            generic = raw_name in {
                "number",
                "quantity",
                "text",
                "string",
                "value",
                "campo",
                "field",
            }
            name = _slug("" if generic or raw_name[:1].isdigit() else raw_name, "")
            if not name:
                name = _slug(labels[0], "campo")
            if name[:1].isdigit():
                name = f"campo_{name}"
            name = _unique(name, used)
            result.append(
                {
                    "kind": "scalar",
                    "name": name,
                    "type": _type(item.get("type")),
                    "labels": labels,
                    "source": _source(item.get("source"), allowed_sources),
                }
            )

    result = result[:20]

    raw_lists = payload.get("lists")
    if isinstance(raw_lists, list):
        for item in raw_lists:
            if not isinstance(item, dict):
                continue
            raw_text = item.get("text_prop")
            raw_number = item.get("number_prop")
            if not isinstance(raw_text, str) or not raw_text.strip():
                continue
            if not isinstance(raw_number, str) or not raw_number.strip():
                continue
            start_labels = _literal_labels(item.get("start_labels"), haystack)
            stop_labels = _literal_labels(item.get("stop_labels"), haystack)
            if not start_labels and not stop_labels:
                continue
            signature = (tuple(start_labels), tuple(stop_labels))
            if signature in seen_lists or len(seen_lists) >= 2:
                continue
            seen_lists.add(signature)
            roles = {
                "text": "producto",
                "quantity": "cantidad" if _enabled(item.get("quantity_prop")) else "",
                "number_right": "precio",
                "observation": (
                    "observaciones" if _enabled(item.get("observation_prop")) else ""
                ),
            }
            raw_list_name = str(item.get("name") or "").strip().lower()
            if raw_list_name in {"", "text_prop", "list", "lista", "items"}:
                list_name = "pedido"
            else:
                list_name = _slug(raw_list_name, "pedido")
            if list_name[:1].isdigit():
                list_name = f"lista_{list_name}"
            name = _unique(list_name, used)
            result.append(
                {
                    "kind": "list",
                    "name": name,
                    "roles": roles,
                    "startLabels": start_labels,
                    "stopLabels": stop_labels,
                }
            )
    return result[:22]
