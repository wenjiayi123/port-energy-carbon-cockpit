from __future__ import annotations

import base64
from copy import deepcopy

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient
import pytest

from app.main import app
from app.schemas.port_collaboration import SOURCE_DOMAINS, PortCollaborationRequest
from app.services.port_collaboration import (
    PortCollaborationService,
    canonical_sha256,
    source_domain_payload,
)


SIGNATURE_PLACEHOLDER = base64.b64encode(b"0" * 64).decode("ascii")


def _payload() -> dict:
    return {
        "schema_version": "port-collaboration-input.v1",
        "case_id": "green-corridor-2026-08",
        "evaluated_at": "2026-08-02T12:00:00+08:00",
        "policy": {
            "policy_id": "corridor-policy-v1",
            "corridor_id": "corridor-port-a-port-b",
            "port_id": "port-b",
            "currency": "CNY",
            "window": {
                "window_id": "window-2026-08-01",
                "start_at": "2026-08-01T00:00:00+08:00",
                "end_at": "2026-08-05T00:00:00+08:00",
            },
            "maximum_arrival_deviation_minutes": 15.0,
            "minimum_advice_lead_hours": 6.0,
            "maximum_amount_variance_pct": 0.1,
            "maximum_source_age_seconds": 86400,
            "maximum_source_alignment_seconds": 60,
            "marine_fuel_emission_factor_kg_per_tonne": 3200.0,
            "jit_priority_points": 30.0,
            "shore_power_priority_points": 40.0,
            "alternative_fuel_priority_points": 30.0,
            "jit_fee_discount_pct": 2.0,
            "shore_power_fee_discount_pct": 3.0,
            "alternative_fuel_fee_discount_pct": 2.0,
            "maximum_total_fee_discount_pct": 7.0,
            "port_benefit_share_pct": 40.0,
            "vessel_operator_benefit_share_pct": 60.0,
            "eligible_alternative_fuels": ["green_methanol", "green_ammonia"],
            "charter_sha256": "a" * 64,
            "allocation_rule_sha256": "b" * 64,
            "approved_by": "corridor-board",
            "approval_record_sha256": "c" * 64,
        },
        "vessel_calls": [
            {
                "vessel_call_id": "call-001",
                "imo_number": "IMO1234567",
                "vessel_name": "Example Green Vessel",
                "vessel_operator_id": "operator-a",
                "origin_port_id": "port-a",
                "destination_port_id": "port-b",
                "original_eta": "2026-08-01T08:00:00+08:00",
                "advice_issued_at": "2026-08-01T00:00:00+08:00",
                "agreed_arrival_at": "2026-08-01T10:00:00+08:00",
                "actual_arrival_at": "2026-08-01T10:05:00+08:00",
                "distance_to_go_nm": 100.0,
                "baseline_speed_knots": 15.0,
                "advised_speed_knots": 10.0,
                "baseline_fuel_tonnes": 20.0,
                "actual_fuel_tonnes": 18.0,
                "operator_accepted": True,
                "acceptance_record_sha256": "d" * 64,
                "fuel_evidence_sha256": "e" * 64,
            }
        ],
        "milestones": [
            {
                "vessel_call_id": "call-001",
                "berth_id": "berth-01",
                "terminal_ready_at": "2026-08-01T09:30:00+08:00",
                "berth_window_start_at": "2026-08-01T09:45:00+08:00",
                "berth_window_end_at": "2026-08-01T12:00:00+08:00",
                "all_fast_at": "2026-08-01T10:30:00+08:00",
                "cargo_operations_start_at": "2026-08-01T11:00:00+08:00",
                "cargo_operations_end_at": "2026-08-02T06:00:00+08:00",
                "departure_at": "2026-08-02T07:00:00+08:00",
                "milestone_record_sha256": "f" * 64,
            }
        ],
        "berth_assignments": [
            {
                "vessel_call_id": "call-001",
                "berth_id": "berth-01",
                "assigned_at": "2026-08-01T00:00:00+08:00",
                "jit_eligible": True,
                "shore_power_eligible": True,
                "alternative_fuel_eligible": True,
                "declared_priority_score": 100.0,
                "assigned_priority_rank": 1,
                "fairness_cohort_id": "cohort-container-2026-08-01",
                "allocation_rule_sha256": "b" * 64,
                "approved": True,
                "assignment_record_sha256": "1" * 64,
            }
        ],
        "shore_power_reservations": [
            {
                "reservation_id": "shore-reservation-001",
                "vessel_call_id": "call-001",
                "berth_id": "berth-01",
                "service_start_at": "2026-08-01T11:00:00+08:00",
                "service_end_at": "2026-08-02T05:00:00+08:00",
                "vessel_compatible": True,
                "berth_compatible": True,
                "reserved_capacity_kw": 1000.0,
                "berth_capacity_kw": 1500.0,
                "metered_energy_kwh": 12000.0,
                "energy_rate_per_kwh": 0.5,
                "connection_fee": 100.0,
                "stated_invoice_amount": 6100.0,
                "currency": "CNY",
                "status": "settled",
                "meter_record_sha256": "2" * 64,
                "invoice_sha256": "3" * 64,
                "settlement_receipt_sha256": "4" * 64,
            }
        ],
        "alternative_fuel_services": [
            {
                "service_id": "fuel-service-001",
                "vessel_call_id": "call-001",
                "fuel_type": "green_methanol",
                "requested_quantity_tonnes": 50.0,
                "available_inventory_tonnes": 100.0,
                "maximum_transfer_rate_tonnes_per_hour": 25.0,
                "service_hours": 2.0,
                "permit_valid_through": "2026-08-31T23:59:59+08:00",
                "compatible_transfer_equipment": True,
                "trained_staff_available": True,
                "safety_case_approved": True,
                "emergency_drill_passed": True,
                "risk_assessment_accepted": True,
                "status": "served",
                "permit_sha256": "5" * 64,
                "safety_case_sha256": "6" * 64,
                "service_receipt_sha256": "7" * 64,
            }
        ],
        "port_fee_incentives": [
            {
                "invoice_id": "port-fee-001",
                "vessel_call_id": "call-001",
                "base_port_fee": 10000.0,
                "declared_discount_pct": 7.0,
                "stated_payable_amount": 9300.0,
                "currency": "CNY",
                "status": "paid",
                "incentive_rule_sha256": "b" * 64,
                "invoice_sha256": "8" * 64,
                "payment_receipt_sha256": "9" * 64,
            }
        ],
        "emission_benefit_claims": [
            {
                "claim_id": "claim-jit-001",
                "vessel_call_id": "call-001",
                "category": "jit_arrival",
                "verified_reduction_tco2e": 6.4,
                "verification_status": "independently_verified",
                "evidence_sha256": "0" * 64,
            },
            {
                "claim_id": "claim-shore-001",
                "vessel_call_id": "call-001",
                "category": "shore_power",
                "verified_reduction_tco2e": 3.0,
                "verification_status": "independently_verified",
                "evidence_sha256": "1" * 64,
            },
            {
                "claim_id": "claim-fuel-001",
                "vessel_call_id": "call-001",
                "category": "alternative_fuel",
                "verified_reduction_tco2e": 5.0,
                "verification_status": "independently_verified",
                "evidence_sha256": "2" * 64,
            },
        ],
        "benefit_sharing": [
            {
                "allocation_id": "benefit-allocation-001",
                "vessel_call_id": "call-001",
                "verified_reduction_tco2e": 14.4,
                "value_per_tco2e": 100.0,
                "total_benefit_value": 1440.0,
                "port_benefit_amount": 576.0,
                "vessel_operator_benefit_amount": 864.0,
                "currency": "CNY",
                "status": "settled",
                "port_approval_sha256": "3" * 64,
                "vessel_operator_approval_sha256": "4" * 64,
                "settlement_receipt_sha256": "5" * 64,
            }
        ],
        "approvals": [
            {
                "approval_id": "approval-port-001",
                "role": "port_authority",
                "approver_id": "port-officer",
                "decision": "approved",
                "approved_at": "2026-08-02T10:00:00+08:00",
                "charter_sha256": "a" * 64,
                "approval_record_sha256": "6" * 64,
            },
            {
                "approval_id": "approval-vessel-001",
                "role": "vessel_operator",
                "approver_id": "operator-officer",
                "decision": "approved",
                "approved_at": "2026-08-02T10:15:00+08:00",
                "charter_sha256": "a" * 64,
                "approval_record_sha256": "7" * 64,
            },
        ],
        "source_attestations": [
            {
                "domain": domain,
                "source_system": f"{domain}-system",
                "source_record_ids": [f"{domain}-record"],
                "observed_at": "2026-08-02T11:45:00+08:00",
                "live_data_verified": True,
                "key_id": f"{domain}-key",
                "signed_payload_sha256": "0" * 64,
                "signature": SIGNATURE_PLACEHOLDER,
            }
            for domain in sorted(SOURCE_DOMAINS)
        ],
    }


