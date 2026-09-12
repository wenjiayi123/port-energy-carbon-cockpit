"""Portable verification entry point for every preserved v7 evidence version."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path


def _weights_match(left: object, right: object, *, absolute_tolerance: float = 1e-12) -> bool:
    """Compare frozen numeric weights without architecture-specific ulp drift."""
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(
            _weights_match(item_left, item_right, absolute_tolerance=absolute_tolerance)
            for item_left, item_right in zip(left, right)
        )
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return math.isclose(float(left), float(right), rel_tol=0.0, abs_tol=absolute_tolerance)
    return left == right


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
        result = verify_report(path)
        if schema == "dispatch-qualified-business-value.v7" and not result["checks"].get(
            "reference_contract", True
        ):
            protocol = json.loads((path.parent / "protocol.json").read_text())
            selection = json.loads(
                (Path(__file__).resolve().parents[2] / protocol["reference_selection_path"]).read_text()
            )
            from app.rl.evaluate_dispatch_v7 import static_weights

            selected = selection["selected"].split("-")
            expected = static_weights(float(selected[1]), float(selected[2])).tolist()
            report = json.loads(path.read_text())
            result["checks"]["reference_contract"] = (
                _weights_match(expected, protocol["reference_static_weights"])
                and _weights_match(expected, report["reference_static_weights"])
            )
            result["ok"] = all(result["checks"].values())
        return result
    except (OSError, ValueError, TypeError, KeyError):
        return {"ok": False, "checks": {"readable_supported_evidence": False}}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("report", type=Path)
    args = parser.parse_args()
    result = verify(args.report)
    print(json.dumps(result))
    raise SystemExit(0 if result["ok"] else 1)
