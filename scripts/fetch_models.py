from __future__ import annotations

import hashlib
import sys
import urllib.request
from pathlib import Path

MODEL_FILENAME = "qwen2.5-0.5b-instruct-q4_k_m.gguf"
MODEL_URL = (
    "https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF/resolve/main/"
    "qwen2.5-0.5b-instruct-q4_k_m.gguf"
)
MODEL_SHA256 = "74a4da8c9fdbcd15bd1f6d01d621410d31c6fc00986f5eb687824e7b93d7a9db"
MODEL_SIZE = 491_400_032


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fetch(dest_dir: Path) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    target = dest_dir / MODEL_FILENAME
    if target.exists():
        if _sha256(target) == MODEL_SHA256:
            print(f"modelo ya presente y verificado: {target}")
            return target
        print(f"hash incorrecto en {target}; se vuelve a descargar", file=sys.stderr)
        target.unlink()

    tmp = target.with_suffix(target.suffix + ".part")
    print(f"descargando {MODEL_URL}")
    with urllib.request.urlopen(MODEL_URL) as response, tmp.open("wb") as out:
        total = int(response.headers.get("Content-Length", 0)) or MODEL_SIZE
        done = 0
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            out.write(chunk)
            done += len(chunk)
            pct = done * 100 // total
            print(f"\r{done // (1024 * 1024)} MB / ~{total // (1024 * 1024)} MB ({pct}%)", end="")
    print()

    if _sha256(tmp) != MODEL_SHA256:
        tmp.unlink()
        raise SystemExit("SHA256 no coincide: descarga corrupta")
    tmp.rename(target)
    print(f"modelo listo: {target}")
    return target


def main() -> int:
    fetch(Path(__file__).resolve().parent.parent / "models")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
