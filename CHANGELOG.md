# Changelog

Todos los cambios notables de este proyecto se documentan aquí.

El formato sigue [Keep a Changelog](https://keepachangelog.com/es/1.1.0/)
y este proyecto se adhiere a [Semantic Versioning](https://semver.org/lang/es/).

## [Unreleased]

### Added

- Contrato JSON Schema anotado: `x-labels` (etiquetas del documento) y `x-source` (columna del valor).
- Asignación determinista sin LLM cuando el contrato está anotado: el modelo solo rellena los campos que no casan y lo determinista gana.
- `--text-format md|rows` (filas automáticas con contrato anotado), `--no-llm` y `--strict`.
- Serialización en filas desde PDF nativo (cajas por carácter de PDFium) o desde OCR.
- Bloque `extract` y `verify` en el informe de métricas; `scripts/draft_contract.py` para proponer un contrato anotado.

- Métricas opt-in: `--metrics` (informe JSON a stderr) y `--metrics-out PATH` (fichero). Miden fichero, ingesta, OCR (bloques y confianza real), SLM (modelo, carga, intentos, tokens y velocidad), salida y total, sin alterar stdout ni los exit codes.
- `--n-ctx N`: contexto del modelo en tokens (defecto 4096) para dar aire a prompts grandes.
- El informe de métricas incluye `llm.finish_reason` y se emite también en error e interrupción, con un campo `error` (`kind` + `message`).

### Fixed

- El reintento del contrato ya no pide `max_tokens` a ciegas: el presupuesto de cada intento se ajusta al contexto que deja el prompt y falla antes de generar si no cabe.
- Una respuesta cortada por el límite de tokens se reporta como truncamiento, no como JSON inválido.
- `Ctrl-C` sale con `130` sin traceback y emite el informe parcial si se pidió.
- `--contract`, `--instructions` y `--model` con `--format md` fallan con `2` en vez de ignorarse en silencio.

## [0.1.0] - 2026-10-30

### Changed

- PDF: se sustituye PyMuPDF (AGPL) por `pypdfium2`/PDFium (permisivo) para mantener el proyecto en MIT.
- Licencia del proyecto: MIT con `LICENSE` y `NOTICE` de terceros.

### Fixed

- Exit codes: contrato/instrucciones/modelo → `2`; entrada/OCR → `1`; PDF corrupto y schema inválido sin traceback.
- Validación `int`: rechaza `1.5` y `"1.5"`; acepta enteros e integrales.
- Revalidación del contrato tras coerción y anclaje; el anclaje `int` ya no trunca.
- Golden test con umbral ≥80 %.
- OCR y sidecar delimitados como datos no confiables frente a prompt injection.

### Added

- CLI `vlm-ocr` con salida Markdown (defecto) y JSON.
- Ingesta de PDFs e imágenes: los PDFs con capa de texto se leen sin OCR; los escaneados se rasterizan a 200 DPI.
- OCR con RapidOCR v3 + ONNX Runtime, con boxes y orden top-down.
- Contrato por ejemplo de payload o JSON Schema (`--contract-kind`), con validación recursiva.
- Inferencia del contrato con `llama.cpp`/GGUF (`llama-cpp-python`), `n_ctx=4096`, truncado de OCR y reintento correctivo.
- Salida `--with-layout` con los boxes del OCR.
- Script `scripts/fetch_models.py` con URL fijada y verificación SHA256.
- Golden tests de fidelidad semántica sobre PDF nativo y escaneado.
- Clave `text` en la salida JSON cuando no se especifica contrato, con `layout` opcional vía `--with-layout`.
- Normalización de números en formato europeo antes de la inferencia.
- El ejemplo de contrato se envía al modelo como forma con tipos (`<string>`, `<number>`), no como valores literales.
- Coerción de strings numéricos inequívocos al tipo numérico del contrato.
- Instrucción al modelo para copiar valores literales y no calcular cifras; `null` aceptado para datos ausentes.
- Anclaje determinista a etiquetas para campos numéricos (`Total: 1895` prevalece sobre un precio unitario).
- Sidecar `*.prompt.md` con instrucciones de ajuste por contrato, autodetectado o vía `--instructions`, con límite de 4 000 caracteres.
- Resolución del modelo por defecto (`models/`, `./models/`, `~/.local/share/vlm-local-ocr/models/`) y script `scripts/build_release.sh` con el GGUF incluido.
- Few-shot mínimo en el prompt para evitar que el modelo reutilice un valor (p. ej. la fecha) en otro campo.
