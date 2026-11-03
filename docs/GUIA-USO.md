# Guía de uso — vlm_local_ocr

Recetas por tarea, de «acabo de instalar» a «he homologado mi plantilla doscientos tickets más
tarde». La referencia profunda (cada flag, cada exit code, cada límite) está en
[MANUAL.md](MANUAL.md); aquí vamos a lo práctico. Si buscas el *cómo funciona por dentro*,
mira [DESARROLLO.md](DESARROLLO.md) y las [píldoras LEARN](learn/README.md).

> **Idea fuerza:** si el documento es predecible (misma plantilla, mismas etiquetas), puedes
> llegar a **0 tokens y ~0,1 s por documento** gracias al extractor determinista y las
> plantillas homologadas. El LLM lo reservas para lo nuevo, lo ilegible y lo raro. Tu portátil
> te lo agradecerá con un ventilador que no suena a despegue.

## Instalación rápida

```bash
git clone <repo> && cd vlm_local_ocr
uv sync
uv run vlm-ocr models fetch llama32-3b --accept-license   # modelo por defecto, ~1,9 GB
```

Comprueba que funciona:

```bash
uv run vlm-ocr --help
```

## Mi primer documento (3 comandos)

```bash
# 1. Solo el texto, Markdown
uv run vlm-ocr documento.pdf

# 2. El texto en JSON (sigue sin tocar el modelo)
uv run vlm-ocr documento.pdf --format json

# 3. Mapeado a un contrato con el modelo por defecto
uv run vlm-ocr factura.pdf --format json --contract mi-contrato.json
```

El paso 3 carga el LLM en memoria (~1,9 GB) y tarda segundos en CPU. Los pasos 1 y 2 son
casi instantáneos. Moraleja: no pagues al LLM si solo quieres leer.

---

## Recetas por tarea

### «Prefiero no tocar la terminal: quiero la SPA»

```bash
uv sync --extra serve
uv run vlm-ocr serve
```

> La SPA es **experimental** y está sujeta a cambios; el CLI base sigue siendo estable.

Arrastra el documento, revisa el texto y las cajas, crea campos y asígnales bloques. «Probar extracción» usa el camino determinista; «Homologar plantilla» guarda la variante. La instalación del CLI sigue siendo técnica; el bundle de escritorio es una fase posterior.

Para tickets o facturas con líneas, usa «Añadir lista»: defines los roles una vez (texto, cantidad, importe, observación) y las etiquetas de fin (`TOTAL`, `IVA`…). No hay que seleccionar cada artículo.

Si no quieres empezar de cero, pulsa «Proponer contrato»: un modelo local propone los campos, etiquetas, columnas y listas; revísalos y ajústalos antes de extraer. `llama32-3b` es la opción recomendada.

Ajusta el espacio con las asas entre columnas y pliega el ticket con «Ocultar ticket». Si quieres preguntar algo al modelo, abre «Prompt del LLM»; también puedes usar ese texto como instrucciones extra al proponer.

### «Quiero el texto de un PDF/imagen y nada más»

```bash
uv run vlm-ocr escaneo.jpg                  # Markdown
uv run vlm-ocr escaneo.jpg --format json    # {"text": "..."}
```

Si el PDF tiene capa de texto (el de la nómina que te descargaste, no el que escaneaste en la
fotocopiadora del 2003), se lee directamente: sin OCR, sin ruido, sin drama. Si no la tiene, se
rasteriza a `--dpi` (200 por defecto) y pasa por RapidOCR.

### «Quiero ver de dónde salió cada palabra»

```bash
uv run vlm-ocr escaneo.jpg --format json --with-layout
```

Cada bloque OCR llega con su caja `(x, y, ancho, alto)` y su confianza. Útil para depurar
por qué el extractor ve `ANTIGÜEDAD` donde el papel dice `ANTIGUEDAD` (sí, pasa; el
extractor tolera esas erratas, ver la receta de contrato anotado).

### «Tengo una factura y un JSON de ejemplo»

Escribe un ejemplo con la forma que quieres (los valores no importan; son disfraz):

```json
{
  "numero_factura": "string",
  "fecha": "string",
  "total": 0,
  "lineas": []
}
```

```bash
uv run vlm-ocr factura.pdf --format json --contract ejemplo.json
```

El modelo recibe la **forma con tipos** y no los valores, así que no le da por copiarte el
cero del ejemplo como total (pasó; ya lo corregimos). Si un dato no está escrito en el
documento, obtienes `null` — `null` significa «no está», no «no sé».

```bash
# Forzar un schema estricto (con $schema/$defs ya se autodetecta)
uv run vlm-ocr factura.pdf --format json --contract schema.json --contract-kind schema
```

### «Una nómina con tabla: quiero 24/24 sin LLM»

