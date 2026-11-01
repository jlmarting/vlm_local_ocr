# LEARN: Un LLM local en la CPU — llama.cpp y GGUF

> Píldora 03 de `vlm_local_ocr`. Nivel: junior. El «modelo» es un fichero; el «servidor» es tu
> portátil; la «nube» es opcional y avisa por stderr.

## Concepto

Aquí el LLM es **llama.cpp ejecutando un GGUF en CPU**. `GGUF` es el formato: todos los pesos
**ya cuantizados** (reducidos de precisión para caber) más los metadatos en un solo fichero;
`Q4_K_M` es el nivel habitual de cuantización (1,9 GB para Llama 3.2 3B). `llama-cpp-python` lo
lanza con dos pernos que un junior debe conocer: `n_ctx` (la ventana en tokens — prompt + salida
deben caber) y `response_format` (la gramática GBNF que fuerza la forma JSON).

## Por qué es importante

Porque el LLM es **la parte cara y la parte mentirosa** del pipeline. Hay cuatro verdades aquí
que evitan el 90 % de los dramas:

- **En CPU el coste es «leer», no «escribir»**: el prefill (meter los 2.000 tokens del prompt)
  domina la latencia. Medido en T480: 2.501 tokens de prompt = 20,6 s; 500 tokens de generación
  = 8,4 s. Por eso truncamos el texto OCR a ~1.500 tokens y dimensionamos el techo de salida.
- **La gramática garantiza forma, no fidelidad**: con GBNF el JSON siempre sale bien formado y
  con tus claves; lo que NO garantiza es que los valores sean los del documento. Por eso existe
  `verify` (píldora 06). Confundir «válido» con «correcto» es como confundir «en inglés
  correcto» con «en inglés veraz».
- **El modelo no sabe calcular y hay que decírselo**: sin «no calcules» explícito el 0,5B suma
  el IVA a su manera y te lo pone de buena fe. La literalidad («copia del texto, no calcules»)
  se dice en el prompt y se **verifica** después, no se confía.
- **La nube es una decisión, no un defecto**: `OllamaRunner` habla `/api/chat` nativo; la clave
  solo viaja por entorno (`OLLAMA_API_KEY`) y la privacidad se avisa. Si tu nómina no puede salir
  del equipo, el defecto no es ollama: es meterla ahí.

## Explicación sencilla

Piensa en llamar a un becario brillante pero sin memoria de largo plazo y con tendencia a
«completar frases»:

- **`n_ctx` = el tamaño de su mesa.** Si tu dossier + su respuesta no caben, algo se cae por el
  borde y se trunca.
- **Prefill = el tiempo que tarda en leer tu dossier.** Generación = lo que tarda en escribir la
  respuesta. En CPU, la lectura es el cuello de botella.
- **Gramática = una plantilla de formulario.** Le das una hoja con casillas y no puede salirse
  de ellas. Puede rellenarlas mal, pero no con un poema.
- **`max_tokens` = el presupuesto que le das para escribir.** Techo, no gasto: si acaba antes,
  no paga el resto. `--max-tokens N` lo ajusta (en local, capado por `n_ctx`).

## Ejemplo práctico

`llmrun.py` expone una interfaz única (`Runner`) con dos implementaciones, un buen patrón para
no acoplar el resto del código al proveedor:

```python
class Runner(Protocol):
    def complete(self, prompt: BuiltPrompt) -> LLMResult: ...
    def estimate_tokens(self, prompt: BuiltPrompt) -> int: ...

class LocalRunner:       # llama.cpp/GGUF, offline, CPU
    def complete(self, prompt):
        kwargs = {"max_tokens": prompt.max_tokens}
        if prompt.response_format is not None:
            kwargs["response_format"] = prompt.response_format   # solo create_chat_completion
        return self._llm.create_chat_completion(..., **kwargs)

class OllamaRunner:      # API nativa /api/chat con structured outputs
    ...
```

Y el detalle que más dolores de cabeza ahorra en el T480: si el texto OCR truncado + la forma
del contrato no caben en `n_ctx`, el mensaje de error lo dice en cristiano (`respuesta fuera de
contexto`) en vez de devolver un JSON raro.

## Consejo pro

Cambia de modelo por medida, no por oído. `vlm-ocr models bench` compara un alias sobre un
documento real con métricas de tiempo y exactitud; el catálogo deja fijado `sha256` y licencia
para que «descargué el modelo X» sea una frase reproducible. Y si el LLM parece bobo con un
documento concreto, mira primero el texto que le llegó (píldora 04): nueve de cada diez veces el
modelo era un escriba obediente transcribiendo un OCR que ya venía roto.
