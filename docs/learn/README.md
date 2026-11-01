# LEARN — píldoras de vlm_local_ocr

Colección de píldoras didácticas del stack y arquitectura de este repo, escritas para el
desarrollador junior que no ha tocado OCR local, llama.cpp ni un extractor determinista.

**Formato común:** cada píldora tiene Concepto → Por qué es importante → Explicación sencilla
(con símil) → Ejemplo práctico → Consejo pro. Cada una cita el código real (firma + fichero) y
los números medidos en el proyecto.

## Ruta de lectura recomendada

Si llegas aquí sin conocer el proyecto, léelas en orden — cada una supone la anterior:

1. **[01 — El pipeline del CLI en cuatro piezas](01-pipeline-cli.md)** — fábrica de cuatro
   estaciones: ingesta, OCR, contrato opcional, salida. Qué puede saltarse, qué mide cada una.
2. **[02 — OCR local en CPU con RapidOCR y ONNX](02-ocr-local-rapidocr-onnx.md)** — det/cls/rec,
   orden top-down ≠ orden de lectura, confianza como guarda, idiomas y sus límites.
3. **[03 — Un LLM local en CPU: llama.cpp y GGUF](03-llm-local-gguf-llamacpp.md)** — `n_ctx` como
   ventana, prefill como cuello de botella, gramática como formulario y por qué no basta.
4. **[04 — Contrato anotado y extractor determinista](04-contrato-anotado-determinista.md)** —
   `x-labels`/`x-source`, las filas desde coordenadas, 24/24 sin tokens. La que más ROI.
5. **[05 — Plantillas homologadas: la huella sin valores](05-plantillas-homologadas-huella.md)** —
   una extracción válida aprende la forma; la siguiente con esa forma no toca el LLM.
6. **[06 — Verificación de literalidad](06-verificacion-literalidad.md)** — gramática ≠ validación
   ≠ verify; números, fechas y strings comparados por valor, y por qué `null` es honesto.
7. **[07 — Catálogo y rutas por plataforma](07-catalogo-modelos-rutas-plataforma.md)** — alias con
   sha256 y la mudanza invisible entre `~/.local/share` y `%LOCALAPPDATA%`.

## Cuándo consultar cada una

| Si te estás pegando con… | Ve a |
|---|---|
| «No sé por dónde fluye el documento» | 01 |
| «El OCR leyó mal o raro» | 02 |
| «El LLM tarda/inventa/da JSON raro» | 03, 06 |
| «Los campos de una tabla no casan» | 04 |
| «Quiero que la próxima vez sea gratis» | 05 |
| «Un valor bueno suena a inventado» | 06 |
| «¿Dónde se guardan los modelos/plantillas?» | 07 |

Cada píldora es autocontenida: no enlaza a rutas del vault ni supone otro proyecto. Para el
manual de desarrollo (cómo añadir un runner o un comando), [DESARROLLO.md](../DESARROLLO.md).
