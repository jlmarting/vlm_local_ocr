# Decisiones de diseño — vlm_local_ocr

El *porqué* del stack y de las normas no evidentes del proyecto. Cada decisión indica el
contexto, la elección y la alternativa descartada. Si alguna decisión te chirría hoy, este
documento es donde se debate; el histórico detallado vive en el CHANGELOG.

> Formato: una decisión, una línea de contexto, la elección y la alternativa que se descartó
> con su motivo.

## 1. `pypdfium2` para PDF, no PyMuPDF

**Contexto.** Leer la capa de texto de un PDF y rasterizar el que no la tiene.
**Decisión.** `pypdfium2` (bindings de PDFium, BSD-3) como única dependencia de PDF.
**Descartada.** PyMuPDF: es AGPL/comercial y no casa con la licencia MIT del proyecto. El dolor
de reescribir ingesta se pagó una vez; el peaje de licencia se pagaría siempre.

## 2. `llama.cpp` + GGUF en CPU, no un servidor de inferencia

**Contexto.** LLM local sin GPU, sin nube, que arranque en un portátil modesto (T480).
**Decisión.** `llama-cpp-python` con GGUF Q4_K_M; carga perezosa solo cuando hay contrato o
`--prompt`.
**Descartada.** vLLM/Ollama local como servidor permanente: más proceso, más puertos, más
supervisión. La nube sigue existiendo (`OllamaRunner`) pero como segunda vía declarada, no como
impedimento.

## 3. RapidOCR/ONNX Runtime para el OCR

**Contexto.** OCR offline en CPU con idiomas latinos incluidos.
**Decisión.** RapidOCR v3 (det+cls+rec sobre ONNX Runtime), ~31 MB de modelos.
**Descartadas.** Tesseract (frágil con scans reales y tablas) y EasyOCR (dependencias pesadas de
PyTorch para un CLI de CPU). RapidOCR acertó el equilibrio coste/precisión.

## 4. Contrato por ejemplo **o** JSON Schema, autodetectado por `$schema`/flag

**Contexto.** El usuario puede traer un ejemplo de payload o un schema formal.
**Decisión.** Si trae `$schema`/`$defs` (o `--contract-kind schema`), es schema estricto; si no,
el ejemplo se usa como forma con tipos y se valida recursivamente (arrays por unión, `null` como
nullable, claves extra prohibidas).
**Descartada.** Detectar «por la clave `type`»: `{"type": "factura"}` es un payload válido, no un
schema. La autodetección por contenido era caja de Pandora; la explícita (`--contract-kind`) es
una línea.

## 5. Anotaciones `x-*` en el schema para el extractor determinista

**Contexto.** Mapear texto OCR a campos sin LLM cuando la disposición es predecible.
**Decisión.** `x-labels` (etiquetas del documento) y `x-source` (columna) viven **en el propio
JSON Schema**; de ahí se generan prompt, serialización por filas y gramática.
**Descartada.** Un fichero de mapeo aparte (YAML/JSON): entonces el contrato y la calibración
viven en dos sitios y se desincronizan. El estándar permite `x-*` justo para esto; ignorarlo
sería reinventar el sidecar.

## 6. Gramática, validación y verificación son tres capas distintas

**Contexto.** «El JSON salió» no significa «el JSON dice la verdad».
**Decisión.** (a) Gramática GBNF fuerza la forma; (b) validación recursiva fuerza el contrato;
(c) `verify.literal_errors` comprueba que cada valor aparece literal en el texto (números,
fechas por valor, horas por dígitos, strings normalizados, listas).
**Descartada.** Confiar en que la gramática ya implica fidelidad: medido en el benchmark, un
modelo con gramática perfecta devuelve valores de la fila equivocada. La forma no es el valor.

## 7. Contratos anotados primero, LLM como fallback

**Contexto.** En documentos estructurados (nóminas, pedidos de clientes) la geografía es predecible.
**Decisión.** El **determinista** intenta primero (`extract.assign` + plantillas homologadas);
el LLM solo rellena los campos `pending`/`unlocated`. `--no-llm` apaga el fallback.
**Descartada.** «Que el LLM lo haga todo»: 0–2 de 24 campos con texto en columnas, ~100 s por
documento. El determinista logra 24/24 en ~0,1 s en este caso. No es «mejor modelo»: es mejor
canal.

