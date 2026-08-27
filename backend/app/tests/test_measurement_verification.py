import base64
from copy import deepcopy
import hashlib
import json

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

from app.main import app
from app.schemas.measurement_verification import MeasurementVerificationRequest
from app.services.measurement_verification import (
    MeasurementVerificationService,
    measurement_verification_service,
)


HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64
HASH_D = "d" * 64
HASH_E = "e" * 64
HASH_F = "f" * 64
VERIFIER_KEY_ID = "test-independent-verifier-key"
VERIFIER_PRIVATE_KEY = Ed25519PrivateKey.generate()
VERIFIER_PUBLIC_KEY_B64 = base64.b64encode(
    VERIFIER_PRIVATE_KEY.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
).decode("ascii")


def canonical_sha256(value: dict) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def complete_evidence_payload() -> dict:
    payload = {
        "schema_version": "energy-carbon-mv-input.v1",
        "project_id": "terminal-efficiency-project-01",
        "boundary": {
            "boundary_id": "terminal-a-revenue-meter",
            "reporting_entity": "Example Terminal Operator",
            "site_id": "TERMINAL-A",
            "accounting_meter_ids": ["METER-REVENUE-01"],
            "included_assets": ["terminal-a-electrical-boundary"],
            "excluded_assets": ["tenant-load-outside-boundary"],
            "approved_by": "energy-manager",
            "approval_record_sha256": HASH_A,
        },
        "plan": {
            "plan_id": "mv-plan-01",
            "plan_version": "1.0",
            "approved_by": "energy-manager",
            "approval_record_sha256": HASH_B,
            "expected_meter_interval_count": 2,
            "minimum_coverage_pct": 100.0,
            "maximum_estimated_pct": 0.0,
            "maximum_cv_rmse_pct": 10.0,
            "maximum_absolute_nmbe_pct": 2.0,
            "maximum_invoice_variance_pct": 1.0,
            "uncertainty_confidence_pct": 95.0,
            "uncertainty_coverage_factor": 1.96,
        },
        "baseline_model": {
            "baseline_model_id": "terminal-a-baseline-v1",
            "method": "site-approved weather-and-throughput regression",
            "model_sha256": HASH_C,
            "baseline_period": {
                "start_at": "2026-07-01T00:00:00Z",
                "end_at": "2026-07-03T00:00:00Z",
            },
            "frozen_at": "2026-07-31T12:00:00Z",
            "training_observations": 1440,
            "validation_observations": 336,
            "cv_rmse_pct": 8.0,
            "nmbe_pct": -1.0,
            "independent_variables": ["handled_teu", "ambient_temperature_c"],
            "approved_by": "energy-manager",
            "approval_record_sha256": HASH_D,
        },
        "reporting_period": {
            "start_at": "2026-08-01T00:00:00Z",
            "end_at": "2026-08-01T02:00:00Z",
        },
        "intervals": [
            {
                "interval_id": "interval-0001",
                "meter_id": "METER-REVENUE-01",
                "start_at": "2026-08-01T00:00:00Z",
                "end_at": "2026-08-01T01:00:00Z",
                "baseline_adjusted_energy_kwh": 100.0,
                "reporting_energy_kwh": 90.0,
                "baseline_adjusted_carbon_kg": 40.0,
                "reporting_carbon_kg": 36.0,
                "baseline_standard_uncertainty_kwh": 1.0,
                "reporting_standard_uncertainty_kwh": 1.0,
                "baseline_standard_uncertainty_carbon_kg": 0.4,
                "reporting_standard_uncertainty_carbon_kg": 0.4,
                "quality": "measured",
                "source_record_id": "meter-row-0001",
                "source_payload_sha256": HASH_A,
            },
            {
                "interval_id": "interval-0002",
                "meter_id": "METER-REVENUE-01",
                "start_at": "2026-08-01T01:00:00Z",
                "end_at": "2026-08-01T02:00:00Z",
                "baseline_adjusted_energy_kwh": 120.0,
                "reporting_energy_kwh": 110.0,
                "baseline_adjusted_carbon_kg": 48.0,
                "reporting_carbon_kg": 44.0,
                "baseline_standard_uncertainty_kwh": 1.0,
                "reporting_standard_uncertainty_kwh": 1.0,
                "baseline_standard_uncertainty_carbon_kg": 0.4,
                "reporting_standard_uncertainty_carbon_kg": 0.4,
                "quality": "measured",
                "source_record_id": "meter-row-0002",
                "source_payload_sha256": HASH_B,
            },
        ],
        "meter_calibrations": [
            {
                "meter_id": "METER-REVENUE-01",
                "certificate_id": "CAL-2026-001",
                "valid_from": "2026-01-01T00:00:00Z",
                "valid_through": "2026-12-31T23:59:59Z",
                "certificate_sha256": HASH_C,
                "status": "valid",
            }
        ],
        "invoice_reconciliation": {
            "reconciliation_id": "invoice-recon-2026-08",
            "revenue_meter_id": "METER-REVENUE-01",
            "invoice_energy_kwh": 200.0,
            "interval_energy_kwh": 200.0,
            "variance_pct": 0.0,
            "status": "reconciled",
            "approved_by": "finance-energy-reviewer",
            "evidence_sha256": HASH_D,
        },
        "non_routine_adjustments": [],
        "non_routine_adjustment_declaration_sha256": HASH_F,
        "emission_factor_registry": {
            "registry_id": "site-factor-register",
            "registry_version": "2026.08",
            "registry_sha256": HASH_E,
            "approved_by": "carbon-manager",
        },
        "independent_verification": {
            "reviewer_id": "independent-reviewer-01",
            "organization": "Independent Assurance Example",
            "independence_attested": True,
            "reviewed_at": "2026-08-10T09:00:00Z",
            "conclusion": "accepted",
            "key_id": VERIFIER_KEY_ID,
            "signed_evidence_sha256": HASH_A,
            "signature": base64.b64encode(b"0" * 64).decode("ascii"),
        },
    }
    provisional = MeasurementVerificationRequest(**payload).model_dump(mode="json")
    unsigned_independent = dict(provisional["independent_verification"])
    unsigned_independent.pop("signature")
    unsigned_independent.pop("signed_evidence_sha256")
    provisional["independent_verification"] = unsigned_independent
    signed_evidence_sha256 = canonical_sha256(provisional)
    payload["independent_verification"]["signed_evidence_sha256"] = signed_evidence_sha256
    payload["independent_verification"]["signature"] = base64.b64encode(
        VERIFIER_PRIVATE_KEY.sign(bytes.fromhex(signed_evidence_sha256))
    ).decode("ascii")
    return payload