Las tablas son el punto donde los SLM lloran: el texto nativo separa etiquetas de valores y el
modelo acaba poniendo el IVA donde iba el salario. La solución no es un modelo más grande: es
un **contrato anotado** que dice dónde vive cada campo:

```json
"salario_base": {
  "type": ["number", "null"],
  "x-labels": ["SALARIO BASE"],
  "x-source": "devengado"
}
```

```bash
uv run vlm-ocr nomina.pdf --format json --contract examples/contrato-nomina.json --no-llm
```

El CLI reconstruye la tabla **por filas** (de las coordenadas OCR) y asigna deterministamente.
Medido en dos nóminas reales de prueba: **24/24 campos, 0 tokens, ~0,1 s**. Los campos que no
casan pasan al LLM; `--no-llm` lo desactiva del todo. Un borrador anotado te lo propone
`scripts/draft_contract.py` sobre un documento de muestra, para no escribir 30 `x-labels`
a mano como un jornalero.

### «Un ticket con una lista de productos»

Los tickets no son fichas: son listas de longitud variable con observaciones sueltas
(`+ Onion`, `- Tomato`). Un `x-item-columns` anota los roles y `x-stop-labels` corta la zona
de pagos:

```bash
uv run vlm-ocr ticket.webp --format json \
  --contract examples/contrato-ticket.schema.json --no-llm
```

`1 Hamburger | 3.60` → item; `+ Onion` se pega al item anterior con `\n`; `TAX`, `CHANGE` y
`TENDER` cortan la lista y nunca se convierten en «producto». Si la cobertura baja del 75 %,
el array pasa a `pending` y decide el LLM: nunca devolvemos `[]` haciéndonos los suecos.

### «La foto vino girada (o el escáner decidió improvisar)»

El enderezado automático corrige giros de hasta ±30° y el recorte quita márgenes. A más ángulo
el OCR empieza a inventarse palabras, y ahí ni nosotros ni el LLM hacemos milagros: escanea de
nuevo. Orientaciones de 90°/270° no están garantizadas (el clasificador distingue 0°/180° por
línea; giró y prefirió no contarlo).

### «Tengo el texto en el portapapeles / no quiero fichero temporal»

```bash
wl-paste -t image/png | uv run vlm-ocr -                       # imagen por stdin
curl -sL https://example.com/factura.pdf | uv run vlm-ocr - --format json
uv run vlm-ocr factura.pdf --format json --contract - < contrato.json
```

- Máximo **una** entrada `-` por invocación (documento, contrato **o** instrucciones).
- En terminal interactiva `vlm-ocr -` falla con exit `2` en vez de quedarse esperándote con
  cara de poker.
- Windows: `type doc.pdf | vlm-ocr -` en CMD. PowerShell toquetea los binarios; redirección
  `< fichero.pdf` es más segura.

### «Ya tengo el texto extraído; saltaos el OCR»

```bash
printf 'cafe 1,20€ coockie 2,2€ total 3,40€' | uv run vlm-ocr - --input-format txt --format json
uv run vlm-ocr nota.txt --format json --contract contrato.json --no-llm
```

Cada línea no vacía es un bloque. `TOTAL | 29.35` se resuelve determinista con contrato
anotado; `total 3,40€` pegado puede necesitar LLM.

### «Solo quiero preguntarle algo al documento, sin contrato»

```bash
uv run vlm-ocr factura.pdf --prompt "resume en 3 líneas" --model qwen05b
uv run vlm-ocr nota.txt --prompt "lista los productos y el total" --model qwen05b --format json
```

`--prompt` exige `--model` explícito y es excluyente con `--contract`. No hay gramática ni
`verify`: la respuesta es prosa libre, así que no bases tu contabilidad en ella. Con `--format
json` la salida es `{"text": ..., "answer": ...}`.

### «Quiero usar la nube (ollama) lo mínimo posible»

```bash
export OLLAMA_API_KEY=...      # https://ollama.com/settings/keys (solo por entorno; jamás por argumento)
uv run vlm-ocr factura.pdf --format json --contract c.json --model cloud-deepseek
```

La API nativa (`/api/chat`) respeta structured outputs; la entrada del catálogo declara
`context`, `max_tokens` y `think`. **Privacidad:** el texto del documento sale del equipo y el
CLI lo dice por stderr — si la nómina es confidencial, quizá no es el día ideal para probar la
nube. Funciona también con un daemon local ollama (cambia `base_url` en tu catálogo de usuario).

## Recetas de operación

### Modelos: ver, descargar, medir

```bash
uv run vlm-ocr models list                    # alias, estado, licencia
uv run vlm-ocr models list --verify           # + sha256 de los presentes
uv run vlm-ocr models fetch qwen05b           # descarga verificada
uv run vlm-ocr models fetch qwen25-3b --accept-license
uv run vlm-ocr models bench llama32-3b --doc nomina.pdf --contract c.json --out bench.jsonl
```

