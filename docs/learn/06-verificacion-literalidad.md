# LEARN: Verificación de literalidad — la gramática no basta

> Píldora 06 de `vlm_local_ocr`. Nivel: junior. La diferencia entre «el JSON salió con forma
> bonita» y «el JSON dice la verdad del documento».

## Concepto

`verify` es el control de calidad que mira el JSON final y comprueba, campo a campo, que el
valor esté **escrito de verdad en el texto OCR**. No en la forma (eso ya lo garantiza la
gramática), no en el sentido (eso es imposible de probar): en la **literalidad**. Números,
fechas, horas y strings, incluidos los elementos de listas, cada uno comparado por valor y
normalizado. Si algo no casa, avisa por stderr (por defecto) o falla con `--strict` (exit 2).

## Por qué es importante

Hay tres capas en este proyecto que un junior tiende a confundir, y cuesta dinero confundirlas:

1. **Gramática (GBNF)**: el JSON existe, tiene tus claves y tus tipos. Perfecto. Y podría estar
   todo inventado.
2. **Validación recursiva** (`contract.validate`): respeta tu contrato (arrays por unión,
   `null` como nullable, claves extra prohibidas). Sigue siendo solo estructura.
3. **Verificación de literalidad**: el valor `1895.34` aparece en el texto como `1.895,34 €`;
   la fecha `02/02/2026` casa con `2026-02-02` por valor, no por formato; el string «café» casa
   con «Café» tras normalizar acentos/mayúsculas/ puntuación.

Sin la tercera capa tienes una máquina de documentos *bien formados y falsos*: el LLM responde
`"total": 100` porque esa clave existe, el JSON valida, el programa está contento, tu contable
no.

## Explicación sencilla

Piensa en corrección de exámenes:

- La gramática es el «ha rellenado todas las preguntas»: sí, hay algo escrito en cada casilla.
- `verify` es «lo que ha escrito también está en el enunciado»: tú pones `14:04`, el modelo pone
  `14:04` y no una hora razonable de invención (`13:55`, que también es una hora válida de la
  forma). `14:04` casa incluso con el `1404` que el OCR pudo tragarse, porque se comparan los
  dígitos.

Con números hay una sutileza que es todo el punto: si el texto pone `1.895,34 €` y el modelo
devuelve `189534`, la literalidad falla aunque el número suene «parecido». Con fechas se
compara el **valor** (`_date_candidates` prueba d/m/a, m/d/a y a/m/d) para que dos formatos
distintos de la misma fecha no se peleen. Y si el string vino parafraseado («café con leche» en
el documento, «café» en el JSON), `verify` avisa: no es un error del determinista, es una pista
de que ese campo pide lectura humana.

## Ejemplo práctico

Entrada real de un ticket (del benchmark del proyecto):

```json
// OCR: "TOTAL 3.40 EUR"   →   JSON esperado: {"total": 3.4, ...}
data := {"total": 100.0}     // ← el LLM eligió un precio unitario como total
errors := verify.literal_errors(data, ocr_text)
// [{"path": "total", "value": 100.0, "reason": "not found in text"}]
```

Y el código que lo hace barato — las comparaciones se construyen con conjuntos, no con bucles de
búsqueda (`verify.py`):

```python
def literal_errors(data: Any, text: str) -> list[dict]:
    """Campos cuyo valor no aparece en el texto. Uno por fallo, razón incluida."""
    nums = _numbers_in(text)      # todos los números normalizados del documento
    dates = _dates_in(text)       # todas las fechas, en el set de (y,m,d)
    words = normalize(text)       # "Café" y "café" se encuentran
    ...
```

Por cierto: `--strict` convierte cualquier aviso en `exit 2`. Útil para un pipeline contable;
innecesario y molesto si lo que haces es prototipar contratos.

## Consejo pro

- La literalidad detecta lo **falsamente literal y lo verdaderamente inventado**, pero no
  detecta «literal pero equivocado»: si el OCR leyó `1.895,34` donde el papel decía `1.895,35`,
  verify está contento y no había forma de saberlo. Por eso existen las plantillas (píldora 05)
  y la guarda de homologar solo con verify en verde.
- Un string parafraseado no es «el LLM mintiendo»: puede ser la respuesta razonable a una
  observación ilegible. Ese aviso te dice «mira ese campo», no «descarta el documento». La
  salida sigue siendo exit 0 hasta que `--strict` decida lo contrario.
- Cuando veas `coverage 0.5` con verify limpio, sospecha de las etiquetas: la mitad no casó y el
  LLM rellenó el resto con valores *sí literales* pero **de la fila equivocada**. El número
  existía en el texto; la culpa era de la geometría de tu tabla.
