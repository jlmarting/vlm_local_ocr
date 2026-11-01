# LEARN: El contrato anotado y el extractor determinista

> Píldora 04 de `vlm_local_ocr`. Nivel: junior. La más rentable del proyecto: te dice cómo se
> pasa de «LLM que inventa» a «0 tokens y 24/24 campos correctos».

## Concepto

Un **contrato anotado** es un JSON Schema donde cada campo lleva metadatos del dominio:
`x-labels` (con qué etiqueta aparece en el documento) y `x-source` (de qué columna se toma).
Sobre esas anotaciones, el **extractor determinista** reconstruye la tabla del OCR por filas
y rellena el contrato *sin tocar el LLM*. Lo que no casa cae al modelo; lo que casa, cero tokens.

## Por qué es importante

Medido con una nómina de 30 campos y cuatro modelos:

| Enfoque | Resultado | Tiempo |
|---|---|---|
| Texto del OCR en columnas + LLM | 0–2 de 24 | ~100 s |
| Texto reordenado en filas + LLM | 16–23 de 24 | ~100 s |
| Contrato anotado + extractor determinista | **24/24** | **~0,1 s** |

La lección que se paga con tokens: **el cuello de botella era la representación del texto, no
el tamaño del modelo**. Cuando el OCR entrega una tabla como «todas las etiquetas y después
todos los valores», ningún 3B humaniza esa sopa; pero con `x-labels` + filas por coordenada no
hace falta entender nada — hay que casar coordenadas.

Además, generar prompt, gramática y validación **desde las anotaciones** (en vez de escribir
prosa a mano) hace del contrato la única fuente de verdad: editas `x-labels` y el prompt del
LLM, el determinista y el golden test se actualizan a la vez.

## Explicación sencilla

Piensa en un formulario de aduana con casillas. El contrato plano dice «qué quiero». El
contrato anotado añade «dónde lo miro» con flechas:

```json
"salario_base": {
  "type": ["number", "null"],
  "x-labels": ["SALARIO BASE"],
  "x-source": "devengado"
}
```

El extractor actúa como un empleado con una regla y un rotulador, cuatro pasos:

1. `layout.group_rows` reagrupa los bloques OCR en **filas por coordenada Y**.
2. Busca en cada fila la celda que contiene una etiqueta de `x-labels` (tolerando erratas del
   OCR si la más parecida es inequívoca — `ANTIGOEDAD` casa con `ANTIGUEDAD`).
3. En la *misma fila* busca la celda de la **columna** `x-source` (ej. `devengado`) y coacciona
   (`parse_number` acepta `1.895,34 €` con moneda y miles latinos).
4. Si encuentra etiqueta pero no valor, marca `pending` y deja ese campo para el LLM; si no hay
   etiqueta, el campo es **ausente** (`null`) y no dispara al modelo.

Moraleja: ningún LLM rellenó la casilla. El «modelo de lenguaje» aquí es una regla con regla.

## Ejemplo práctico

De `src/vlm_ocr/extract.py`, el corazón del determinista:

```python
def assign(blocks: list[LayoutBlock], schema: dict) -> Assignment:
    """Mapa etiqueta→valor desde filas reagrupadas. Devuelve también los campos pendientes."""
    hints = leaf_hints(schema)               # campos anotados con x-labels/x-source
    rows = group_rows(blocks)                # de píxeles a filas legibles
    for row in rows:
        label = _closest_label(row.text, known_labels)   # tolera la errata del OCR
        if label:
            value_cell = _cell_under(row, span_of_column(hints[label]))
            set_value(label, parse_number(value_cell.text))      # "1.895,34 €" → 1895.34

def parse_number(raw: str) -> float | None:
    """Acepta moneda y formatos latinos; devuelve None si no es inequívoco."""
    ...
```

Ejecutable en cinco segundos:

```bash
scripts/draft_contract.py nomina-ejemplo.pdf --out borrador.json   # propone los x-labels
uv run vlm-ocr nomina.pdf --format json --contract borrador.json --no-llm --metrics
```

Mira `extract.coverage_contract` en las métricas: si está en 1.0, el LLM ni arrancó.

## Consejo pro

- El determinista es tan bueno como tus etiquetas: un `x-labels` mal escrito falla y la forma de
  detectarlo no es «más prompt», es la verificación de literalidad (píldora 06) contándote
  `verify.literal_errors`.
- Los campos sin etiqueta no se piden al modelo: quedan `null`. Si necesitas «todo lo que no
  tengo etiquetado me lo rellena el LLM», ese comportamiento vive en el fallback, no en el
  determinista — y con un `pending` honesto, no con un silencio que simula un valor.
- La cobertura mínima real es 75 %: por debajo, el documento entero pasa al LLM (aviso por
  stderr). Si caes ahí a menudo, tu OCR está fusionando columnas — vuelve a la píldora 02 y
  sube `--dpi`.
