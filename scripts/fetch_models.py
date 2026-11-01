from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from vlm_ocr import catalog


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Descarga y verifica modelos del catálogo (por defecto, el modelo por defecto)"
    )
    parser.add_argument("alias", nargs="*", help="alias a descargar")
    parser.add_argument("--dest", type=Path, help="directorio de destino")
    parser.add_argument(
        "--accept-license",
        action="store_true",
        help="acepta la licencia del modelo (obligatorio si lo exige)",
    )
    args = parser.parse_args()
    aliases = args.alias or ([catalog.default_alias()] if catalog.default_alias() else [])
    try:
        for alias in aliases:
            catalog.fetch(alias, dest=args.dest, accept_license=args.accept_license)
    except catalog.CatalogError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
