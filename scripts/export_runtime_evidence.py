#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.services.runtime_forecast import runtime_forecast_model  # noqa: E402


DEFAULT_OUTPUT = ROOT / "reports" / "runtime_forecast_model_v1.json"


def expected() -> dict:
    return runtime_forecast_model.metadata()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Export or verify the leakage-safe runtime forecast evidence."
    )
    parser.add_argument("command", choices=("export", "verify"))
    parser.add_argument("path", nargs="?", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    current = expected()
    if args.command == "export":
        args.path.parent.mkdir(parents=True, exist_ok=True)
        args.path.write_text(
            json.dumps(current, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(f"runtime forecast evidence exported: {args.path}")
        print(f"model_sha256={current['model_sha256']}")
        return 0
    if not args.path.is_file():
        print(f"runtime forecast evidence missing: {args.path}", file=sys.stderr)
        return 1
    recorded = json.loads(args.path.read_text(encoding="utf-8"))
    if recorded != current:
        print("runtime forecast evidence drift detected", file=sys.stderr)
        print(
            f"recorded={recorded.get('model_sha256')} current={current.get('model_sha256')}",
            file=sys.stderr,
        )
        return 1
    print(f"runtime forecast evidence verified: {current['model_sha256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
