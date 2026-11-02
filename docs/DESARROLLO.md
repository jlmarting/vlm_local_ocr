# Manual del desarrollador — vlm_local_ocr

Para quien edita este código. Si solo quieres *usar* el CLI, estás en el documento equivocado:
[GUIA-USO.md](GUIA-USO.md) (recetas) y [MANUAL.md](MANUAL.md) (referencia). Si quieres aprender
el stack desde junior, antes por aquí: [learn/](learn/README.md).

## Setup de desarrollo

```bash
git clone <repo> && cd vlm_local_ocr
uv sync                      # crea .venv con deps + dev (pytest, ruff)
uv sync --extra serve        # añade FastAPI/uvicorn para la SPA local
uv run pytest -q -m "not integration"   # rápido: unidades
uv run pytest -q                         # todo (los de integración piden modelos reales)
uv run ruff check .
```

- Python ≥ 3.11 (desarrollado con 3.14 en un T480; sí, un portátil con edad de votar).
- Los tests de integración están en `tests/integration/` y marcados `@pytest.mark.integration`:
  `test_golden.py` necesita el modelo por defecto descargado; `test_ocr_rows.py` usa escaneos
  sintéticos que genera ella misma; `test_stdin.py` prueba la entrada por tubería.
- No hay CI aún; tu máquina es la CI. Actúa en consecuencia: PR verde = suite verde + `ruff`
  limpio + CHANGELOG al día.

## El mapa (para no perderse)

22 módulos, ~5.900 líneas, una responsabilidad cada uno. El grafo de dependencias manda: si
«no estás seguro de dónde ponerlo», probablemente es porque estás creando una dependencia
circular y el grafo te está haciendo un favor.

| Módulo | Responsabilidad | Lo usan |
|---|---|---|
| `cli.py` | argparse, orquestación de las etapas, subcomandos `models`/`templates`, exit codes | (entrada) |
| `inputs.py` | stdin (`-`), firma del documento, texto plano `.txt`/`--input-format txt` | `cli` |
| `ingest.py` | PDF: capa de texto directa con `pypdfium2`; si no, rasteriza a `--dpi`; endereza | `cli`, `bench` |
| `ocr.py` | RapidOCR/ONNX: detección, clasificación 0°/180°, reconocimiento; confianza | `cli`, `bench` |
| `layout.py` | agrupa bloques OCR en filas por coordenada Y | `cli`, `extract`, `homologate`, `templates` |
| `annotations.py` | `x-labels`/`x-source`/`x-item-columns`: campos, etiquetas normalizadas, tipos hoja | `extract`, `homologate`, `promptstyles`, `templates`, `verify` |
| `extract.py` | el extractor determinista (sin LLM): mapa etiqueta→valor desde filas | `cli`, `homologate`, `templates`, `verify` |
| `homologate.py` | `--homologate`: aprende el mapa de una extracción válida, guardas y `--homologate-report` | `cli` |
| `templates.py` | variantes por contrato: huella estructural, N variantes, enrutado, `list\|show\|drop` | `cli`, `homologate` |
| `contract.py` | carga/parse del contrato (ejemplo/schema), validación recursiva, coerción, gramática | `cli`, `bench` |
| `promptstyles.py` | construye el prompt por proveedor: `chat` + gramática, `nuextract` (sin gramática), free prompt, repair | `contract`, `bench`, `cli` |
| `llmrun.py` | runners: `LocalRunner` (llama.cpp/GGUF) y `OllamaRunner` (API `/api/chat`) — interfaz común | `contract`, `bench` |
| `catalog.py` | el catálogo (`catalog.json` en el wheel + overlay de usuario), descarga con sha256 | `cli`, `contract`, `llmrun`, `bench` |
| `paths.py` | resolución por plataforma de datos/config con guarda de compatibilidad | `catalog`, `templates` |
| `verify.py` | literalidad: números, fechas por valor, horas, strings normalizados, listas | `cli` |
| `metrics.py` | informe opt-in: tiempos por etapa, tokens, confianza, coberturas honestas | `cli` |
| `output.py` | escritura md/json a stdout/--out | `cli`, `bench` |
| `types.py` | `LayoutBlock` y poco más (tipos compartidos) | casi todos |
| `errors.py` | jerarquía `VlmOcrError → InputError | ContractError | ...` | casi todos |
| `bench.py` | `models bench`: un documento, un modelo, JSONL con métricas (spike) | `cli` |
| `server.py` | servidor local (FastAPI/uvicorn) y API de la SPA; extra opcional `[serve]` | `cli` |
| `workspace.py` | persistencia de workspaces (documento, contrato, resultado, recientes) | `server` |
| `serve_layout.py` | render de páginas y normalización de cajas nativas/OCR | `server` |
| `web/` | SPA estática (HTML/CSS/JS, locales ES/EN) servida por `server.py` | `server` |

## El pipeline, en una vista

```
argv ──► cli.parse ──► inputs (stdin? firma? txt?) ──► ingest (capa de texto | raster)
                                                          │
          ┌───────────────────────────────────────────────▼─────────────────────────────┐
          │  ¿contrato anotado?                                                          │
          │   ├─ sí ─► templates.find (¿variante?) ─► extract determinista (layout+annot) │
          │   │           └─ faltan campos ─► subcontrato al LLM ──────────────────┐      │
          │   └─ no ─► contract.load ─► promptstyles.build (por proveedor) ─────────┤     │
          │                                                                        ▼      │
          │                       llmrun.complete (Local | Ollama) ─► contract.validate   │
          └───────────────────────────────────────────────┬───────────────────────────────┘
                                                           ▼
                    verify (literalidad) ─► metrics (stderr) ─► output (stdout)
```