def _service_and_keys() -> tuple[PortCollaborationService, dict[str, Ed25519PrivateKey]]:
    private_keys = {domain: Ed25519PrivateKey.generate() for domain in SOURCE_DOMAINS}
    public_keys = {
        f"{domain}-key": base64.b64encode(
            key.public_key().public_bytes(
                encoding=serialization.Encoding.Raw,
                format=serialization.PublicFormat.Raw,
            )
        ).decode("ascii")
        for domain, key in private_keys.items()
    }
    return PortCollaborationService(source_public_keys=public_keys), private_keys


def _signed_request(
    payload: dict,
    private_keys: dict[str, Ed25519PrivateKey],
) -> PortCollaborationRequest:
    request = PortCollaborationRequest(**deepcopy(payload))
    normalized = request.model_dump(mode="json")
    attestations = {item["domain"]: item for item in normalized["source_attestations"]}
    for domain in SOURCE_DOMAINS:
        digest = canonical_sha256(source_domain_payload(request, domain))
        attestations[domain]["signed_payload_sha256"] = digest
        attestations[domain]["signature"] = base64.b64encode(
            private_keys[domain].sign(bytes.fromhex(digest))
        ).decode("ascii")
    normalized["source_attestations"] = [attestations[domain] for domain in sorted(SOURCE_DOMAINS)]
    return PortCollaborationRequest(**normalized)


