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
uv run python scripts/fetch_models.py   # descarga y verifica el GGUF (~491 MB)
# artefacto de distribución con el modelo incluido:
./scripts/build_release.sh
```

El script descarga `Qwen2.5-0.5B-Instruct Q4_K_M` (Apache-2.0). Los modelos OCR por defecto vienen en el wheel de `rapidocr` y funcionan offline.

El CLI busca el GGUF por defecto en `models/` del repo, `./models/` o `~/.local/share/vlm-local-ocr/models/`; `--model` lo sobrescribe. `--contract`, `--instructions` y `--model` requieren `--format json`: con Markdown el CLI los rechaza con `2` en vez de ignorarlos. `scripts/build_release.sh` genera un artefacto con el modelo incluido.

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
- Sin contrato/modelo, `llm.enabled` es `false` y el resto se mide igual.

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

## Límites conocidos

- **Orientación**: el clasificador de RapidOCR distingue 0°/180° por línea; páginas giradas 90°/270° no se garantizan.
- **Multicolumna**: el orden es top-down por detección; documentos a varias columnas quedan fuera de v1.
- **Manuscrito, tablas complejas y formularios**: fuera de v1.
- **Idiomas**: el set por defecto cubre chino/inglés/japonés y ~50 lenguas latinas (incl. español); cirílico, árabe, devanagari, **coreano**, etc. requieren modelos adicionales. Con `--lang ar`/`--lang ko` el CLI falla con un hint claro; sin `--lang` el OCR devuelve texto incorrecto en silencio.
- **Fidelidad semántica**: la estructura JSON está garantizada por gramática, pero el modelo de 0.5B puede equivocarse en valores; usa `--model` con uno mayor para contratos exigentes.

## Tests

```bash
uv run pytest -q -m "not integration"   # unitarios
uv run pytest -m integration -v         # golden con el modelo real
uv run ruff check .
```

## Documentación

- [docs/MANUAL.md](docs/MANUAL.md) — manual de uso, contratos, límites y estado de cierre.
- [CHANGELOG.md](CHANGELOG.md) — historial de cambios.

## Licencia

MIT. Ver [LICENSE](LICENSE) y [NOTICE](NOTICE).
