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
REGULATORY_REPORT = PROJECT_ROOT / "reports" / "regulatory_resilience_v3.json"
HISTORY_REPORTS = {
    "v3_public_benchmark": PROJECT_ROOT / "reports" / "offline_benchmark_v3.json",
    "v3_vessel_benchmark": PROJECT_ROOT / "reports" / "offline_benchmark_vessel_activity_v1.json",
    "v4_landing_benchmark": LANDING_REPORT,
    "td3_blocked_candidate": PROJECT_ROOT
    / "reports"
    / "rl_td3_vessel_activity_100k"
    / "verification.json",
    "v4_runtime_forecast": PROJECT_ROOT / "reports" / "runtime_forecast_model_v1.json",
    "regulatory_resilience_v1": PROJECT_ROOT / "reports" / "regulatory_resilience_v1.json",
    "regulatory_resilience_v2": PROJECT_ROOT / "reports" / "regulatory_resilience_v2.json",
    "regulatory_resilience_v3": REGULATORY_REPORT,
}


@router.get("/evidence/regulatory-resilience")
def regulatory_resilience_evidence(response: Response) -> dict[str, Any]:
    """Return the compact, qualified v4 inspection-delay energy evidence."""
    try:
        report_bytes = REGULATORY_REPORT.read_bytes()
        report = json.loads(report_bytes)
        required = {
            "report_version",
            "status",
            "evidence_label",
            "strategy",
            "boundary",
            "datasets",
            "protocol",
            "selected_seed",
            "selected_artifact_sha256",
            "business_metrics_vs_preserved_legacy",
            "uncertainty",
            "offline_admission_gate",
            "history_preservation",
            "preserved_failed_candidates",
            "evidence_sha256",
        }
        if not isinstance(report, dict) or required - set(report):
            raise ValueError("invalid regulatory evidence structure")
    except Exception:
        logger.exception("Regulatory resilience evidence could not be loaded")
        raise HTTPException(status_code=503, detail="regulatory_evidence_unavailable") from None
    file_sha256 = hashlib.sha256(report_bytes).hexdigest()
    response.headers["ETag"] = f'"{file_sha256}"'
    response.headers["Cache-Control"] = "public, max-age=60"
    return {
        **{key: report[key] for key in required},
        "report_file_sha256": file_sha256,
        "per_window_evidence_included": False,
        "per_window_evidence_path": "reports/regulatory_resilience_v3.json",
        "production_authority": False,
    }
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


def _load_history_report(report_id: str) -> tuple[dict[str, Any], str]:
    path = HISTORY_REPORTS[report_id]
    report_bytes = path.read_bytes()
    report = json.loads(report_bytes)
    if not isinstance(report, dict):
        raise ValueError(f"{report_id} must contain an object")
    return report, hashlib.sha256(report_bytes).hexdigest()


