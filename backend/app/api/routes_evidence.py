from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Response


router = APIRouter(tags=["evidence"])
logger = logging.getLogger(__name__)
PROJECT_ROOT = Path(__file__).resolve().parents[3]
LANDING_REPORT = PROJECT_ROOT / "reports" / "port_landing_benchmark_v4.json"
PUBLIC_REPORT_FIELDS = (
    "report_version",
    "generated_at",
    "status",
    "evidence_label",
    "boundary",
    "dataset",
    "protocol",
    "business_metrics_vs_fixed_full_resources",
    "algorithm_increment_vs_causal_legacy_mpc",
    "tail_risk",
    "stress_tests",
    "derived_metrics_refreshed_at",
    "evidence_sha256",
)


@router.get("/evidence/landing-benchmark")
def landing_benchmark_evidence(response: Response) -> dict[str, Any]:
    """Return the published v4 summary without the large per-window payload."""
    try:
        report_bytes = LANDING_REPORT.read_bytes()
        report = json.loads(report_bytes)
        if not isinstance(report, dict) or any(field not in report for field in PUBLIC_REPORT_FIELDS):
            raise ValueError("invalid report structure")
    except Exception:
        logger.exception("Published landing benchmark could not be loaded")
        raise HTTPException(status_code=503, detail="landing_evidence_unavailable") from None

    file_sha256 = hashlib.sha256(report_bytes).hexdigest()
    response.headers["ETag"] = f'"{file_sha256}"'
    response.headers["Cache-Control"] = "public, max-age=60"
    return {
        **{field: report[field] for field in PUBLIC_REPORT_FIELDS},
        "report_file_sha256": file_sha256,
        "per_window_evidence_included": False,
        "per_window_evidence_path": "reports/port_landing_benchmark_v4.json",
    }