def test_default_keeps_public_vessel_activity_out_of_verified_collaboration() -> None:
    report = PortCollaborationService(source_public_keys={}).build_default(
        scenario_shore_power_usage_rate=62.5,
        scenario_vessel_activity_source="public_daily_activity_expanded_to_hours",
    )

    assert report.status == "blocked"
    assert len(report.gates) == 15
    assert not any(gate["passed"] for gate in report.gates)
    assert report.source_readiness["domain_count"] == 0
    assert report.jit_arrival["verified_call_count"] is None
    assert report.shore_power["scenario_usage_rate_pct"] == 62.5
    assert report.benefit_sharing["verified_total_benefit_value"] is None
    assert report.production_boundary["vessel_speed_instruction_allowed"] is False


def test_seven_signed_domains_close_all_fifteen_collaboration_gates() -> None:
    service, private_keys = _service_and_keys()
    report = service.evaluate(_signed_request(_payload(), private_keys))

    assert report.status == "evidence_package_passed"
    assert all(gate["passed"] for gate in report.gates)
    assert report.source_readiness["domain_count"] == 7
    assert len(report.source_readiness["signed_domains"]) == 7
    assert report.jit_arrival["verified_call_count"] == 1
    assert report.jit_arrival["verified_on_time_rate_pct"] == 100.0
    assert report.jit_arrival["verified_fuel_savings_tonnes"] == 2.0
    assert report.jit_arrival["verified_reduction_tco2e"] == 6.4
    assert report.green_berth["verified_assignment_count"] == 1
    assert report.shore_power["verified_energy_kwh"] == 12000.0
    assert report.shore_power["verified_settlement_amount"] == 6100.0
    assert report.alternative_fuel["verified_served_quantity_tonnes"] == 50.0
    assert report.incentives["verified_discount_amount"] == 700.0
    assert report.benefit_sharing["verified_total_benefit_value"] == 1440.0
    assert report.benefit_sharing["verified_port_benefit_amount"] == 576.0
    assert report.benefit_sharing["verified_vessel_operator_benefit_amount"] == 864.0
    assert report.production_boundary["berth_plan_writeback_allowed"] is False
    assert report.production_boundary["fuel_bunkering_authorization_allowed"] is False