@router.get("/evidence/history")
def evidence_history(response: Response) -> dict[str, Any]:
    """Return a compact, path-sanitized history including rejected candidates."""
    try:
        v3, v3_hash = _load_history_report("v3_public_benchmark")
        vessel, vessel_hash = _load_history_report("v3_vessel_benchmark")
        landing, landing_hash = _load_history_report("v4_landing_benchmark")
        td3, td3_hash = _load_history_report("td3_blocked_candidate")
        runtime, runtime_hash = _load_history_report("v4_runtime_forecast")
        regulatory_v1, regulatory_v1_hash = _load_history_report("regulatory_resilience_v1")
        regulatory_v2, regulatory_v2_hash = _load_history_report("regulatory_resilience_v2")
        regulatory_v3, regulatory_v3_hash = _load_history_report("regulatory_resilience_v3")
        td3_evaluation = td3["evaluation"]
        td3_policy = td3_evaluation["policy"]
        td3_metrics = td3_evaluation["metrics"]
        runtime_evidence = runtime["evidence"]
    except Exception:
        logger.exception("Historical evidence registry could not be loaded")
        raise HTTPException(status_code=503, detail="historical_evidence_unavailable") from None

    entries = [
        {
            "version": "v0.2.0",
            "evidence_id": "offline_benchmark_v3",
            "status": "archived_reproducible",
            "decision": "historical_baseline",
            "evidence_label": v3["evidence_label"],
            "dataset_id": v3["dataset"]["id"],
            "dataset_sha256": v3["dataset"]["package_sha256"],
            "metrics": v3["resume_safe_metrics"],
            "report_file_sha256": v3_hash,
        },
        {
            "version": "v0.2.1",
            "evidence_id": "vessel_activity_benchmark_v1",
            "status": "archived_reproducible",
            "decision": "historical_baseline",
            "evidence_label": vessel["evidence_label"],
            "dataset_id": vessel["dataset"]["id"],
            "dataset_sha256": vessel["dataset"]["package_sha256"],
            "metrics": vessel["resume_safe_metrics"],
            "report_file_sha256": vessel_hash,
        },
        {
            "version": "candidate-2026-07-25",
            "evidence_id": td3_policy["policy_version"],
            "status": td3["status"],
            "decision": "rejected_by_admission_gate",
            "evidence_label": "HELD_OUT_RL_CANDIDATE_NOT_ADMITTED",
            "algorithm": td3_policy["algorithm"],
            "dataset_id": td3_policy["dataset_id"],
            "dataset_sha256": td3_policy["dataset_sha256"],
            "artifact_sha256": td3_policy["artifact_sha256"],
            "failed_checks": [check["name"] for check in td3["checks"] if not check["passed"]],
            "metrics": {
                name: td3_metrics[name]
                for name in (
                    "carbon_reduction_pct",
                    "cost_saving_pct",
                    "fixed_baseline_carbon_reduction_pct",
                    "fixed_baseline_cost_saving_pct",
                    "fixed_baseline_peak_change_pct",
                    "fixed_baseline_throughput_change_pct",
                    "constraint_success_rate_pct",
                    "test_steps",
                )
            },
            "report_file_sha256": td3_hash,
        },
        {
            "version": "v0.3.0",
            "evidence_id": "port_landing_benchmark_v4",
            "status": landing["status"],
            "decision": "current_offline_champion",
            "evidence_label": landing["evidence_label"],
            "dataset_id": landing["dataset"]["id"],
            "dataset_sha256": landing["dataset"]["package_sha256"],
            "metrics": landing["business_metrics_vs_fixed_full_resources"],
            "algorithm_increment": landing["algorithm_increment_vs_causal_legacy_mpc"],
            "report_file_sha256": landing_hash,
        },
        {
            "version": "v0.4.0",
            "evidence_id": runtime["model_id"],
            "status": "reproducible_current_input_inference",
            "decision": "runtime_simulation_only",
            "evidence_label": "PUBLIC_CALIBRATED_RUNTIME_FORECAST_NOT_FIELD_KPI",
            "dataset_id": runtime["dataset_id"],
            "dataset_sha256": runtime["dataset_sha256"],
            "model_sha256": runtime["model_sha256"],
            "held_out_test_mae_by_horizon": {
                horizon: evidence["held_out_test_mae"]
                for horizon, evidence in runtime_evidence.items()
            },
            "future_test_rows_accessed_during_inference": runtime[
                "future_test_rows_accessed_during_inference"
            ],
            "report_file_sha256": runtime_hash,
        },
        {
            "version": "regulatory-v1",
            "evidence_id": "regulatory_resilience_v1_full_action_sac",
            "status": regulatory_v1["status"],
            "decision": "rejected_by_admission_gate",
            "evidence_label": regulatory_v1["evidence_label"],
            "algorithm": "SAC",
            "failed_checks": [
                item["name"]
                for item in regulatory_v1["offline_admission_gate"]["checks"]
                if not item["passed"]
            ],
            "metrics": regulatory_v1["business_metrics_vs_legacy_fixed"],
            "report_file_sha256": regulatory_v1_hash,
        },
        {
            "version": "regulatory-v2",
            "evidence_id": "regulatory_resilience_v2_simple_shield",
            "status": regulatory_v2["status"],
            "decision": "rejected_by_forward_gate",
            "evidence_label": regulatory_v2["evidence_label"],
            "algorithm": "shielded SAC",
            "failed_checks": [
                item["name"]
                for item in regulatory_v2["offline_admission_gate"]["checks"]
                if not item["passed"]
            ],
            "metrics": regulatory_v2["business_metrics_vs_preserved_legacy"],
            "report_file_sha256": regulatory_v2_hash,
        },
        {
            "version": "regulatory-v3",
            "evidence_id": "regulatory_resilience_v3_dominance_projected_sac",
            "status": regulatory_v3["status"],
            "decision": "qualified_offline_regulatory_resilience",
            "evidence_label": regulatory_v3["evidence_label"],
            "algorithm": "dominance-projected SAC",
            "metrics": regulatory_v3["business_metrics_vs_preserved_legacy"],
            "artifact_sha256": regulatory_v3["selected_artifact_sha256"],
            "report_file_sha256": regulatory_v3_hash,
        },
    ]
    registry_hash = hashlib.sha256(
        json.dumps(entries, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    response.headers["ETag"] = f'"{registry_hash}"'
    response.headers["Cache-Control"] = "public, max-age=60"
    return {
        "schema_version": "history-evidence.v1",
        "history_preserved": True,
        "production_authority": False,
        "entry_count": len(entries),
        "registry_sha256": registry_hash,
        "entries": entries,
        "boundary": (
            "Evidence reports are historical public-data offline or calibrated-simulation artifacts; "
            "none authorizes field dispatch."
        ),
    }