Precedencia: `--model` (alias o ruta) > `--profile fast|balanced|quality|extract` > defecto
(`llama32-3b`). Si el defecto no está descargado, error con hint; nunca te cambian el modelo
por debajo y en silencio, que luego pasa lo que pasa.

Tus propios alias viven en el overlay de usuario `<config>/vlm-local-ocr/catalog.json`
(dónde es `<config>` según tu SO: ver
[rutas por plataforma](MANUAL.md#rutas-por-plataforma)).

### Homologar una plantilla (una sola vez por cliente)

Doscientos tickets del mismo proveedor no merecen doscientas visitas al LLM:

```bash
# Pasada 1: LLM una vez, guarda el mapa etiqueta→campo
uv run vlm-ocr pedido-cliente-a.png --format json --contract contrato-pedido.json \
  --homologate --metrics

# Pasada 2+: 0 tokens
uv run vlm-ocr pedido-cliente-a.png --format json --contract contrato-pedido.json --no-llm

# Antes de fiarte: mira qué se aprendió, sin persistirlo
uv run vlm-ocr pedido-cliente-a.png --format json --contract contrato-pedido.json \
  --homologate --homologate-report mapa.json --metrics-out m.json
```

**La regla de oro: homologa solo extracciones verificadas.** `--homologate` aprende lo que ve,
no lo que es correcto: si el LLM dijo `fecha: "2022"` y era el año de la línea de firma, ese
mapa equivocado quedará fijado para siempre (pasó de verdad, en un ticket In-N-Out). Si quedan
campos sin localizar, la guarda bloquea el guardado; `--homologate-partial` lo fija a propósito.

```bash
uv run vlm-ocr templates list
uv run vlm-ocr templates show <digest>
uv run vlm-ocr templates drop <digest> --yes
```

### Medir todo (y descubrir dónde se va el tiempo)

```bash
uv run vlm-ocr factura.pdf --format json --contract c.json --metrics
uv run vlm-ocr factura.pdf --metrics-out metricas.json
```

El informe (stderr o fichero) trae tiempos por etapa (`ingest`/`ocr`/`llm`), tokens y velocidad
del modelo, confianza media del OCR y `extract.coverage_contract` (cuántos campos se resolvieron
sin LLM). Si algo te huele raro, `--metrics` es tu primera parada, no el rezo.

## Problemas frecuentes

| Síntoma | Causa probable | Solución |
|---|---|---|
| `no hay modelo: usa --model …, --profile … o descárgalo con vlm-ocr models fetch …` | El modelo por defecto no está en disco | `uv run vlm-ocr models fetch llama32-3b --accept-license` |
| 0/24 campos en un contrato grande | Texto en columnas del OCR | Contrato anotado + `--text-format rows` (o `--no-llm`); el modelo no es el cuello de botella, la representación sí |
| JSON «truncado por límite de tokens» | Poco presupuesto | Sube `--max-tokens`; el error es honesto (antes mentía y decía "JSON inválido") |
| `verify` avisa con strings correctos | Paráfrasis legítima del modelo | Aviso (exit 0) por defecto; `--strict` solo si la literalidad es contractual |
| Cobertura baja (<75 %) | OCR de baja calidad / etiquetas no aisladas | Repite el escaneo, sube `--dpi`, mira `--with-layout` |
| `exit 2` sin motivo | Flag inválido o combinación excluyente (`--contract`+`--prompt`) | Mensaje por stderr; un exit 2 es uso, un 1 es procesado, un 130 tú con Ctrl-C |
| `--lang ar` falla al instante | RapidOCR no lleva árabe por defecto y el CLI avisa | Descarga del modelo extra (ver límites en MANUAL) — o evita silencios peores |
| En Windows el pipe `cat` no existe | CMD ≠ Bash | `type doc.pdf \| vlm-ocr -` o redirección `<` |
| `--homologate` no guarda nada | Quedaban campos sin localizar (guarda) | Resuelve el documento primero o confirma con `--homologate-partial` |
| Plantilla no se encuentra tras actualizar | Ruta antigua vs ruta por SO | La guarda prefiere la vieja con contenido; `--templates-dir` lo fuerza (ver rutas por plataforma) |

## Para ir más lejos

- [MANUAL.md](MANUAL.md) — referencia completa (flags, límites, seguridad, estado).
- [DECISIONES.md](DECISIONES.md) — por qué el stack es este y no otro.
- [DESARROLLO.md](DESARROLLO.md) — si vas a tocar el código.
- [learn/](learn/README.md) — píldoras didácticas del stack, para ir de junior a «entiendo qué
  acabo de romper».
