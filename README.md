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
```

El modelo por defecto es `Qwen2.5-0.5B-Instruct Q4_K_M` (Apache-2.0). Los modelos OCR por defecto vienen en el wheel de `rapidocr` y funcionan offline.

## Uso

```bash
# Markdown (defecto)
uv run vlm-ocr documento.pdf

# JSON a partir de un ejemplo de payload
uv run vlm-ocr factura.pdf --format json \
  --contract ejemplo.json \
  --model models/qwen2.5-0.5b-instruct-q4_k_m.gguf

# JSON Schema explícito y layout con boxes
uv run vlm-ocr escaneo.jpg --format json --contract schema.json --contract-kind schema \
  --model models/qwen2.5-0.5b-instruct-q4_k_m.gguf --with-layout

# Escribir a fichero
uv run vlm-ocr documento.pdf --out salida.md
```

### Contrato

El contrato puede ser:

- un **JSON Schema** (con `$schema` o `--contract-kind schema`): validación estricta;
- un **ejemplo de datos** (defecto): se valida la forma de forma recursiva (arrays, objetos anidados, `null` como nullable, claves extra prohibidas).

La inferencia se hace con una llamada por documento, `n_ctx=4096` y el texto OCR truncado a ~1500 tokens.

## Rendimiento medido (T480, CPU)

| Caso | Tiempo |
|---|---|
| PDF nativo → Markdown | 1,5 s |
| PDF nativo → JSON de contrato | 6,1 s |
| PDF escaneado → Markdown | 3,2 s |
| PDF escaneado → JSON de contrato | 7,8 s |
| Prefill aislado de 2 500 tokens | 20,6 s |

Las páginas densas (miles de tokens de OCR) pueden superar los 10 s: el prefill en CPU domina. El presupuesto de tokens y el truncado están fijados en código.

## Límites conocidos

- **Orientación**: el clasificador de RapidOCR distingue 0°/180° por línea; páginas giradas 90°/270° no se garantizan.
- **Multicolumna**: el orden es top-down por detección; documentos a varias columnas quedan fuera de v1.
- **Manuscrito, tablas complejas y formularios**: fuera de v1.
- **Idiomas**: el set por defecto cubre chino/inglés/japonés y ~50 lenguas latinas (incl. español); cirílico, árabe, devanagari, etc. requieren modelos adicionales.
- **Fidelidad semántica**: la estructura JSON está garantizada por gramática, pero el modelo de 0.5B puede equivocarse en valores; usa `--model` con uno mayor para contratos exigentes.

## Tests

```bash
uv run pytest -q              # unitarios
uv run pytest -m integration -v  # golden tests con el modelo real
uv run ruff check .
```