def test_tampering_one_domain_withholds_all_verified_values() -> None:
    service, private_keys = _service_and_keys()
    request = _signed_request(_payload(), private_keys)
    tampered = request.model_copy(
        update={
            "vessel_calls": [
                request.vessel_calls[0].model_copy(
                    update={"fuel_evidence_sha256": "f" * 64}
                )
            ]
        }
    )
    report = service.evaluate(tampered)

    assert report.status == "reconciled_pending_source_attestation"
    assert report.assurance["calculation_ready"] is True
    assert report.jit_arrival["calculated_fuel_savings_tonnes"] == 2.0
    assert report.jit_arrival["verified_fuel_savings_tonnes"] is None
    assert report.benefit_sharing["verified_total_benefit_value"] is None


@pytest.mark.parametrize(
    ("mutation", "gate_id"),
    [
        (lambda value: value["vessel_calls"][0].update(operator_accepted=False), "jit_consent_and_notice"),
        (lambda value: value["vessel_calls"][0].update(actual_arrival_at="2026-08-01T11:00:00+08:00"), "jit_arrival_and_fuel"),
        (lambda value: value["milestones"][0].update(terminal_ready_at="2026-08-01T10:15:00+08:00"), "berth_milestones"),
        (lambda value: value["berth_assignments"][0].update(declared_priority_score=90.0), "green_berth_priority"),
        (lambda value: value["shore_power_reservations"][0].update(vessel_compatible=False), "shore_power_reservation"),
        (lambda value: value["shore_power_reservations"][0].update(stated_invoice_amount=6200.0), "shore_power_meter_billing"),
        (lambda value: value["alternative_fuel_services"][0].update(trained_staff_available=False), "alternative_fuel_readiness"),
        (lambda value: value["port_fee_incentives"][0].update(stated_payable_amount=9500.0), "port_fee_incentive"),
        (lambda value: value["benefit_sharing"][0].update(port_benefit_amount=700.0), "benefit_sharing"),
        (lambda value: value["approvals"][1].update(approver_id="port-officer"), "dual_approval_audit"),
    ],
)
def test_collaboration_failures_close_the_named_gate(mutation, gate_id: str) -> None:
    service, private_keys = _service_and_keys()
    payload = _payload()
    mutation(payload)
    report = service.evaluate(_signed_request(payload, private_keys))

    assert report.status == "blocked"
    gate = next(item for item in report.gates if item["gate_id"] == gate_id)
    assert gate["passed"] is False
    assert report.jit_arrival["verified_call_count"] is None
    assert report.benefit_sharing["verified_total_benefit_value"] is None


def test_dashboard_api_exposes_fail_closed_collaboration_default() -> None:
    response = TestClient(app).get("/api/dashboard/port-collaboration")
    payload = response.json()

    assert response.status_code == 200
    assert payload["schema_version"] == "port-call-collaboration.v1"
    assert payload["status"] == "blocked"
    assert payload["source_readiness"]["domain_count"] == 0
    assert len(payload["gates"]) == 15
    assert payload["jit_arrival"]["verified_call_count"] is None
    assert payload["production_boundary"]["port_invoice_issue_allowed"] is False
    assert len(payload["evidence_sha256"]) == 64


def test_api_with_unconfigured_keys_keeps_calculations_unverified() -> None:
    _, private_keys = _service_and_keys()
    request = _signed_request(_payload(), private_keys)
    response = TestClient(app).post(
        "/api/dashboard/port-collaboration/evaluate",
        json=request.model_dump(mode="json"),
    )
    payload = response.json()

    assert response.status_code == 200
    assert payload["status"] == "reconciled_pending_source_attestation"
    assert payload["assurance"]["calculation_ready"] is True
    assert payload["assurance"]["collaboration_verified"] is False
    assert payload["jit_arrival"]["calculated_fuel_savings_tonnes"] == 2.0
    assert payload["jit_arrival"]["verified_fuel_savings_tonnes"] is None