def test_default_report_preserves_scenario_difference_but_blocks_field_claims() -> None:
    report = measurement_verification_service.build_default(
        dataset_id="public-benchmark",
        dataset_sha256=HASH_A,
        trajectory_steps=24,
        baseline_energy_kwh=1200.0,
        reporting_energy_kwh=1000.0,
        baseline_carbon_kg=500.0,
        reporting_carbon_kg=420.0,
        baseline_cost_cny=9000.0,
        reporting_cost_cny=8000.0,
    )

    assert report.status == "blocked"
    assert report.results["scenario_energy_difference_kwh"] == 200.0
    assert report.results["scenario_carbon_difference_kg"] == 80.0
    assert report.results["verified_energy_savings_kwh"] is None
    assert report.results["verified_carbon_reduction_kg"] is None
    assert report.assurance["verified_savings_claim_allowed"] is False
    assert report.production_boundary["field_savings_verified"] is False
    assert all(not gate["passed"] for gate in report.gates)
    assert len(report.evidence_sha256) == 64


def test_complete_site_evidence_package_calculates_and_accepts_verified_values() -> None:
    request = MeasurementVerificationRequest(**complete_evidence_payload())
    service = MeasurementVerificationService(
        verifier_public_keys={VERIFIER_KEY_ID: VERIFIER_PUBLIC_KEY_B64}
    )
    report = service.evaluate(request)

    assert report.status == "evidence_package_passed"
    assert report.assurance["calculation_ready"] is True
    assert report.assurance["independent_verification_evidence_accepted"] is True
    assert report.assurance["software_is_verifier"] is False
    assert report.results["calculated_energy_savings_kwh"] == 20.0
    assert report.results["verified_energy_savings_kwh"] == 20.0
    assert report.results["verified_carbon_reduction_kg"] == 8.0
    assert report.results["verified_financial_savings_cny"] is None
    assert report.uncertainty["energy_savings_interval_kwh"] == [16.08, 23.92]
    assert report.uncertainty["carbon_savings_interval_kg"] == [6.432, 9.568]
    assert all(gate["passed"] for gate in report.gates)
    assert report.production_boundary["regulatory_submission_allowed"] is False


def test_estimated_data_over_approved_limit_fails_closed() -> None:
    payload = deepcopy(complete_evidence_payload())
    payload["intervals"][0]["quality"] = "estimated"
    request = MeasurementVerificationRequest(**payload)
    service = MeasurementVerificationService(
        verifier_public_keys={VERIFIER_KEY_ID: VERIFIER_PUBLIC_KEY_B64}
    )
    report = service.evaluate(request)

    assert report.status == "blocked"
    assert report.data_quality["estimated_pct"] == 50.0
    assert report.results["calculated_energy_savings_kwh"] is None
    assert report.results["verified_energy_savings_kwh"] is None
    assert "interval_coverage" in report.assurance["blocker_codes"]


def test_tampered_package_cannot_unlock_verified_savings() -> None:
    payload = complete_evidence_payload()
    payload["project_id"] = "terminal-efficiency-project-tampered"
    request = MeasurementVerificationRequest(**payload)
    service = MeasurementVerificationService(
        verifier_public_keys={VERIFIER_KEY_ID: VERIFIER_PUBLIC_KEY_B64}
    )
    report = service.evaluate(request)

    assert report.status == "calculated_pending_independent_verification"
    assert report.results["calculated_energy_savings_kwh"] == 20.0
    assert report.results["verified_energy_savings_kwh"] is None
    independent_gate = next(
        gate for gate in report.gates if gate["gate_id"] == "independent_verification"
    )
    assert independent_gate["evidence"]["signature_valid"] is False


def test_measurement_verification_evaluate_api_returns_hashed_receipt() -> None:
    response = TestClient(app).post(
        "/api/dashboard/measurement-verification/evaluate",
        json=complete_evidence_payload(),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "calculated_pending_independent_verification"
    assert payload["results"]["verified_energy_savings_kwh"] is None
    assert payload["report_id"].startswith("mv:")
    assert len(payload["input_evidence_sha256"]) == 64
    assert len(payload["evidence_sha256"]) == 64
