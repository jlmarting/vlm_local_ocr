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
cp LICENSE NOTICE README.md CHANGELOG.md "${bundle}/"

cp src/vlm_ocr/catalog.json "${bundle}/"
BUNDLE="${bundle}" uv run python - <<'PY'
import os
import shutil
import sys
from pathlib import Path

from vlm_ocr.catalog import license_files, redistributable_files

bundle = Path(os.environ["BUNDLE"])
models = Path("models")
copied = 0
for name in redistributable_files():
    source = models / name
    if source.is_file():
        shutil.copy2(source, bundle / name)
        copied += 1
    else:
        print(f"aviso: falta {source}; el paquete no incluye {name}", file=sys.stderr)
for relative in license_files():
    destination = bundle / "licenses" / Path(relative).name
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(relative, destination)
if not copied:
    print("aviso: no hay GGUF redistribuibles en models/", file=sys.stderr)
PY

tar -C dist -czf "dist/vlm-local-ocr-${version}.tar.gz" "vlm-local-ocr-${version}"
echo "release: dist/vlm-local-ocr-${version}.tar.gz"
