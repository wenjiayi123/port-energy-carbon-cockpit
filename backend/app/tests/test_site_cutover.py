import base64
from copy import deepcopy
from datetime import datetime, timezone

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.schemas.site_cutover import (
    APPROVAL_ROLES,
    MODULE_DOMAINS,
    REQUIRED_SHADOW_SCENARIOS,
    CutoverModuleEvidence,
    SiteCutoverRequest,
)
from app.services.site_cutover import (
    SiteCutoverService,
    approval_subject_sha256,
    canonical_sha256,
    module_signature_payload,
)


HASH = "a" * 64
EVALUATED_AT = datetime(2026, 7, 15, 12, tzinfo=timezone.utc)


def _public_key(private_key: Ed25519PrivateKey) -> str:
    return base64.b64encode(
        private_key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
    ).decode("ascii")


def _payload() -> dict:
    placeholder_signature = base64.b64encode(b"x" * 64).decode("ascii")
    modules = [
        {
            "domain": domain,
            "schema_version": f"{domain}.v1",
            "report_id": f"report:{domain}:001",
            "report_status": "accepted",
            "evidence_sha256": HASH,
            "site_id": "port-site-001",
            "tenant_id": "terminal-tenant-001",
            "assessment_window_id": "window-2026-h1",
            "data_cutoff_at": "2026-07-01T00:00:00Z",
            "observed_at": "2026-07-10T00:00:00Z",
            "source_mode": "production_shadow"
            if domain
            in {"production_execution", "long_horizon_shadow", "algorithm_production"}
            else "live_site",
            "owner_system": f"owner-{domain}",
            "source_record_ids": [f"record-{domain}"],
            "independently_verified": True,
            "acceptance_conclusion": "accepted",
            "exception_ids": [],
            "key_id": f"module-key-{domain}",
            "signed_payload_sha256": "0" * 64,
            "signature": placeholder_signature,
        }
        for domain in sorted(MODULE_DOMAINS)
    ]
    approvals = [
        {
            "approval_id": f"approval-{role}",
            "role": role,
            "approver_id": f"person-{role}",
            "decision": "approved",
            "approved_at": "2026-07-10T12:00:00Z",
            "acceptance_package_sha256": "0" * 64,
            "approval_record_sha256": HASH,
            "key_id": f"approval-key-{role}",
            "signature": placeholder_signature,
        }
        for role in sorted(APPROVAL_ROLES)
    ]
    return {
        "schema_version": "site-cutover-input.v1",
        "case_id": "cutover-case-001",
        "evaluated_at": EVALUATED_AT.isoformat(),
        "policy": {
            "policy_id": "site-cutover-policy-001",
            "site_id": "port-site-001",
            "tenant_id": "terminal-tenant-001",
            "target_release": "release-2026.07",
            "window": {
                "window_id": "window-2026-h1",
                "start_at": "2026-01-01T00:00:00Z",
                "end_at": "2026-07-01T00:00:00Z",
            },
            "configuration_sha256": HASH,
            "infrastructure_as_code_sha256": HASH,
            "minimum_shadow_days": 180,
            "minimum_operating_season_count": 2,
            "maximum_module_age_days": 30,
            "maximum_data_cutoff_alignment_hours": 24,
            "maximum_energy_balance_error_pct": 1.0,
            "maximum_bill_reconciliation_error_pct": 0.5,
            "maximum_rollback_minutes": 30,
            "maximum_rpo_minutes": 15,
            "maximum_rto_minutes": 60,
        },
        "module_evidence": modules,
        "operational_evidence": {
            "ready_live_adapter_count": 6,
            "required_live_adapter_count": 6,
            "accepted_live_snapshot_count": 20_000,
            "composite_shadow_release_count": 10_000,
            "meter_coverage_pct": 100,
            "calibrated_meter_coverage_pct": 100,
            "energy_balance_error_pct": 0.4,
            "bill_reconciliation_error_pct": 0.2,
            "shadow_run_days": 183,
            "operating_seasons": ["peak", "off_peak"],
            "covered_shadow_scenarios": sorted(REQUIRED_SHADOW_SCENARIOS),
            "production_instruction_gateway_external": True,
            "device_capability_checks_passed": True,
            "independent_plc_interlocks_tested": True,
            "device_receipt_rate_pct": 100,
            "command_timeout_fallback_tested": True,
            "human_takeover_drill_passed": True,
            "rollback_drill_passed": True,
            "measured_rollback_minutes": 12,
            "backup_restore_drill_passed": True,
            "measured_rpo_minutes": 5,
            "measured_rto_minutes": 20,
            "cyber_incident_exercise_passed": True,
            "unresolved_severity_1_count": 0,
            "unresolved_severity_2_count": 0,
            "operator_training_coverage_pct": 100,
            "approved_sop_sha256": HASH,
            "approved_runbook_sha256": HASH,
            "safety_case_sha256": HASH,
            "independent_mv_accepted": True,
            "benefit_attribution_report_sha256": HASH,
            "change_ticket_id": "CHANGE-2026-001",
            "change_window_start_at": "2026-07-20T00:00:00Z",
            "change_window_end_at": "2026-07-20T04:00:00Z",
            "production_authority_disabled_in_application": True,
        },
        "approvals": approvals,
    }


