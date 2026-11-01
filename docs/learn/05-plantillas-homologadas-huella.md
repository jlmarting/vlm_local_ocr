# LEARN: Plantillas homologadas — aprender de la forma, no de los datos

> Píldora 05 de `vlm_local_ocr`. Nivel: junior. La que convierte «doscientos tickets iguales»
> en doscientos documentos de 0 tokens.

## Concepto

Un **contrato** identifica la tipología del documento (pedido, factura, ticket). Una
**variante** es cada disposición estructural distinta de esa tipología (el pedido del cliente A,
el del cliente B: cambian membretes y zonas, no la información). Homologar una variante es
guardar el **mapa etiqueta→campo** aprendido de una extracción válida, bajo una **huella
estructural** que describe el documento *sin valores*. Documento siguiente con esa huella = los
campos se asignan deterministamente con el mapa guardado, sin LLM.

## Por qué es importante

Por dos razones, una económica y una de confianza:

- **Económica**: el LLM se paga una vez por variante, no por documento. En un lote real de
  pedidos del mismo cliente, el coste por documento cae de ~90 s y tokens a **0,1 s y 0 tokens**.
- **De confianza**: como la huella solo mira etiquetas, cabeceras y zonas relativas — **nunca
  valores** — no hay fugas entre documentos. Tu plantilla de pedidos no puede «contagiarse» del
  total de ayer.

Pero hay una trampa que esta píldora existe para evitar: homologar aprende *lo que vio*, no «lo
correcto». Si la extracción de referencia inventó un valor literal pero equivocado, ese error
se fija y se replica 200 veces. Por eso el CLI pone guardas: `--homologate` **bloquea** si
quedan campos sin localizar; `--homologate-report` lee el mapa sin persistirlo, y `templates
list|show|drop` gestiona la biblioteca.

## Explicación sencilla

Piensa en el padrón de un gimnasio: no te reconoce por tu cara (de hecho se la da igual), te
reconoce por *la forma de tu ficha*: «el campo NOMBRE arriba a la derecha, el listado de CUOTA
en la columna central…». Eso es la huella estructural. Lo que NO guarda son los valores («Juan,
35 €») porque eso sería una filtración: el próximo socio no quiere tu cuota.

El ciclo completo, resumido:

1. `--homologate` termina una extracción que pasó verify y guarda el mapa etiqueta→campo con la
   huella (zona de filas + columnas, cabeceras).
2. Próximo documento: `templates.best_template` compara la huella nueva contra las almacenadas
   por similitud (0,85 de umbral con margen sobre la segunda).
3. Si casa: `hint_from_template` genera el «mapa» para el extractor y `extract.assign` llena los
   campos; los no cubiertos quedan `unlocated` (LLM solo para ellos, no para todo).
4. Si el layout deriva menos del 75 % de cobertura, se descarta la variante y se avisa, no se
   fuerza el resultado.

En el fondo es «recordar la forma del formulario para no desmontarlo cada vez».

## Ejemplo práctico

```bash
# Pasada 1: LLM (o determinista), verifica, homologa si todo ok
uv run vlm-ocr pedido-a.png --format json --contract contrato.json --homologate --metrics

# Antes de fiarte: qué se aprendió, sin persistir
uv run vlm-ocr pedido-a.png --format json --contract contrato.json \
  --homologate --homologate-report mapa.json

# Pasadas 2+: 0 tokens si la huella casa
uv run vlm-ocr pedido-a2.png --format json --contract contrato.json --no-llm

# Gestión de la biblioteca
uv run vlm-ocr templates list
uv run vlm-ocr templates drop <digest> --yes       # --yes obligatorio: es irreversible
```

Y el código que guarda el mapa *sin valores* (`templates.py::save_template`, simplificado):

```python
def save_template(blocks, assignment, contract, ...):
    rows = tuple(RowMark(label, band) for ...)        # etiqueta + banda vertical relativa
    digest = _digest(rows, columns)                    # hash de la forma, no del contenido
    map_ = FieldMap.from_labels(assignment.labels)     # etiquetas → campo (sin valor)
    Template(digest=digest, contract=contract_hash(contract), rows=rows, columns=columns, map=map_)
```

Observa: si cambia el contrato, `contract_hash` cambia y las variantes caducan solas (no hay que
limpiar). Si cambia la zona de items, la huella cambia y la similitud cae: nuevo homologado.

## Consejo pro

- **Homologa solo sobre verify verde.** `verify.literal_errors` vacío es tu green light. Un
  mapa «perfecto» aprendido de un documento mal extraído te fabricará 200 errores idénticos.
- Las métricas son honestas a propósito: `template.coverage` es matched/mapped de la variante
  (qué mapa casó), **no** cobertura del contrato. Para el contrato mira
  `extract.coverage_contract`. Confundirlas es pensar «1.0 = perfecto» cuando en realidad falta
  un tercio de los campos.
- Si una plantilla casa de más (dos contratos se parecen demasiado), afina las `x-labels` con
  etiquetas más únicas; la unicidad es lo que separa «esta disposición» de «cualquier papel».
