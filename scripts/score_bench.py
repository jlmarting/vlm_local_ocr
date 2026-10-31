from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _get(data: Any, dotted: str) -> Any:
    current = data
    for key in dotted.split("."):
        if not isinstance(current, dict) or key not in current:
            return None
        current = current[key]
    return current


def _count_leaves(value: Any) -> int:
    if isinstance(value, dict):
        return sum(_count_leaves(sub) for sub in value.values())
    return 1


def _count_nulls(value: Any) -> int:
    if isinstance(value, dict):
        return sum(_count_nulls(sub) for sub in value.values())
    return 1 if value is None else 0


def _matches(value: Any, expected: Any) -> bool:
    if isinstance(expected, dict) and "any" in expected:
        return any(_matches(value, option) for option in expected["any"])
    if isinstance(expected, str):
        return isinstance(value, str) and value.strip().upper() == expected.strip().upper()
    if expected is None:
        return value is None
    return isinstance(value, int | float) and abs(float(value) - float(expected)) < 0.011


def main() -> int:
    parser = argparse.ArgumentParser(description="Puntúa un bench JSONL contra una verdad JSON")
    parser.add_argument("--bench", type=Path, required=True)
    parser.add_argument("--truth", type=Path, required=True)
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()

    truth = json.loads(args.truth.read_text(encoding="utf-8"))
    rows = []
    for line in args.bench.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        expected = truth.get(record["doc"], {})
        data = record.get("data") or {}
        correct = sum(
            1 for path, value in expected.items() if _matches(_get(data, path), value)
        )
        rows.append(
            {
                "model": record["model"],
                "doc": record["doc"],
                "mode": record.get("mode"),
                "correct": correct,
                "total": len(expected),
                "valid_json": record.get("valid_json"),
                "time_s": round((record.get("time_ms") or 0) / 1000, 1),
                "tokens_per_second": record.get("tokens_per_second"),
                "nulls": _count_nulls(data),
                "leaves": _count_leaves(data),
            }
        )

    if args.as_json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return 0
    for row in rows:
        print(
            f"{row['model'][:30]:30} {row['doc'][:20]:20} {row['correct']}/{row['total']}"
            f"  valid={row['valid_json']}  {row['time_s']:>5}s  {row['tokens_per_second']} t/s"
            f"  nulls={row['nulls']}/{row['leaves']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
