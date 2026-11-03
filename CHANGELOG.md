# Changelog

Todos los cambios notables de este proyecto se documentan aquí.

El formato sigue [Keep a Changelog](https://keepachangelog.com/es/1.1.0/)
y este proyecto se adhiere a [Semantic Versioning](https://semver.org/lang/es/).

## [Unreleased]

### Added

- SPA: «Proponer contrato» con un LLM local — propone campos, etiquetas, columnas y listas a partir del texto extraído, con validación, filtro de literalidad y revisión humana obligatoria. Modelos locales (`llama32-3b` recomendado). Endpoints `GET /api/models` y `POST /api/workspaces/{id}/propose`.
- SPA: editor de listas repetidas (`x-item-columns`): roles texto/cantidad/importe/observación, etiquetas de inicio y fin, tabla de artículos y reconstrucción desde el contrato guardado. El extractor aplica los roles a todas las filas; no se selecciona artículo por artículo.
- Servidor local `vlm-ocr serve` (extra `[serve]`: `fastapi`, `uvicorn`, `python-multipart`): SPA bilingüe ES/EN para arrastrar documentos, ver texto y cajas, construir contratos anotados, extraer en determinista, exportar schema/resultado/texto y homologar plantillas. Escucha solo en loopback con token efímero; workspaces persistentes con recientes.
- Listas repetidas en tickets: `x-item-columns`, `x-stop-labels` obligatorio, `cantidad`, observaciones unidas con espacio + salto de línea, extractor determinista, stop de pagos, fallback al LLM y verificación de precios. Plantillas/homologación por línea (`ItemMap`) con 0 tokens. Ejemplo: `examples/contrato-ticket.schema.json`.
- Modo `--prompt` con LLM sin contrato: tarea libre sobre el texto, excluyente con `--contract`, modelo explícito y salida md (respuesta) o json (`text` + `answer`); sin gramática ni verificación literal.
- Texto plano como documento: ficheros `.txt` y `--input-format txt|text` por stdin. Se decodifica en UTF-8 estricto (BOM tolerado), no pasa por OCR y cada línea no vacía es un bloque; vacío o no UTF-8 es error.
- Entrada por stdin (`-`) para el documento, `--contract` y `--instructions`, con detección del tipo de documento por firma y `--input-format` de rescate. Sin APIs POSIX: la misma ruta sirve en Linux, macOS y Windows. Como máximo una entrada puede ser `-` por invocación.
- `parse_number` acepta moneda (`$`, `€`, `£`, `¥` y códigos ISO): los importes con símbolo se leen, se asignan y se homologan (`$29.35` → `29.35`).
- Un valor con etiqueta encontrada pero no legible pasa a `pending` y se pide al LLM; los campos sin etiqueta siguen considerándose ausentes y no disparan el modelo.

- Guardas de homologación: `--homologate` no guarda si quedan campos sin localizar (salvo `--homologate-partial`), `--homologate-report PATH` escribe el mapa aprendido sin persistirlo, y `vlm-ocr templates list|show|drop` gestiona variantes.
- Métricas honestas: `template.fields_mapped`/`fields_unlocated`/`blocked` y `extract.coverage_contract`/`fields_total`/`fields_filled` (la cobertura de la variante no es la del contrato).
- Literalidad extendida en `verify`: además de números, comprueba fechas (por valor parseado, no por formato), horas (`14:04` ≡ `1404`) y strings normalizados (acentos, mayúsculas, puntuación, saltos de línea), y recorre listas (`pedido[0].producto`). Aviso por defecto; `--strict` bloquea.
- Techo de salida y contexto por entrada del catálogo: `max_tokens` y `think` (tri-estado), `--max-tokens N` como override y `num_ctx` calculado en el proveedor remoto (prompt + techo, mínimo 8.192, capado por `context`). `llm.max_tokens` en el informe de métricas.
- Alias cloud `cloud-deepseek` (`deepseek-v4.1-flash:1017`), que sustituye al placeholder `llama3.2` (id inexistente en `/api/tags`); desactiva el razonamiento con `think: false`.
- Catálogo de modelos (`src/vlm_ocr/catalog.json`, dentro del wheel): alias, tamaño, sha256, licencia, contexto y perfil; overlay de usuario en `~/.config/vlm-local-ocr/catalog.json`.
- `--model` acepta alias del catálogo o ruta `.gguf`; `--profile fast|balanced|quality|extract` elige un modelo local. Precedencia `--model` > `--profile` > defecto (`llama32-3b`), sin caída silenciosa a otro modelo.
- Subcomandos `models list [--json] [--verify]` y `models fetch ALIAS… [--accept-license]`: descarga con `.part`, verificación sha256 y consentimiento de licencia; repos *gated* con `HF_TOKEN`.
- Proveedor remoto ollama (`kind: "ollama"`): API nativa `/api/chat` con structured outputs, `OLLAMA_API_KEY` solo desde el entorno, aviso de privacidad por stderr y `llm.provider` en el informe de métricas.
- Estilo de prompt nativo de NuExtract-1.5-tiny (`prompt_style: "nuextract"`, perfil `extract`).
- `scripts/build_release.sh` empaqueta solo los modelos redistribuibles y sus textos de `licenses/`.

### Changed

- SPA: vista de trabajo a tres columnas en escritorio — ticket a la izquierda, texto reconocido plegable al lado y operativa fija a la derecha; los bloques se colorean por estado (azul seleccionado, verde asignado) con leyenda y tooltip; la pantalla de inicio (recientes y arrastre) queda fuera del área de trabajo.
- SPA: flujo guiado de contratos — barra de acciones sobre el bloque seleccionado (crear campo, inicio/fin de lista), guía de siguiente paso, sugerencias de etiquetas de fin detectadas del documento y vista previa de las líneas de artículo antes de extraer. La vista previa muestra cómo se leerá cada línea (producto, cantidad, importe) con avisos de líneas sin importe, fusionadas o pendientes, y documenta la convención de «cantidad» (número inicial de la línea).
- UI de la SPA: las cajas del visor siguen la imagen real al redimensionar (medición con `getBoundingClientRect` y `ResizeObserver`, sin borde que desplace el overlay); editor de contrato con guía de pasos, banner de selección, «Campo desde el bloque», campos con etiquetas y ayudas, columna desplegable con opción libre, validación de nombres y panel de resultado JSON.
- Rutas por plataforma para plantillas, catálogo de usuario y modelos descargados: `%LOCALAPPDATA%`/`%APPDATA%` en Windows, `~/Library/Application Support` en macOS y XDG en Linux. Si el directorio antiguo (XDG) existe con contenido y el nuevo está vacío, se prefiere el antiguo; las rutas explícitas siguen mandando.
- `scripts/fetch_models.py` acepta alias y, sin argumentos, descarga el modelo por defecto del catálogo (antes descargaba el 0.5B).
- El release ya no copia todos los GGUF de `models/`: Qwen2.5-3B (`qwen-research`) queda fuera.

- Plantillas homologadas (variantes): huella estructural sin valores (solo etiquetas de campo + cabeceras + zonas horizontales relativas), N variantes por contrato, búsqueda por digest exacto o similitud, y `--homologate` para registrar el mapa de una extracción válida. `--templates-dir` y `--no-template`.
- Enrutado determinista con variante: segunda pasada sin LLM (0 tokens); los campos `unlocated` usan un subcontrato y los `absent` quedan `null`; deriva con aviso y caída al LLM.
- `join_label` aprendido por campo (reproduce `GRUPO 3` sin pegar `PEDIDO: 123`) y equivalencia de fechas (`2026-02-02` ≡ `02/02/2026`) al aprender el mapa.
- Métricas `template.found/digest/score/version/coverage/homologated/drift`.
- Contrato JSON Schema anotado: `x-labels` (etiquetas del documento) y `x-source` (columna del valor).
- Asignación determinista sin LLM cuando el contrato está anotado: el modelo solo rellena los campos que no casan y lo determinista gana.
- `--text-format md|rows` (filas automáticas con contrato anotado), `--no-llm` y `--strict`.
- Enderezado y recorte automático de imágenes antes del OCR (perfil de filas, giros de hasta ±30°).
- Etiquetas tolerantes a erratas del OCR (similitud ≥ 0,9 y ganadora clara) y valores verticales alineados por posición, no por orden.
- Aviso de cobertura baja: si se resuelven menos del 75 % de los campos anotados, se avisa (`--strict` falla) en vez de devolver datos plausibles pero falsos.
- Serialización en filas desde PDF nativo (cajas por carácter de PDFium) o desde OCR.
- Bloque `extract` y `verify` en el informe de métricas; `scripts/draft_contract.py` para proponer un contrato anotado.

- Métricas opt-in: `--metrics` (informe JSON a stderr) y `--metrics-out PATH` (fichero). Miden fichero, ingesta, OCR (bloques y confianza real), SLM (modelo, carga, intentos, tokens y velocidad), salida y total, sin alterar stdout ni los exit codes.
- `--n-ctx N`: contexto del modelo en tokens (defecto 4096) para dar aire a prompts grandes.
- El informe de métricas incluye `llm.finish_reason` y se emite también en error e interrupción, con un campo `error` (`kind` + `message`).

### Fixed

- El editor de la SPA envía `"string"` para los campos de tipo texto/fecha (antes `"text"` rompía el JSON Schema) y los errores filtran los `[INFO]` de RapidOCR/ONNX.
- `--with-layout` usa las cajas reales del texto nativo en PDFs con capa de texto (antes devolvía `[0, 0, 0, 0]`), lo que permite pintar el visor de la SPA.
- `--text-format rows` con contrato sin anotar ya no se salta el LLM: la asignación determinista solo corre con anotaciones o variante.
- `_row_blocks` reutiliza los bloques OCR ya calculados en vez de repetir el OCR de las páginas rasterizadas.
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