## 8. Catálogo de modelos en el wheel, overlay de usuario encima

**Contexto.** Alias (`llama32-3b`), descarga verificada, licencias, perfiles.
**Decisión.** `src/vlm_ocr/catalog.json` **viaja en el paquete** y el usuario lo sobreescribe
solo en `<config>/vlm-local-ocr/catalog.json` (mismo alias → gana el del usuario).
**Descartada.** Un registro central en red o un fichero de usuario sin paquete: entonces
instalar el CLI no te deja listo para nada. Llevar el catálogo dentro es «baterías incluidas»
con una puerta para tus propios modelos.

## 9. El paquete solo lleva modelos realmente redistribuibles

**Contexto.** Licencias de pesos heterogéneas (MIT, Apache-2.0, Llama Community, qwen-research).
**Decisión.** `scripts/build_release.sh` empaqueta solo los `redistributable: true` con sus
textos de licencia; Qwen2.5-3B y los remotos quedan fuera y se descargan aparte.
**Descartada.** Incluirlo todo: un solo modelo con licencia no redistribuible contamina todo el
paquete. El script lo comprueba por catálogo, no por lista a mano.

## 10. Rutas por plataforma sin `platformdirs`

**Contexto.** Datos (plantillas, modelos) y config en el lugar que espera cada SO.
**Decisión.** `paths.py` resuelve `data_dir()`/`config_dir()` con `platform`, `env` y `home`
inyectables, con guarda de compatibilidad (prefiere el directorio antiguo con contenido).
**Descartada.** `platformdirs`: resuelve más casos raros de Windows antiguo, pero añade una
dependencia para 20 líneas propias y, lo que es peor, deja la guarda de compatibilidad fuera. La
función inyectable además hace los tests triviales: simular un Windows es `data_dir("win32",
env, tmp_home)`, no una VM.

## 11. Métricas opt-in y siempre por stderr

**Contexto.** Saber cuánto cuesta cada documento sin ensuciar la salida.
**Decisión.** `--metrics` escribe el informe JSON en **stderr** (stdout intacto para pipes) y
`--metrics-out` en fichero. Nada se mide por defecto ni con coste apreciable.
**Descartada.** Métricas mezcladas en stdout: rompe `vlm-ocr doc.pdf | jq .` y todo pipeline de
verdad. La regla «stdout es el producto, stderr es el taller» no se negocia.

## 12. Columnas libres en listas (`x-item-columns` como rol u objeto)

**Contexto.** Los roles de ticket (`text`/`quantity`/`number_right`/`observation`) no representan tablas con columnas propias (fecha, concepto, importe, saldo).
**Decisión.** `x-item-columns` acepta el rol legacy o un objeto `{x0, x1, type, required}` con rangos 0–1 relativos a la región de la lista (filas de datos). Las columnas libres requieren `x-item-labels` (cabecera); la extracción asigna cada celda por el centro x normalizado y coacciona por tipo. No se mezclan roles y columnas en el mismo array.
**Descartada.** Rangos absolutos en píxeles (frágiles a escala y márgenes) y una anotación nueva (`x-item-table`) que fragmentaría el formato; el objeto en la misma clave mantiene compatibilidad.

## 13. Modelos remotos visibles en la SPA, nunca por defecto

**Contexto.** El CLI ya soporta modelos ollama; la SPA solo mostraba locales. El usuario quiere ver `cloud-deepseek`.
**Decisión.** `/api/models` lista también los remotos con `remote`, `available` y `key_env`; se pueden usar si `OLLAMA_API_KEY` está en el entorno del servidor. La UI avisa de que el documento sale de la máquina y nunca selecciona un remoto por defecto.
**Descartada.** Ocultarlos (el usuario pidió verlos) y usarlos por defecto (rompe la promesa local del proyecto).

---

**Cómo se añade una decisión.** Cuando una ronda cierre una decisión de arquitectura que no sea
obvia en el código, añade aquí una sección con el mismo formato y enlaza el commit/PR. No todas:
solo las que un revisor podría intentar revertir por desconocer el porqué.
