# vlm_local_ocr

CLI local para extraer texto de PDFs e imágenes y mapearlo a un contrato JSON.

- OCR con RapidOCR (ONNX Runtime), offline.
- PDFs con capa de texto se leen directamente (sin OCR).
- Contrato por ejemplo de payload o JSON Schema, inferido con `llama.cpp`/GGUF.
- Pensado para CPU (probado en un ThinkPad T480).

Estado: v1 en construcción. Ver `CHANGELOG.md`.
