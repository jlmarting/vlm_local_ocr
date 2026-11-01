# vlm_local_ocr

CLI local para extraer texto de PDFs e imágenes y mapearlo a un contrato JSON, sin servicios en la nube.

- **OCR** con RapidOCR (ONNX Runtime), offline.
- **PDFs con capa de texto** se leen directamente, sin OCR.
- **Contrato** por ejemplo de payload o JSON Schema, inferido con `llama.cpp`/GGUF.
- Pensado para CPU (probado en un ThinkPad T480).

## Requisitos

- Python ≥ 3.11 y [uv](https://docs.astral.sh/uv/).
- `llama-cpp-python` puede requerir toolchain de C++ (cmake/gcc) si no hay wheel prebuilt para tu plataforma.

## Instalación

```bash
uv sync
uv run vlm-ocr models list                                   # catálogo, estado y licencias
uv run vlm-ocr models fetch llama32-3b --accept-license      # ~1,9 GB (modelo por defecto)
# artefacto de distribución con los modelos redistribuibles:
./scripts/build_release.sh
```

Los modelos OCR por defecto vienen en el wheel de `rapidocr` y funcionan offline.

El CLI busca cada GGUF en `models/` del repo, `./models/` o `~/.local/share/vlm-local-ocr/models/`; `--model` acepta un alias del catálogo o una ruta. `--contract`, `--instructions`, `--model` y `--profile` requieren `--format json`: con Markdown el CLI los rechaza con `2` en vez de ignorarlos.

## Modelos: catálogo, alias y perfiles

`src/vlm_ocr/catalog.json` (viaja en el wheel) es la única fuente de verdad: alias, nombre, tamaño, sha256, licencia, contexto y perfil. `vlm-ocr models list` muestra el estado (presente/remoto/—) y con `--verify` comprueba el sha256.

| Alias | Modelo | Tamaño | Licencia | Perfil | En el paquete |
|---|---|---|---|---|---|
| `llama32-3b` | Llama 3.2 3B Instruct Q4_K_M | 1,9 GB | Llama 3.2 Community | `balanced` (defecto) | sí, con su licencia |
| `phi4mini` | Phi-4-mini-instruct Q4_K_M | 2,3 GB | MIT | `quality` | sí |
| `qwen05b` | Qwen2.5-0.5B-Instruct Q4_K_M | 0,5 GB | Apache-2.0 | `fast` | sí |
| `nuextract-tiny` | NuExtract-1.5-tiny Q4_K_M | 0,4 GB | MIT | `extract` | sí |
| `qwen25-3b` | Qwen2.5-3B-Instruct Q4_K_M | 2,0 GB | qwen-research | — | **no** (descarga aparte) |
| `llama32-3b-cloud` | Llama 3.2 3B en ollama | — | Llama 3.2 Community | — | no (API) |

```bash
uv run vlm-ocr models fetch qwen05b                      # descarga verificada (sha256)
uv run vlm-ocr models fetch qwen25-3b --accept-license   # licencia qwen-research: consentimiento
uv run vlm-ocr doc.pdf --format json --contract c.json --model llama32-3b
uv run vlm-ocr doc.pdf --format json --contract c.json --profile fast
```

- Precedencia: `--model` (alias o ruta) > `--profile` > modelo por defecto. Si el defecto no está descargado, **error con hint** (`models fetch llama32-3b`); nunca cae en silencio a otro modelo.
- `--profile` solo resuelve modelos **locales**; lo remoto exige `--model <alias>` explícito.
- Sin `--accept-license` no se descarga un modelo cuya licencia exige aceptación; sin `HF_TOKEN` no se descargan repos *gated*.
- Alias propios: `~/.config/vlm-local-ocr/catalog.json` se fusiona sobre el del paquete (mismo alias → gana el del usuario).
- El paquete solo incluye modelos **redistribuibles**; Qwen2.5-3B (`qwen-research`) queda fuera y se descarga aparte.

### Proveedor remoto (ollama)

```bash
export OLLAMA_API_KEY=...        # https://ollama.com/settings/keys
uv run vlm-ocr doc.pdf --format json --contract c.json --model llama32-3b-cloud
```

Habla el API nativo de ollama (`POST /api/chat`, structured outputs por `format`). Sirve también para un daemon local: pon `base_url` a `http://localhost:11434` en la entrada del catálogo. **Privacidad**: con un alias remoto el texto del documento sale del equipo y se envía a ese endpoint; el CLI lo avisa por stderr. La API key se lee solo de `OLLAMA_API_KEY` (nunca por argumentos) y no se escribe en métricas ni en errores.

## Uso

```bash
# Markdown (defecto)
uv run vlm-ocr documento.pdf

# JSON solo con el texto extraído (sin contrato, sin modelo)
uv run vlm-ocr documento.pdf --format json
# { "text": "..." }

# JSON con texto + boxes del OCR
uv run vlm-ocr escaneo.jpg --format json --with-layout

# JSON a partir de un ejemplo de payload
uv run vlm-ocr factura.pdf --format json \
  --contract ejemplo.json \
  --model models/qwen2.5-0.5b-instruct-q4_k_m.gguf

# JSON Schema explícito y layout con boxes
uv run vlm-ocr escaneo.jpg --format json --contract schema.json --contract-kind schema \
  --model models/qwen2.5-0.5b-instruct-q4_k_m.gguf --with-layout

# Instrucciones de ajuste junto al contrato (autodetectadas)
# Si existe factura.prompt.md, se usa automáticamente
uv run vlm-ocr factura.pdf --format json --contract factura.json \
  --model models/qwen2.5-0.5b-instruct-q4_k_m.gguf

# O un fichero de instrucciones explícito
uv run vlm-ocr factura.pdf --format json --contract factura.json \
  --instructions ajuste.md \
  --model models/qwen2.5-0.5b-instruct-q4_k_m.gguf

# Escribir a fichero
uv run vlm-ocr documento.pdf --out salida.md
```

### Ajuste por contrato (sidecar)

Cada contrato puede llevar su propio fichero de instrucciones:

```
factura.json          # contrato
factura.prompt.md     # ajuste específico (autodetectado)
```

- Se añade como `TASK-SPECIFIC INSTRUCTIONS` **después** de los invariantes (literales, no calcular, JSON, `null`) y antes de la forma y el OCR. No puede desactivarlos.
- `--instructions PATH` tiene prioridad sobre la autodetección.
- Límite: 4 000 caracteres; si se supera, error claro.
- Solo aplica con `--contract`.

### Contrato

El contrato es **opcional**. Si no se indica `--contract`, `--format json` devuelve el texto extraído en `{"text": ...}` (y `layout` con `--with-layout`), sin necesidad de modelo. Si se indica, puede ser:

- un **JSON Schema** (con `$schema` o `--contract-kind schema`): validación estricta;
- un **ejemplo de datos** (defecto): se usa como **forma y tipos** (los valores no se copian) y se valida de forma recursiva (arrays, objetos anidados, `null` como nullable, claves extra prohibidas).

En ese caso se requiere `--model` y la inferencia se hace con una llamada por documento, `n_ctx=4096` (`--n-ctx` lo cambia) y el texto OCR truncado a ~1500 tokens. La respuesta se pide con un presupuesto de tokens que siempre cabe en el contexto; si el modelo corta el JSON, el error lo dice (`respuesta truncada por límite de tokens`) en lugar de fingir un JSON inválido.

El modelo recibe instrucción explícita de **copiar los valores literales** del texto y **no calcular** (nada de sumas, subtotales, porcentajes, medias ni cifras derivadas). Si un dato no aparece escrito, devuelve `null`; la clave del contrato sigue siendo obligatoria.

Para campos numéricos, si el texto contiene la etiqueta del campo (por ejemplo `Total:`), prevalece ese valor literal sobre lo que devuelva el modelo. Así se evita confundir el total con un precio unitario o una cantidad.

## Contrato anotado (JSON Schema)

Un contrato puede anotar cada campo con `x-labels` (etiquetas con las que aparece en el documento) y `x-source` (columna de la que se toma el valor: `unidades`, `importe`, `devengado`, `a_deducir`, `base`, `porcentaje`, `cuota`):

```json
"salario_base": {
  "type": ["number", "null"],
  "x-labels": ["SALARIO BASE"],
  "x-source": "devengado"
}
```

Con un contrato anotado el CLI reconstruye la tabla del PDF **en filas** y asigna los valores **sin LLM**; el modelo solo rellena los campos que no casan (`--no-llm` lo desactiva del todo). El prompt se genera del mapa de campos y `--text-format rows|md` elige la representación. `scripts/draft_contract.py` propone un borrador anotado a partir de un documento.

Medido con las dos nóminas de prueba (contrato de 30 campos): **24/24 campos, 0 tokens y sin incidencias de literalidad**; con el texto en columnas y LLM el mejor resultado era 1/24. La ruta OCR está cubierta por tests de integración con un escaneo sintético en PNG y en PDF sin capa de texto (`tests/integration/test_ocr_rows.py`): el PDF se rasteriza a `--dpi`, la imagen se **endereza y recorta** si llega girada, RapidOCR separa las celdas cuando hay separación horizontal suficiente y el extractor las resuelve igual (con tolerancia a erratas del OCR en las etiquetas). Detalle en `rondas/20261031d-extraccion-fiable/`.

```bash
uv run vlm-ocr nomina.pdf --format json --contract examples/contrato-nomina.json --no-llm --metrics
```

El ejemplo completo (29 campos de una nómina) está en [`examples/contrato-nomina.json`](examples/contrato-nomina.json).

## Plantillas homologadas (variantes)

Un contrato puede recibir documentos de clientes distintos: cambia el membrete, la disposición de los datos o las observaciones, pero la información converge en el mismo contrato. La **tipología** es el contrato (su hash) y cada disposición distinta es una **variante** registrada bajo esa tipología.

- `--homologate` registra la variante al terminar una extracción válida. Solo se guardan las etiquetas que mapean a campos, las cabeceras y las zonas relativas: **nunca valores**. Los campos con valores no literales se excluyen y quedan para el LLM.
- La huella ignora membretes, observaciones y tags: añadir una observación no rompe el reconocimiento.
- En la siguiente pasada, si la variante cubre el documento, **no se carga el modelo** (0 tokens). Si falta algún campo, el LLM recibe solo ese subconjunto; si el layout deriva, se avisa y cae al LLM completo.
- Puede haber **N variantes por contrato** (dos clientes, mismo pedido). Se elige por huella exacta o por similitud estructural (0,85 con margen sobre la segunda).

```bash
# Primera pasada: paga el LLM una vez por variante y la registra
uv run vlm-ocr pedido-cliente-a.png --format json --contract contrato-pedido.json \
  --model llama32-3b --text-format rows --homologate --metrics

# Siguientes pasadas: asignación determinista, sin modelo
uv run vlm-ocr pedido-cliente-a.png --format json --contract contrato-pedido.json --no-llm --metrics
```

Las variantes viven en `$XDG_DATA_HOME/vlm-local-ocr/templates/<hash-contrato>/` (por defecto `~/.local/share/vlm-local-ocr/templates/`); `--templates-dir` lo cambia y `--no-template` las ignora. El informe de métricas añade `template.found/digest/score/version/coverage/homologated/drift`. Si el contrato cambia, su hash cambia y las variantes caducan solas.

## Métricas (opt-in)

`--metrics` emite un informe JSON por **stderr** (stdout intacto) y `--metrics-out PATH` lo escribe a fichero:

```bash
uv run vlm-ocr factura.pdf --format json --contract factura.json --metrics
uv run vlm-ocr documento.pdf --metrics-out metricas.json
```

El informe incluye tamaño, formato y páginas del fichero; tiempos de ingesta, OCR y SLM; páginas nativas y rasterizadas; bloques y confianza media; el **modelo GGUF** usado (`llm.model`, basename), intentos, tokens de prompt/completado/total, velocidad de generación y motivo de parada (`llm.finish_reason`); tamaño de la salida y tiempo total.

```json
{
  "file":   {"path": "factura.pdf", "size_bytes": 53000, "format": "pdf", "pages": 1},
  "ingest": {"time_ms": 12.3, "native_pages": 0, "rasterized_pages": 1, "dpi": 200},
  "ocr":    {"time_ms": 1234.5, "blocks": 8, "mean_confidence": 0.92},
  "llm":    {"enabled": true, "model": "qwen2.5-0.5b-instruct-q4_k_m.gguf",
             "load_time_ms": 800.0, "time_ms": 9000.0, "attempts": 1,
             "prompt_tokens": 500, "completion_tokens": 40, "total_tokens": 540,
             "tokens_per_second": 42.1, "finish_reason": "stop"},
  "output": {"format": "json", "size_bytes": 123},
  "total":  {"time_ms": 10500.0},
  "error":  null
}
```

- Sin `--metrics`/`--metrics-out` no hay salida extra ni coste apreciable.
- En error (exit `1`/`2`) o interrupción (`130`) el informe se emite igualmente, con las etapas medidas y un campo `error` (`kind` + `message`).
- `mean_confidence` se calcula **solo** sobre bloques de páginas rasterizadas (las nativas llevan confianza `1.0` sintética); `null` si no hay OCR real.
- `llm.enabled` indica si el modelo llegó a usarse; `extract` dice cuántos campos se resolvieron sin él.

## Rendimiento medido (T480, CPU)

| Caso | Tiempo |
|---|---|
| PDF nativo → Markdown | 1,5 s |
| PDF nativo → JSON de contrato (3 campos) | 6,1 s |
| PDF escaneado A4 100 DPI → Markdown | 3,2 s |
| PDF escaneado A4 100 DPI → JSON (5 campos) | 13,9 s |
| PDF escaneado 2 págs → JSON (4 campos) | 18,2 s |
| Prefill aislado de 2 500 tokens | 20,6 s |

En A4 escaneado completo el JSON de contrato puede superar los 10 s: el OCR va en 3–5 s y el resto es inferencia. Un contrato con más campos tarda más (y puede disparar un reintento correctivo).

### Contrato de 30 campos (nómina)

Banco reproducible: `scripts/bench_models.py` (mide) y `scripts/score_bench.py` (puntúa contra una
verdad JSON). Misma nómina, contrato, sidecar y gramática; `n_ctx=4096`, `max_tokens=1200`, un
intento; 24 campos verificados contra el PDF.

| Modelo | Texto en columnas (como lo da hoy el CLI) | Texto en filas (prueba de concepto) | Tiempo |
|---|---|---|---|
| Qwen2.5-0.5B Q4 | 0/24 | — | 56 s |
| Phi-4-mini Q4 (MIT) | 1/24 | 18/24 | 111-120 s |
| Qwen2.5-3B Q4 | 1-2/24 | 19/24 | 109-121 s |
| Llama 3.2 3B Q4 | 1/24 | **22/24** | 96-102 s |
| Contrato anotado + `--no-llm` | — | **24/24** | 0,1 s |

`--profile balanced` (defecto), `--profile quality`, `--profile fast` y `--profile extract`
seleccionan los modelos locales equivalentes del catálogo.

Lectura: con el texto tal como lo emite la ruta nativa (todas las etiquetas y después todos los
valores) ningún modelo pasa de 2/24; serializando la tabla en filas, Llama 3.2 3B llega a 22/24.
El cuello de botella es la representación del texto, no el tamaño del modelo.

## Límites conocidos

- **Orientación**: el clasificador de RapidOCR distingue 0°/180° por línea; páginas giradas 90°/270° no se garantizan.
- **Multicolumna**: el orden es top-down por detección; documentos a varias columnas quedan fuera de v1.
- **Manuscrito, tablas complejas y formularios**: fuera de v1.
- **Idiomas**: el set por defecto cubre chino/inglés/japonés y ~50 lenguas latinas (incl. español); cirílico, árabe, devanagari, **coreano**, etc. requieren modelos adicionales. Con `--lang ar`/`--lang ko` el CLI falla con un hint claro; sin `--lang` el OCR devuelve texto incorrecto en silencio.
- **Fidelidad semántica**: el JSON válido está garantizado por gramática; la forma del contrato solo se impone como esquema cuando el contrato es un JSON Schema. Los valores dependen del modelo y, sobre todo, del texto: en tablas (nóminas) el orden del texto nativo puede separar etiquetas y valores, y entonces ningún modelo acierta. Ver «Contrato de 30 campos».
- **Cobertura baja**: si menos del 75 % de los campos anotados se resuelven, se avisa por stderr (`--strict` lo convierte en error). Protege de OCR de baja calidad que devuelve valores plausibles pero falsos: los números salen del texto y pasan la literalidad, aunque estén en la fila equivocada.
- **Asignación determinista**: depende de que las etiquetas lleguen aisladas. El enderezado cubre giros de hasta ±30°; la perspectiva (foto inclinada en un eje) no se corrige.
- **Asignación determinista (etiquetas)**: se toleran erratas del OCR (`ANTIGOEDAD`) si la etiqueta ganadora es claramente la más parecida. Con un escaneo sintético RapidOCR separa las celdas; si la separación entre columnas es pequeña y devuelve la fila entera como un bloque, no hay columnas que cruzar y el campo cae al LLM. Las cabeceras verticales y los totales al pie se resuelven con heurísticas (ventana de filas y unicidad del número), no con una tabla geométrica completa.

## Tests

```bash
uv run pytest -q -m "not integration"   # unitarios
uv run pytest -m integration -v         # golden con el modelo real
uv run ruff check .
```

Banco de modelos (spike, no forma parte de la suite):

```bash
uv run python scripts/bench_models.py --model llama32-3b --doc nomina.pdf \
  --contract contrato.json --instructions prompt.md --out bench.jsonl
uv run python scripts/score_bench.py --bench bench.jsonl --truth verdad.json
```

## Documentación

- [docs/MANUAL.md](docs/MANUAL.md) — manual de uso, contratos, límites y estado de cierre.
- [CHANGELOG.md](CHANGELOG.md) — historial de cambios.

## Licencia

MIT. Ver [LICENSE](LICENSE) y [NOTICE](NOTICE).
