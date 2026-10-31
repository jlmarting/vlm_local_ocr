#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

uv build
version="$(uv run python -c 'import vlm_ocr; print(vlm_ocr.__version__)')"
bundle="dist/vlm-local-ocr-${version}"

rm -rf "${bundle}"
mkdir -p "${bundle}"
cp dist/*.whl "${bundle}/"
cp scripts/fetch_models.py "${bundle}/"

if compgen -G "models/*.gguf" > /dev/null; then
  cp models/*.gguf "${bundle}/"
else
  echo "aviso: no hay GGUF en models/; el paquete no incluye modelo" >&2
fi

tar -C dist -czf "dist/vlm-local-ocr-${version}.tar.gz" "vlm-local-ocr-${version}"
echo "release: dist/vlm-local-ocr-${version}.tar.gz"
