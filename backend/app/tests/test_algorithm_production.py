import base64
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

from app.main import app
from app.api import routes_dashboard
from app.schemas.algorithm_production import (
    SOURCE_DOMAINS,
    AlgorithmProductionQualificationRequest,
)
from app.services.algorithm_production import (
    AlgorithmProductionQualificationService,
    canonical_sha256,
    source_domain_payload,
)


HASHES = {letter: letter * 64 for letter in "abcdef123456789"}
SOURCE_PRIVATE_KEYS = {domain: Ed25519PrivateKey.generate() for domain in sorted(SOURCE_DOMAINS)}
SOURCE_KEY_IDS = {domain: f"test-algorithm-{domain}-key" for domain in sorted(SOURCE_DOMAINS)}
SOURCE_PUBLIC_KEYS = {
    SOURCE_KEY_IDS[domain]: base64.b64encode(
        private_key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
    ).decode("ascii")
    for domain, private_key in SOURCE_PRIVATE_KEYS.items()
}
ROOT = Path(__file__).resolve().parents[3]
FAULT_TYPES = [
    "communications_loss",
    "sensor_drift",
    "transformer_derating",
    "battery_overtemperature",
    "stale_data",
    "unknown_ood",
]


def unsigned_payload() -> dict:
    seasons = ["spring", "summer", "autumn", "winter"]
    pairs = []
    for seed_index, seed in enumerate((11, 29, 47)):
        for season_index, season in enumerate(seasons):
            index = seed_index * 4 + season_index
            pairs.append(
                {
                    "pair_id": f"pair-{seed}-{season}",
                    "seed": seed,
                    "season": season,
                    "split": "read_only_shadow",
                    "candidate_policy_id": "risk-aware-mpc-v4-candidate",
                    "baseline_policy_id": "causal-legacy-mpc-v3",
                    "candidate": {
                        "carbon_kg": 90.0 + index * 0.1,
                        "cost_cny": 95.0 + index * 0.1,
                        "peak_kw": 94.0 + index * 0.1,
                        "throughput_teu": 101.0 + index * 0.1,
                        "delay_minutes": 8.0,
                        "safety_violations": 0,
                        "reserve_breach_steps": 0,
                    },
                    "baseline": {
                        "carbon_kg": 100.0 + index * 0.1,
                        "cost_cny": 100.0 + index * 0.1,
                        "peak_kw": 100.0 + index * 0.1,
                        "throughput_teu": 100.0 + index * 0.1,
                        "delay_minutes": 10.0,
                        "safety_violations": 0,
                        "reserve_breach_steps": 0,
                    },
                    "source_window_sha256": HASHES["1"],
                }
            )
    return {
        "schema_version": "algorithm-production-qualification-input.v1",
        "qualification_id": "terminal-a-risk-aware-mpc-2026-08",
        "site_id": "TERMINAL-A",
        "evaluated_at": "2026-08-01T00:00:00Z",
        "requested_by": "model-risk-owner",
        "policy": {
            "policy_id": "terminal-a-algorithm-admission-v1",
            "candidate_policy_id": "risk-aware-mpc-v4-candidate",
            "baseline_policy_id": "causal-legacy-mpc-v3",
            "minimum_distinct_seeds": 3,
            "required_seasons": seasons,
            "minimum_pairs_per_seed_season": 1,
            "nominal_interval_coverage": 0.9,
            "minimum_interval_coverage": 0.85,
            "maximum_interval_coverage": 0.98,
            "maximum_median_mae": 10.0,
            "minimum_forecast_samples": 20,
            "minimum_ood_true_positive_rate": 0.9,
            "maximum_ood_false_positive_rate": 0.05,
            "minimum_ood_samples_per_class": 10,
            "minimum_explanation_records": 12,
            "minimum_explanation_fidelity": 0.9,
            "minimum_action_receipts": 12,
            "maximum_action_tracking_error": 1.0,
            "maximum_ack_latency_ms": 2000.0,
            "minimum_latency_samples": 20,
            "maximum_p95_latency_ms": 1000.0,
            "maximum_p99_latency_ms": 1500.0,
            "required_fault_types": FAULT_TYPES,
            "maximum_fault_recovery_ms": 5000.0,
            "minimum_human_reviews": 12,
            "minimum_distinct_reviewers": 2,
            "minimum_shadow_hours": 168.0,
            "minimum_shadow_decisions": 1000,
            "minimum_carbon_improvement_pct": 0.0,
            "maximum_cost_regression_pct": 0.0,
            "maximum_peak_regression_pct": 0.0,
            "maximum_throughput_regression_pct": 0.0,
            "maximum_reserve_breach_increase_pct": 0.0,
            "maximum_source_age_seconds": 300,
            "maximum_source_alignment_seconds": 60,
            "approved_by": "model-risk-committee",
            "approval_record_sha256": HASHES["a"],
        },
        "source_attestations": [
            {
                "domain": domain,
                "source_system": f"site-{domain}",
                "source_record_ids": [f"{domain}-record-001"],
                "observed_at": "2026-07-31T23:59:30Z",
                "live_data_verified": True,
                "key_id": SOURCE_KEY_IDS[domain],
                "signed_payload_sha256": HASHES["a"],
                "signature": base64.b64encode(b"0" * 64).decode("ascii"),
            }
            for domain in sorted(SOURCE_DOMAINS)
        ],
        "artifacts": [
            {
                "policy_id": "risk-aware-mpc-v4-candidate",
                "role": "candidate",
                "algorithm_family": "risk_aware_model_predictive_control",
                "artifact_sha256": HASHES["a"],
                "dataset_sha256": HASHES["b"],
                "code_sha256": HASHES["c"],
                "observation_contract_sha256": HASHES["d"],
                "action_contract_sha256": HASHES["e"],
                "immutable": True,
            },
            {
                "policy_id": "causal-legacy-mpc-v3",
                "role": "baseline",
                "algorithm_family": "causal_model_predictive_control",
                "artifact_sha256": HASHES["f"],
                "dataset_sha256": HASHES["b"],
                "code_sha256": HASHES["c"],
                "observation_contract_sha256": HASHES["d"],
                "action_contract_sha256": HASHES["e"],
                "immutable": True,
            },
        ],
        "evaluation_pairs": pairs,
        "probabilistic_forecasts": [
            {
                "forecast_id": f"forecast-{index}",
                "decision_id": f"forecast-decision-{index}",
                "target": "terminal_load_kw",
                "horizon_minutes": 60,
                "lower": 90.0,
                "median": 100.0,
                "upper": 110.0,
                "actual": 100.0 if index < 18 else 115.0,
            }
            for index in range(20)
        ],
        "ood_events": [
            {
                "event_id": f"ood-{index}",
                "decision_id": f"ood-decision-{index}",
                "expected_ood": True,
                "score": 2.0,
                "threshold": 1.0,
                "detected": True,
                "fallback_activated": True,
                "recommendation_suppressed": True,
                "fallback_policy_id": "current-state-sop-v1",
            }
            for index in range(10)
        ]
        + [
            {
                "event_id": f"id-{index}",
                "decision_id": f"id-decision-{index}",
                "expected_ood": False,
                "score": 0.5,
                "threshold": 1.0,
                "detected": False,
                "fallback_activated": False,
                "recommendation_suppressed": False,
                "fallback_policy_id": None,
            }
            for index in range(10)
        ],
        "explanations": [
            {
                "decision_id": f"explanation-decision-{index}",
                "model_sha256": HASHES["a"],
                "policy_sha256": HASHES["b"],
                "input_sha256": HASHES["c"],
                "reason_codes": ["PEAK_RISK", "CARBON_INTENSITY"],
                "feature_attributions": {
                    "transformer_loading_pct": 0.62,
                    "grid_carbon_factor": 0.38,
                },
                "local_fidelity": 0.96,
                "counterfactual_action": {"battery_power_kw": 0.0},
                "rationale": "Transformer reserve drives the bounded discharge action.",
                "generated_before_human_review": True,
            }
            for index in range(12)
        ],
        "action_receipts": [
            {
                "command_id": f"shadow-command-{index}",
                "decision_id": f"action-decision-{index}",
                "mode": "read_only_shadow",
                "receipt_kind": "site_shadow_gateway_ack",
                "current_action": {"battery_power_kw": 0.0},
                "requested_action": {"battery_power_kw": 500.0},
                "projected_action": {"battery_power_kw": 500.0},
                "acknowledged_action": {"battery_power_kw": 500.2},
                "limits": {
                    "battery_power_kw": {
                        "minimum": -5000.0,
                        "maximum": 5000.0,
                        "maximum_delta": 1000.0,
                        "unit": "kW",
                    }
                },
                "ack_latency_ms": 120.0,
                "interlocks_satisfied": True,
                "receipt_sha256": HASHES["d"],
            }
            for index in range(12)
        ],
        "latency_samples": [
            {
                "decision_id": f"latency-decision-{index}",
                "mode": "read_only_shadow",
                "forecast_ms": 50.0,
                "policy_ms": 60.0,
                "safety_projection_ms": 20.0,
                "end_to_end_ms": 200.0 + index,
                "timed_out": False,
                "fallback_activated": False,
            }
            for index in range(20)
        ],
        "fault_injections": [
            {
                "campaign_id": "campaign-2026-08",
                "fault_id": f"fault-{fault_type}",
                "fault_type": fault_type,
                "detected": True,
                "failed_closed": True,
                "fallback_activated": True,
                "unsafe_action_count": 0,
                "recovery_ms": 800.0,
                "receipt_sha256": HASHES["e"],
            }
            for fault_type in FAULT_TYPES
        ],
        "human_reviews": [
            {
                "decision_id": f"review-decision-{index}",
                "requested_by": "model-operator",
                "reviewer_id": f"risk-reviewer-{index % 2}",
                "outcome": "veto" if index == 0 else "approve",
                "reason_code": "GRID_RESERVE" if index == 0 else "WITHIN_POLICY",
                "comment": "Vetoed on reserve evidence." if index == 0 else "Evidence reviewed.",
                "reviewed_at": f"2026-07-31T23:{40 + index:02d}:00Z",
                "policy_sha256": HASHES["a"],
                "input_sha256": HASHES["b"],
                "audit_event_sha256": HASHES["c"],
            }
            for index in range(12)
        ],
        "shadow_runs": [
            {
                "run_id": "shadow-run-2026-summer",
                "site_id": "TERMINAL-A",
                "mode": "read_only_shadow",
                "started_at": "2026-07-15T00:00:00Z",
                "ended_at": "2026-07-31T00:00:00Z",
                "decision_count": 2000,
                "live_data_verified": True,
                "run_evidence_sha256": HASHES["f"],
            }
        ],
    }