def _sign(payload: dict) -> tuple[SiteCutoverRequest, dict[str, dict[str, str]]]:
    value = deepcopy(payload)
    private_keys: dict[str, Ed25519PrivateKey] = {}
    trusted_signers: dict[str, dict[str, str]] = {}
    for module in value["module_evidence"]:
        key = Ed25519PrivateKey.generate()
        private_keys[module["key_id"]] = key
        trusted_signers[module["key_id"]] = {
            "public_key": _public_key(key),
            "authority": module["domain"],
        }
        provisional = CutoverModuleEvidence(**module)
        digest = canonical_sha256(module_signature_payload(provisional))
        module["signed_payload_sha256"] = digest
        module["signature"] = base64.b64encode(key.sign(bytes.fromhex(digest))).decode("ascii")

    provisional_request = SiteCutoverRequest(**value)
    subject = approval_subject_sha256(provisional_request)
    for approval in value["approvals"]:
        key = Ed25519PrivateKey.generate()
        trusted_signers[approval["key_id"]] = {
            "public_key": _public_key(key),
            "authority": approval["role"],
        }
        approval["acceptance_package_sha256"] = subject
        approval["signature"] = base64.b64encode(key.sign(bytes.fromhex(subject))).decode("ascii")
    return SiteCutoverRequest(**value), trusted_signers


def test_default_unifies_repository_reports_without_claiming_site_acceptance() -> None:
    reports = {
        domain: {
            "schema_version": f"{domain}.v1",
            "report_id": f"report:{domain}",
            "report_status": "blocked",
            "evidence_sha256": HASH,
        }
        for domain in MODULE_DOMAINS
    }
    report = SiteCutoverService(trusted_signers={}).build_default(reports)

    assert report.status == "blocked"
    assert report.source_readiness["repository_report_count"] == 13
    assert report.source_readiness["accepted_domain_count"] == 0
    assert report.assurance["passed_gate_count"] == 0
    assert len(report.domain_evidence) == 13
    assert report.production_boundary["production_authority"] is False


def test_thirteen_domains_and_six_approvals_close_all_cutover_gates() -> None:
    request, trusted_signers = _sign(_payload())
    report = SiteCutoverService(trusted_signers=trusted_signers).evaluate(request)

    assert report.status == "eligible_for_external_cutover_review"
    assert report.source_readiness["signed_domain_count"] == 13
    assert report.source_readiness["accepted_domain_count"] == 13
    assert report.assurance["passed_gate_count"] == 16
    assert report.operational_acceptance["verified_shadow_days"] == 183
    assert report.approval_summary["all_bound_to_package"] is True
    assert report.production_boundary["cutover_plan_export_allowed"] is True
    assert report.production_boundary["production_authority"] is False
    assert report.production_boundary["automatic_cutover_allowed"] is False