Reglas inmutables que el código asume: **stdout es solo para el resultado** (avisos y métricas
por stderr), **el LLM nunca se carga si no hace falta** (`--no-llm`, variante completa, sin
contrato), **un campo sin etiqueta es ausente** (`null`), no «pide al modelo lo que no existe».

## Cómo extender sin romper

### Añadir un modelo al catálogo

1. Edita `src/vlm_ocr/catalog.json`: alias, `kind`, fichero/URL, `size_bytes`, `sha256`,
   licencia, `redistributable`, `context`, `prompt_style`, perfil (opcional).
2. Verifica el sha256 del GGUF real (`sha256sum`); el CLI lo comprueba tras la descarga.
3. Test del alias en `tests/test_catalog.py`: carga del JSON y resolución (`resolve`).
4. Marca `redistributable: false` si la licencia no lo permite: el release lo excluye solo.

### Añadir un proveedor (runner)

1. `llmrun.py`: implementa la interfaz de `Runner` (`complete`, `estimate_tokens`); mira
   `OllamaRunner` como molde.
2. `promptstyles.py`: añade el estilo si el proveedor habla distinto (`build_prompt` elige).
3. `catalog.py`: nuevo valor en la tupla `KINDS` → `ModelEntry`/`_entry_from()` lo validan y
   documenta el esquema de esa entrada.
4. Seguridad: key solo por entorno (como `OLLAMA_API_KEY`), aviso de privacidad por stderr,
   y **nunca** la clave en métricas ni errores.

### Añadir un comando al CLI

1. `cli.py`: subparser (mira `_templates_parser()`); exit codes fijos: `0` ok, `1` procesado,
   `2` uso/validación, `130` interrupción.
2. **Test-first es el contrato de la casa**: escribe el test CLI en `tests/test_cli_*.py` antes
   de implementar (los subcomandos `models` y `templates` nacieron así y aún se lo agradecen).
3. Documenta en README + MANUAL + CHANGELOG en el mismo PR.

### Añadir una anotación de contrato (`x-*`)

1. `annotations.py` la entiende (normaliza, valida alias).
2. `extract.py` le da semántica determinista si procede.
3. `promptstyles.py` la añade al mapa de campos del prompt cuando el LLM la necesita.
4. Tests: `test_annotations.py`, `test_extract_items.py` y un ejemplo en `examples/`.

## Convenciones (no negociables)

- **Test-first en el CLI**: `--flag` nueva sin test rojo previo es un bug de proceso, no una feature.
- **ruff** a 100 columnas, siempre limpio antes de PR.
- **Español del proyecto**: código e identificadores en inglés; mensajes al usuario, docs y
  commits en español, con hint accionable (`no hay modelo:… descárgalo con vlm-ocr models fetch …`).
- **Commits**: `feat|fix|docs|test|refactor|chore`, imperativo, minúsculas, una cosa por commit.
- **CHANGELOG**: toda conducta observable entra en `[Unreleased]` (Keep a Changelog + semver).
- **YAGNI armado**: si no está en una ronda/propuesta, no se construye. El scope creep muere aquí.
- **Honestidad primero**: un error claro (`respuesta truncada por límite de tokens`) siempre
  mejor que una heurística que simula éxito. `verify` avisa; `--strict` bloquea; nunca miente.

## Release

```bash
./scripts/build_release.sh
```

Genera `dist/vlm-local-ocr-<version>/` con el wheel, `fetch_models.py`, LICENSE/NOTICE/README/
CHANGELOG, el catálogo y **solo los modelos redistribuibles** con sus textos de `licenses/`
(Qwen2.5-3B y lo remoto quedan fuera). Antes de publicar: `uv run pytest -q` verde,
`uv run ruff check .` limpio, CHANGELOG con la versión, tag `vX.Y.Z`.

## Puntos de observación (debug)

| Quieres ver… | Dónde |
|---|---|
| tiempos por etapa, tokens, velocidad, confianza | `--metrics` (stderr) o `--metrics-out fichero.json` |
| qué mapa aprendería `--homologate` | `--homologate-report mapa.json` (escribe y no persiste) |
| por qué el extractor no encontró un campo | `--with-layout` (cajas y confianza del OCR) |
| qué variante casa y con qué score | `metrics.template.found/digest/score/version/coverage` |
| cobertura determinista vs contrato | `extract.coverage_contract` vs `fields_total/fields_filled` |
| gramática que realmente se envió | `promptstyles.schema_from()` y el `response_format` resultante (ojo: `"type": ["number","null"]` degrada en silencio a genérica en llama.cpp; por eso los nulos van con `anyOf`) |

## Enlaces internos

- Referencia de uso: [MANUAL.md](MANUAL.md) · recetas: [GUIA-USO.md](GUIA-USO.md)
- Decisiones y alternativas descartadas: [DECISIONES.md](DECISIONES.md)
- Píldoras didácticas del stack: [learn/](learn/README.md)
- Historial: [../CHANGELOG.md](../CHANGELOG.md)