def signed_request(payload: dict | None = None) -> AlgorithmProductionQualificationRequest:
    payload = deepcopy(payload or unsigned_payload())
    placeholder = AlgorithmProductionQualificationRequest(**payload)
    attestations = {item["domain"]: item for item in payload["source_attestations"]}
    for domain in sorted(SOURCE_DOMAINS):
        digest = canonical_sha256(source_domain_payload(placeholder, domain))
        attestations[domain]["signed_payload_sha256"] = digest
        attestations[domain]["signature"] = base64.b64encode(
            SOURCE_PRIVATE_KEYS[domain].sign(bytes.fromhex(digest))
        ).decode("ascii")
    return AlgorithmProductionQualificationRequest(**payload)


def service() -> AlgorithmProductionQualificationService:
    return AlgorithmProductionQualificationService(source_public_keys=SOURCE_PUBLIC_KEYS)


def gate(report, gate_id: str) -> dict:
    return next(item for item in report.gates if item["gate_id"] == gate_id)


def test_default_is_fail_closed_and_preserves_negative_results() -> None:
    report = AlgorithmProductionQualificationService(source_public_keys={}).build_default()
    assert report.status == "blocked"
    assert report.source_readiness["domain_count"] == 0
    assert sum(item["passed"] for item in report.gates) == 0
    assert len(report.gates) == 15
    assert report.known_offline_evidence["negative_results_preserved"] is True
    legacy = report.known_offline_evidence["risk_aware_vs_causal_legacy_mpc"]
    assert legacy["carbon_reduction_pct"] == -0.1557
    assert legacy["cost_reduction_pct"] == -0.1911
    assert (
        report.known_offline_evidence["grid_derating_10pct"]["reserve_breach_reduction_pct"]
        == -7.6923
    )
    assert report.production_boundary["automatic_policy_promotion_allowed"] is False
    assert report.production_boundary["autonomous_dispatch_allowed"] is False
    assert report.production_boundary["algorithm_expansion_recommended"] is False


