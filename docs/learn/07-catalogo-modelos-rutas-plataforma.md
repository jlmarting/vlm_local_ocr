# LEARN: Catálogo de modelos y rutas por plataforma

> Píldora 07 de `vlm_local_ocr`. Nivel: junior. Dos utilidades de fontanería aburridas que
> evitan que la fiesta tenga lugar en `~/.local/share` para siempre.

## Concepto

Dos piezas, una misma idea: **que el usuario no tenga que pelearse con el sistema operativo**.

1. **Catálogo de modelos**: un `catalog.json` dentro del paquete declara cada alias
   (`llama32-3b`, `qwen05b`, `phi4mini`…) con fichero, tamaño, sha256, licencia, contexto y
   perfil. Tú dices `--model qwen05b` y el CLI sabe exactamente qué fichero bajó y si verificó.
   Tus propios alias viven en un overlay de usuario (`<config>/vlm-local-ocr/catalog.json`) que
   se fusiona sin tocar el paquete.
2. **Rutas por plataforma** (`paths.py`): el sitio donde viven datos y config depende del SO
   (`~/.local/share` en Linux, `%LOCALAPPDATA%` en Windows, `Application Support` en macOS) y la
   implementación prefiere el directorio antiguo si existe con contenido: nadie pierde plantillas
   ni modelos porque actualizaste.

## Por qué es importante

Son dos piezas que se notan por su ausencia:

- Sin catálogo, «qué modelo uso» es un path largo y ambiguo, y «es el mismo en CI y en mi
  máquina» deja de ser verdad. Con sha256, «descargué llama32-3b» es reproducible.
- Sin `paths.py`, cada módulo que guarda ficheros decide por su cuenta dónde: el resultado es
  `$XDG`, `%APPDATA%`, `AppData\Local`, y un usuario que no encuentra sus plantillas. Con una
  única función inyectable (`data_dir(platform, env, home)`) los tests simulan un Windows sin
  necesitar un Windows.
- La **guarda de compatibilidad** (prefiere la ruta vieja si tiene contenido) evita lo que la
  píldora llama «la migración fantasma»: actualizar, no mover los ficheros, y que de repente no
  existan plantillas.

## Explicación sencilla

Piensa en la mudanza que hiciste sin decírselo a nadie:

- El **catálogo** es la lista de contactos con teléfono verificado: cada alias es una entrada
  con nombre, hash y si su licencia permite compartirlo en el paquete. Si un alias es
  `redistributable: false` (Qwen2.5-3B con `qwen-research`), el release lo deja fuera solo.
- **Rutas por plataforma** es saber dónde dejas las llaves según la casa. En Linux, el cajón de
  siempre (`~/.local/share`); en Windows, la convención marca `%LOCALAPPDATA%` para datos y
  `%APPDATA%` para config; en macOS, `~/Library/Application Support`.
- La **guarda** es «antes de mover las cosas, mira si la casa vieja sigue ocupada»: si
  `~/.local/share/vlm-local-ocr/` tiene plantillas dentro y la nueva ruta está vacía, se usa la
  vieja. Determinista, auditable y sin migración sorpresa.

Y la parte junior-friendly: como la plataforma y el entorno se **inyectan** en los tests
(`platform`, `env`, `home` como parámetros), probar «¿qué pasa en Windows sin `%LOCALAPPDATA%`?»
no requiere una máquina Windows, solo `paths.data_dir("win32", {}, tmp_path)`.

## Ejemplo práctico

El centro de `paths.py` (resumido) y por qué se diseñó así:

```python
def data_dir(platform=None, env=None, home=None) -> Path:
    platform, env, home = _with_defaults(platform, env, home)  # sys.platform, os.environ, home()
    new = _new_data_dir(platform, env, home)       # %LOCALAPPDATA%, Application Support o XDG
    legacy = _legacy_data_dir(env, home)           # la vieja ruta XDG/ .local/share
    # Guarda: si la vieja tiene contenido y la nueva está vacía → usa la vieja
    return legacy if (new != legacy and _has_content(legacy) and not _has_content(new)) else new
```

Y el catálogo decide qué se comparte y qué no:

```python
fetch_llama32_3b  = catalog.fetch("llama32-3b", accept_license=True)
# descarga con .part, verifica sha256, y con `--accept-license` porque la licencia lo pide
```

El resultado visible:

```bash
uv run vlm-ocr models list                    # alias, estado, licencia, si está presente
uv run vlm-ocr models fetch llama32-3b --accept-license
uv run vlm-ocr models bench llama32-3b --doc n.pdf --contract c.json
```

## Consejo pro

- **No añadas dependencias para esto** (`platformdirs` se descartó a propósito): 20 líneas
  propias vs una dependencia con rarezas de Windows antiguo que jamás soportarás. Menos es más
  auditable.
- El catálogo es la única fuente de verdad de «dónde está el modelo»: ni `--model` ni
  `search_dirs()` inventan rutas por su cuenta. Si hay duplicados (Linux y `data_dir` coinciden
  por casualidad), `dict.fromkeys` los limpia.
- En tests, nunca te fíes de `platform.system()` real: inyecta. Es la diferencia entre «test
  verde en mi Mac y rojo en CI de Windows» y «verde en todos lados porque el Windows se simula».
  Y la guarda se prueba creando directorios vacíos y llenos en `tmp_path`, no rezando.
