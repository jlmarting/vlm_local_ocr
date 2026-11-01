# Contribuir a vlm_local_ocr

Gracias por mirar qué se puede mejorar. Las normas son pocas y están para que una contribución
valiosa no muera por formato.

## Antes de empezar

- **Cambios con impacto de usuario o arquitectura** van con propuesta previa (issue o propuesta
  del proyecto): discutir antes de construir evita PRs que nadie quiere.
- **Bugs claros, mejoras de documentación y tests** entran directo con su test y su entrada de
  CHANGELOG.

## Reglas de la casa

- **Test-first**: una flag o comportamiento del CLI sin su test rojo primero no es una feature,
  es una promesa. `uv run pytest -q` verde es la puerta.
- **Lint limpio**: `uv run ruff check .` (100 columnas). Si ruff dice algo, algo no está dicho.
- **Commits**: `feat|fix|docs|test|refactor|chore` en español, imperativo, minúsculas. Un
  commit, una cosa. El mensaje dice el *qué*, el código dice el *cómo* y DECISIONES el *porqué*.
- **CHANGELOG**: todo cambio observable entra en `[Unreleased]` con Keep a Changelog + semver.
- **Idiomas**: código en inglés; mensajes de usuario, documentación y mensajes de error en
  español y con hint accionable.
- **Licencias**: si traes un modelo nuevo, declara su licencia y marca `redistributable` en
  consecuencia, con su texto en `licenses/` si aplica.

## Setup del entorno

```bash
uv sync                       # crea .venv con deps + dev (pytest, ruff)
uv run pytest -q -m "not integration"   # unitarios
uv run pytest -q                        # todo (integración pide el modelo real)
uv run ruff check .
```

Detalle del flujo interno: [docs/DESARROLLO.md](docs/DESARROLLO.md).

## Cómo contribuir según el tipo

| Quieres… | Cómo |
|---|---|
| Reportar un bug | issue con: comando, versión, documento que lo dispara (o un sintético), salida y lo esperado |
| Añadir un modelo al catálogo | PR con entrada en `src/vlm_ocr/catalog.json` + sha256 verificado + licencia + test en `test_catalog.py` |
| Mejorar un extractor o plantilla | PR con benchmark en `scripts/` y goldens ajustados, con CHANGELOG de la conducta |
| Mejorar documentación o píldoras | PR directo; si es una píldora, sigue el formato canónico y regístrala en el índice de `docs/learn/` |
| Proponer una feature grande | propuesta previa con problema, diseño y alternativas — discusión antes de código |

## Lo que no está permitido sin debate

Añadir dependencias runtime, tocar el pipeline central (ingest/ocr/contract/extract) con un PR
en frío, cambiar la semántica de `null`/`absent`/`pending`, ni «optimizar» lo que no tiene
benchmark en `scripts/`. Si dudas, abre issue.
