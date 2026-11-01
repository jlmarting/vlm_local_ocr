# LEARN: OCR local en CPU con RapidOCR y ONNX

> Píldora 02 de `vlm_local_ocr`. Nivel: junior. Si no sabes qué es un «OCR», quédate: en diez
> minutos lo sabrás usar sin GPU, sin nube y sin miedo.

## Concepto

OCR significa «pasar de píxeles a texto». El mito comercial lo vende como magia de nube; la
realidad práctica de este proyecto es **RapidOCR ejecutando modelos ONNX en tu CPU**, en
offline, por ~31 MB de modelos. `ONNX Runtime` ejecuta el fichero `.onnx` (haces **inferencia**,
no entrenamiento) y RapidOCR lo orquesta en tres pasos: detectar dónde hay texto, enderezar cada
línea si viene girada 0°/180°, y reconocer los caracteres.

## Por qué es importante

Sin esta estación no hay proyecto: todo lo demás (contratos, plantillas, LLM) consume lo que
RapidOCR escupe. Y hay tres verdades aquí que un junior necesita **antes** de escribir código
contra el OCR:

- **El orden no es lectura semántica**: los bloques vienen top-down por detección, no en el
  orden en que los leerías tú. Si asumes orden de lectura, tu extractor mezclará el IVA con el
  salario (pasó de verdad; la solución está en la píldora 04).
- **La confianza no es un capricho**: es tu *guard* para saber si estás leyendo una nómina o el
  posavasos. Un 0,92 medio no se parece en nada a un 0,41. Medirlo (`--metrics`) es tu primer
  diagnóstico.
- **Cada idioma cuesta**: el set por defecto cubre chino/inglés/japonés y ~50 latinas (español
  incluido); árabe o coreano no están y `--lang ar` falla con un hint **porque el silencio sería
  peor** (leería basura con cara de confianza).

## Explicación sencilla

Piensa en RapidOCR como un equipo de tres escáneres de mano en fila:

1. **det** detalla *dónde* hay texto: dibuja rectángulos (cajas) sobre cada palabra o línea,
   como quien marca con resaltador antes de leer.
2. **cls** corrige la postura: decide si cada línea está a 0° o 180° (esa es **toda** su
   sabiduría; 90° no existe en su mundo) y la endereza.
3. **rec** lee: convierte cada caja en caracteres con una probabilidad (`boxes, txts, scores`).

Solo hace una cosa y la hace bien en CPU: ese es el truco. Lo que NO hace es interpretar tablas.
Un PDF de nómina puede ser «una foto con 300 palabras bien leídas y un desastre estructural» —
por eso las píldoras 04 y 05 existen.

## Ejemplo práctico

De `src/vlm_ocr/ocr.py` (las dos funciones que el proyecto invoca realmente):

```python
def ocr_pages(pages: list[PageInput], lang: str = "default") -> list[LayoutBlock]:
    """Raster → bloques. Cada LayoutBlock trae texto, caja (x,y,w,h) y confianza."""
    ...

def deskew(image_png: bytes) -> bytes:
    """Endereza giros de hasta ±30° midiendo cuántas filas salen limpias por ángulo."""
    ...
```

Uso desde `cli.py`:

```python
from vlm_ocr import ocr

blocks = ocr.ocr_pages(pages)          # lista de LayoutBlock
media = sum(b.confidence for b in blocks) / len(blocks)   # guard de calidad
```

Y la guarda de idioma honesta (mejor un error claro que un OCR silencioso yequivocado):

```python
if lang in {"ar", "ko"}:
    raise InputError("ese idioma no va en el set empaquetado; descarga el modelo extra")
```

Las páginas nativas (PDF con capa de texto) **no** pasan por aquí: ya son texto, y ahorrar ese
paso es de las decisiones que más tiempo quitan por documento.

## Consejo pro

Antes de tocar el extractor, mira el OCR con `--with-layout` y guarda las cajas. El 80 % de los
«el LLM lo extrajo mal» que hemos visto eran en realidad **el OCR juntando dos columnas en un
bloque** o una etiqueta con errata (`ANTIGOEDAD`). El determinista tolera las erratas si la
etiqueta es claramente la más parecida (`_closest_label` usa `difflib`) — pero si la caja viene
fusionada, no hay magia que deshaga ese nudo, solo un LLM con el campo como `pending`. Medir
primero, creer después.
