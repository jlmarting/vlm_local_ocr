# LEARN: El pipeline del CLI en cuatro piezas

> Píldora de proyecto: `vlm_local_ocr`. Nivel: junior. Lee esto primero; el resto de píldoras
> ([índice](README.md)) supone que te conoces este mapa.

## Concepto

`vlm-ocr` no es «un programa que hace OCR»: es una línea de montaje de cuatro estaciones. Un
documento entra por la izquierda y sale por la derecha transformado en Markdown o JSON validado.
Cada estación es un módulo con una única responsabilidad, su propio juego de tests y un punto
de métricas donde se le cronometra.

## Por qué es importante

Un pipeline bien cortado hace tres cosas por ti:

1. **Puedes sustituir cualquier estación sin tocar las demás.** Cambiar el motor de OCR solo
   toca `ocr.py`; añadir un proveedor remoto solo toca `llmrun.py` y `promptstyles.py`.
2. **Puedes saltarte estaciones enteras.** Sin contrato, el LLM ni se carga en memoria. No
   cargar 1,9 GB de GGUF «por si acaso» es la diferencia entre 0,1 s y 60 s por documento.
3. **Sabes dónde nació cada error.** Un `exit 1` en la estación de ingesta no se parece en nada
   a un `exit 2` por un flag mal escrito. El pipeline te dice en qué andén poner la maleta.

## Explicación sencilla

Piensa en la línea de empaquetado de una fábrica:

```
CAJA (documento) ─► [1] RECEPCIÓN ─► [2] OCR ─► [3] CONTRATO ─► [4] ENTREGA
                     pypdfium2          RapidOCR     llama.cpp      md | json
```

- **Recepción** (`inputs.py` + `ingest.py`): abre la caja. Si es un PDF que ya lleva el texto
  dentro (capa de texto), lo lee directamente — no hay nada que reconocer. Si es un escaneo o
  una imagen, lo rasteriza a PNG a `--dpi` y lo endereza si viene torcido.
- **OCR** (`ocr.py`): la parte que «mira la foto». RapidOCR devuelve bloques con texto, una
  caja `(x, y, ancho, alto)` y una confianza. Salida: una lista de `LayoutBlock`, no un poema.
- **Contrato** (`contract.py` + amigos): la parte opcional — la fábrica solo la ejecuta si
  pasas `--contract` o `--prompt`. Antes de llamar al modelo, el **extractor determinista**
  intenta resolver el contrato *sin* LLM (coordenadas + etiquetas). Lo que no cuadre cae al
  LLM con una gramática que le obliga a devolver JSON con la forma pedida.
- **Entrega** (`verify.py` + `metrics.py` + `output.py`): antes de despachar, `verify`
  comprueba que cada valor del JSON está escrito de verdad en el documento (literalidad) y
  `metrics` cronometra todo. El producto final sale por **stdout**; los avisos van por stderr.

La regla de oro de la fábrica: **stdout es el producto, stderr es el ruido del taller**. Por
eso puedes hacer `vlm-ocr factura.pdf --format json --metrics | jq .total` sin que el informe
de métricas contamine el pipe.

## Ejemplo práctico

El punto de entrada real (`cli.py::main`, simplificado) enseña el corte de estaciones mejor
que cien diagramas:

```python
def run(args):
    # [1] Recepción: fichero, stdin o texto plano → páginas/imágenes
    pages = ingest.load(args.document, dpi=args.dpi)

    # [2] OCR: páginas sin texto nativo pasan por RapidOCR → bloques con cajas
    blocks = ocr.ocr_pages(pages, lang=args.lang)

    # [3] Contrato (opcional): primero determinista, luego LLM si faltan campos
    if args.contract is not None:
        data = contract.resolve(blocks, args.contract, model_ref=ref, no_llm=args.no_llm)

    # [4] Entrega: verify valida, metrics cronometra, output escribe en stdout
    verify.check(data, blocks_text)      # avisa o falla con --strict
    output.write(data, format=args.format, out=args.out)
```

Observa el orden: **determinista antes que LLM**, **verify antes que output**. Ninguna estación
recorta la anterior.

## Consejo pro

Cuando metas una feature nueva, pregúntate a qué estación pertenece. Si la respuesta es «a dos»,
o bien estás confundiendo responsabilidades, o bien acabas de descubrir que falta una estación.
Y mapea siempre el coste: `--metrics-out depurar.json` te dice qué estación se come el tiempo
antes de que te pongas a optimizar la equivocada.