def test_complete_signed_four_season_package_is_qualification_ready() -> None:
    report = service().evaluate(signed_request())
    assert report.status == "qualification_ready"
    assert report.source_readiness["domain_count"] == 6
    assert report.qualification_summary["passed_gate_count"] == 15
    assert report.qualification_summary["qualification_evidence_ready"] is True
    assert report.qualification_summary["production_qualified"] is False
    assert report.qualification_summary["pending_independent_human_release"] is True
    assert report.multi_seed_cross_season["distinct_seeds"] == 3
    assert set(report.multi_seed_cross_season["covered_seasons"]) == {
        "spring",
        "summer",
        "autumn",
        "winter",
    }
    assert report.probabilistic_forecast["empirical_interval_coverage"] == 0.9
    assert report.ood_monitoring["true_positive_rate"] == 1.0
    assert report.human_oversight["veto_count"] == 1
    assert report.production_boundary["production_authority"] is False


def test_tampered_forecast_blocks_source_signature() -> None:
    request = signed_request()
    request.probabilistic_forecasts[0].actual = 101.0
    report = service().evaluate(request)
    assert report.status == "blocked"
    assert gate(report, "source_trust_and_time")["passed"] is False


def test_multi_seed_and_cross_season_are_independent_gates() -> None:
    payload = unsigned_payload()
    for item in payload["evaluation_pairs"]:
        if item["seed"] == 47:
            item["seed"] = 29
        if item["season"] == "winter":
            item["season"] = "autumn"
    report = service().evaluate(signed_request(payload))
    assert report.status == "not_qualified"
    assert gate(report, "multi_seed_validation")["passed"] is False
    assert gate(report, "cross_season_validation")["passed"] is False