def test_tampered_module_signature_withholds_verified_cutover_values() -> None:
    request, trusted_signers = _sign(_payload())
    tampered = request.model_dump(mode="json")
    tampered["module_evidence"][0]["report_status"] = "tampered"

    report = SiteCutoverService(trusted_signers=trusted_signers).evaluate(
        SiteCutoverRequest(**tampered)
    )

    assert report.status == "blocked"
    assert next(gate for gate in report.gates if gate["gate_id"] == "module_signatures")[
        "passed"
    ] is False
    assert report.site_consistency["verified_site_id"] is None
    assert report.operational_acceptance["verified_shadow_days"] is None


def test_approval_signatures_bind_exact_operational_package() -> None:
    request, trusted_signers = _sign(_payload())
    changed = request.model_dump(mode="json")
    changed["operational_evidence"]["accepted_live_snapshot_count"] += 1

    report = SiteCutoverService(trusted_signers=trusted_signers).evaluate(
        SiteCutoverRequest(**changed)
    )

    assert report.status == "blocked"
    assert next(gate for gate in report.gates if gate["gate_id"] == "binding_approvals")[
        "passed"
    ] is False
    assert report.approval_summary["all_bound_to_package"] is False


@pytest.mark.parametrize(
    ("mutation", "gate_id"),
    [
        (
            lambda value: value["module_evidence"][0].update(site_id="another-site"),
            "site_tenant_window",
        ),
        (
            lambda value: value["operational_evidence"].update(ready_live_adapter_count=5),
            "live_data_closed_loop",
        ),
        (
            lambda value: value["operational_evidence"].update(meter_coverage_pct=99.9),
            "metering_and_calibration",
        ),
        (
            lambda value: value["operational_evidence"].update(shadow_run_days=179),
            "long_horizon_shadow",
        ),
        (
            lambda value: value["operational_evidence"].update(device_receipt_rate_pct=99.9),
            "production_execution",
        ),
        (
            lambda value: value["operational_evidence"].update(rollback_drill_passed=False),
            "takeover_and_rollback",
        ),
        (
            lambda value: value["operational_evidence"].update(measured_rto_minutes=61),
            "resilience_and_restore",
        ),
        (
            lambda value: value["operational_evidence"].update(
                unresolved_severity_2_count=1
            ),
            "cyber_readiness",
        ),
    ],
)
def test_named_site_cutover_failure_closes_its_gate(mutation, gate_id: str) -> None:
    payload = _payload()
    mutation(payload)
    request, trusted_signers = _sign(payload)

    report = SiteCutoverService(trusted_signers=trusted_signers).evaluate(request)

    assert report.status == "blocked"
    assert next(gate for gate in report.gates if gate["gate_id"] == gate_id)["passed"] is False
    assert report.production_boundary["production_authority"] is False


def test_dashboard_api_exposes_default_site_cutover_summary() -> None:
    response = TestClient(create_app()).get("/api/dashboard/site-cutover-readiness")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "blocked"
    assert payload["source_readiness"]["repository_report_count"] == 13
    assert payload["source_readiness"]["accepted_domain_count"] == 0
    assert len(payload["gates"]) == 16


def test_api_without_trusted_signers_keeps_valid_calculations_unattested() -> None:
    request, _ = _sign(_payload())
    response = TestClient(create_app()).post(
        "/api/dashboard/site-cutover-readiness/evaluate",
        json=request.model_dump(mode="json"),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "reconciled_pending_attestation"
    assert payload["assurance"]["passed_gate_count"] == 14
    assert payload["site_consistency"]["verified_site_id"] is None
    assert payload["production_boundary"]["production_authority"] is False
