# docs — Documentación de vlm_local_ocr

Toda la documentación del proyecto vive aquí (y el README en la raíz). Cada documento dice
a quién va dirigido y qué contiene; si buscas algo, este índice es tu entrada.

| Documento | Para quién | Qué tiene |
|---|---|---|
| [../README.md](../README.md) | Cualquiera que llegue al repo | qué es, badges, instalación rápida, modelos, ejemplos básicos, límites, rendimiento |
| [GUIA-USO.md](GUIA-USO.md) | Usuario del CLI | recetas por tarea («quiero hacer X»), problemas frecuentes (tabla síntoma→causa→solución) y operación diaria |
| [MANUAL.md](MANUAL.md) | Usuario avanzado / operador | referencia completa: flags, exit codes, formatos, límites detallados, seguridad, rendimiento medido |
| [DESARROLLO.md](DESARROLLO.md) | Quien edita el código | setup dev, mapa de los 19 módulos, cómo extender (modelo/proveedor/comando/anotación), convenciones, release, puntos de debug |
| [DECISIONES.md](DECISIONES.md) | Maintainer que se pregunta «¿por qué así?» | ADR-lite: las 11 decisiones estructurales con alternativa descartada y porqué |
| [learn/](learn/README.md) | Junior que no conoce este stack | 7 píldoras didácticas del stack y la arquitectura (OCR, GGUF, extractor determinista, plantillas, verify...) con ruta de lectura |
| [../CHANGELOG.md](../CHANGELOG.md) | Todo el mundo | historial versionado (Keep a Changelog + semver) |

## Cómo mantener la doc sincronizada

- **Cada flag o comportamiento nuevo** → aparece en README, MANUAL, CHANGELOG y, si cambia un
  flujo de usuario, en la GUIA-USO. El mismo PR, no el siguiente.
- **Los números de rendimiento** solo se renuevan con un benchmark real en `scripts/` y quedan
  en el MANUAL §7 y README. Si contradicen algo aquí escrito, el benchmark manda.
- **Cada LEARN** que nazca del proyecto se añade en `learn/` y se registra en el índice de la
  carpeta.
- **Las decisiones** se añaden a DECISIONES.md si *revertirla por desconocimiento* sería un bug
  caro. Lo demás es historia de git.