def test_forecast_ood_and_explanation_fail_their_own_gates() -> None:
    payload = unsigned_payload()
    for item in payload["probabilistic_forecasts"]:
        item["actual"] = 140.0
    for item in payload["ood_events"][:2]:
        item.update(
            {
                "score": 0.5,
                "detected": False,
                "fallback_activated": False,
                "recommendation_suppressed": False,
                "fallback_policy_id": None,
            }
        )
    for item in payload["explanations"]:
        item["local_fidelity"] = 0.5
    report = service().evaluate(signed_request(payload))
    assert gate(report, "probabilistic_calibration")["passed"] is False
    assert gate(report, "ood_detection_fallback")["passed"] is False
    assert gate(report, "policy_explainability")["passed"] is False


def test_action_latency_fault_and_human_gates_fail_closed() -> None:
    payload = unsigned_payload()
    payload["action_receipts"][0]["acknowledged_action"]["battery_power_kw"] = 505.0
    payload["latency_samples"][-1]["end_to_end_ms"] = 2000.0
    payload["fault_injections"][0]["unsafe_action_count"] = 1
    for item in payload["human_reviews"]:
        item["reviewer_id"] = "risk-reviewer-only"
    report = service().evaluate(signed_request(payload))
    assert gate(report, "action_reachability")["passed"] is False
    assert gate(report, "realtime_latency")["passed"] is False
    assert gate(report, "fault_injection")["passed"] is False
    assert gate(report, "human_veto_statistics")["passed"] is False


def test_candidate_regression_fails_comparison_and_safety_gates() -> None:
    payload = unsigned_payload()
    for item in payload["evaluation_pairs"]:
        item["candidate"]["carbon_kg"] = item["baseline"]["carbon_kg"] * 1.02
    payload["evaluation_pairs"][0]["candidate"]["reserve_breach_steps"] = 1
    report = service().evaluate(signed_request(payload))
    assert gate(report, "champion_challenger")["passed"] is False
    assert gate(report, "safety_non_regression")["passed"] is False


def test_shadow_duration_is_measured_not_inferred() -> None:
    payload = unsigned_payload()
    payload["shadow_runs"][0]["started_at"] = "2026-07-30T00:00:00Z"
    payload["shadow_runs"][0]["decision_count"] = 50
    report = service().evaluate(signed_request(payload))
    assert gate(report, "shadow_duration")["passed"] is False
    assert report.qualification_summary["production_qualified"] is False


def test_dashboard_api_exposes_fail_closed_qualification() -> None:
    client = TestClient(app)
    response = client.get("/api/dashboard/algorithm-production")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "blocked"
    assert len(payload["source_readiness"]["required_domains"]) == 6
    assert len(payload["gates"]) == 15
    snapshot = client.get("/api/dashboard/snapshot").json()
    assert snapshot["algorithm_production"]["status"] == "blocked"


def test_dashboard_api_evaluates_signed_package(monkeypatch) -> None:
    monkeypatch.setattr(
        routes_dashboard.algorithm_production_qualification_service,
        "source_public_keys",
        SOURCE_PUBLIC_KEYS,
    )
    client = TestClient(app)
    response = client.post(
        "/api/dashboard/algorithm-production/evaluate",
        json=signed_request().model_dump(mode="json"),
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "qualification_ready"
    assert payload["qualification_summary"]["passed_gate_count"] == 15
    assert payload["qualification_summary"]["production_qualified"] is False


def test_signing_cli_signs_one_source_domain(tmp_path: Path) -> None:
    payload = unsigned_payload()
    input_path = tmp_path / "input.json"
    output_path = tmp_path / "output.json"
    private_key_path = tmp_path / "private.pem"
    input_path.write_text(json.dumps(payload), encoding="utf-8")
    private_key_path.write_bytes(
        SOURCE_PRIVATE_KEYS["forecast_calibration"].private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "sign_algorithm_production_evidence.py"),
            "--input",
            str(input_path),
            "--domain",
            "forecast_calibration",
            "--private-key",
            str(private_key_path),
            "--key-id",
            SOURCE_KEY_IDS["forecast_calibration"],
            "--output",
            str(output_path),
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0
    updated = AlgorithmProductionQualificationRequest(
        **json.loads(output_path.read_text(encoding="utf-8"))
    )
    report = service().evaluate(updated)
    assert report.source_readiness["signed_domains"] == ["forecast_calibration"]
    assert report.status == "blocked"
