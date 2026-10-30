# Changelog

Todos los cambios notables de este proyecto se documentan aquí.

El formato sigue [Keep a Changelog](https://keepachangelog.com/es/1.1.0/)
y este proyecto se adhiere a [Semantic Versioning](https://semver.org/lang/es/).

## [Unreleased]

## [0.1.0] - 2026-10-30

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
- Few-shot mínimo en el prompt para evitar que el modelo reutilice un valor (p. ej. la fecha) en otro campo.
