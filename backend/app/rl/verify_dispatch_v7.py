"""Portable verification entry point for every preserved v7 evidence version."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def verify(path: Path):
    path = path.resolve()
    try:
        schema = json.loads(path.read_text())["schema_version"]
        if schema == "dispatch-qualified-business-value.v7":
            from app.rl.qualified_dispatch_v7 import verify_report
        elif schema == "dispatch-guarded-business-value.v7":
            from app.rl.evaluate_guarded_dispatch_v7 import verify_report
        elif schema == "dispatch-business-value.v7":
            from app.rl.evaluate_dispatch_v7 import verify_report
        else:
            raise ValueError("Unsupported evidence schema")
        return verify_report(path)
    except (OSError, ValueError, TypeError, KeyError):
        return {"ok": False, "checks": {"readable_supported_evidence": False}}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("report", type=Path)
    args = parser.parse_args()
    result = verify(args.report)
    print(json.dumps(result))
    raise SystemExit(0 if result["ok"] else 1)
