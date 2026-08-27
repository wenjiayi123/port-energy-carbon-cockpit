import base64
from copy import deepcopy
import hashlib
import json

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

from app.main import app
from app.schemas.energy_carbon_management import EnergyCarbonManagementRequest
from app.services.energy_carbon_management import EnergyCarbonManagementService


HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64
HASH_D = "d" * 64
HASH_E = "e" * 64
AUDITOR_KEY_ID = "test-management-assurance-key"
AUDITOR_PRIVATE_KEY = Ed25519PrivateKey.generate()
AUDITOR_PUBLIC_KEY_B64 = base64.b64encode(
    AUDITOR_PRIVATE_KEY.public_key().public_bytes(
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


def complete_management_payload() -> dict:
    payload = {
        "schema_version": "energy-carbon-management-system-input.v1",
        "cycle_id": "terminal-a-2026-management-cycle",
        "cycle_period": {
            "start_at": "2026-01-01T00:00:00Z",
            "end_at": "2026-12-31T23:59:59Z",
        },
        "context": {
            "system_id": "terminal-a-energy-carbon-system",
            "reporting_entity": "Example Terminal Operator",
            "site_ids": ["TERMINAL-A"],
            "organizational_boundary": "Operational control over Terminal A",
            "operational_boundary": "All seven port emission source categories and purchased energy",
            "standard_references": [
                "ISO 50001:2018/Amd 1:2024",
                "ISO 14064-1:2018",
            ],
            "applicable_requirements_register_id": "legal-register-2026-v1",
            "applicable_requirements_sha256": HASH_A,
            "context_review_sha256": HASH_B,
            "climate_change_relevance_reviewed": True,
            "approved_by": "port-director",
        },
        "policy": {
            "policy_id": "energy-carbon-policy-v3",
            "policy_sha256": HASH_C,
            "top_management_id": "port-director",
            "approved_at": "2025-12-01T09:00:00Z",
            "effective_at": "2025-12-15T00:00:00Z",
            "communicated_at": "2025-12-20T09:00:00Z",
            "continual_improvement_commitment": True,
            "information_and_resources_commitment": True,
        },
        "roles": [
            {
                "role": "top_management",
                "person_id": "port-director",
                "authority_scope": "Approve policy, objectives and resources",
                "assigned_at": "2025-11-01T00:00:00Z",
                "appointment_sha256": HASH_A,
            },
            {
                "role": "energy_manager",
                "person_id": "energy-manager",
                "authority_scope": "Own energy review, baselines and EnPIs",
                "assigned_at": "2025-11-01T00:00:00Z",
                "appointment_sha256": HASH_B,
            },
            {
                "role": "ghg_inventory_owner",
                "person_id": "carbon-manager",
                "authority_scope": "Own GHG inventory and factor register",
                "assigned_at": "2025-11-01T00:00:00Z",
                "appointment_sha256": HASH_C,
            },
            {
                "role": "operations_owner",
                "person_id": "operations-manager",
                "authority_scope": "Own significant-energy-use operating controls",
                "assigned_at": "2025-11-01T00:00:00Z",
                "appointment_sha256": HASH_D,
            },
            {
                "role": "internal_auditor",
                "person_id": "internal-auditor",
                "authority_scope": "Audit independently from operating responsibilities",
                "assigned_at": "2025-11-01T00:00:00Z",
                "appointment_sha256": HASH_E,
            },
        ],
        "energy_review": {
            "review_id": "energy-review-2025-v1",
            "reviewed_at": "2025-12-10T09:00:00Z",
            "total_energy_use_kwh": 1000000.0,
            "minimum_seu_coverage_pct": 80.0,
            "significant_energy_uses": [
                {
                    "seu_id": "seu-cranes",
                    "label": "Quay and yard cranes",
                    "asset_ids": ["QC-01", "YC-01"],
                    "energy_use_kwh": 600000.0,
                    "relevant_variables": ["handled_teu", "lift_count"],
                    "meter_ids": ["METER-CRANES"],
                    "operational_control_ids": ["CTRL-CRANES"],
                },
                {
                    "seu_id": "seu-reefer",
                    "label": "Reefer racks",
                    "asset_ids": ["REEFER-BLOCK-A"],
                    "energy_use_kwh": 250000.0,
                    "relevant_variables": ["plugged_reefer_hours", "ambient_temperature_c"],
                    "meter_ids": ["METER-REEFER"],
                    "operational_control_ids": ["CTRL-REEFER"],
                },
            ],
            "improvement_opportunities": [
                "crane regenerative braking",
                "reefer temperature-band coordination",
            ],
            "approved_by": "energy-manager",
            "review_sha256": HASH_A,
        },
        "energy_baseline": {
            "baseline_id": "terminal-a-enb-2025",
            "period": {
                "start_at": "2025-01-01T00:00:00Z",
                "end_at": "2025-12-31T00:00:00Z",
            },
            "baseline_energy_kwh": 1000000.0,
            "normalization_method": "Approved throughput and weather regression",
            "relevant_variables": ["handled_teu", "ambient_temperature_c"],
            "adjustment_triggers": ["asset boundary change", "material production change"],
            "frozen_at": "2025-12-31T12:00:00Z",
            "approved_by": "energy-manager",
            "model_sha256": HASH_B,
        },
        "enpis": [
            {
                "enpi_id": "enpi-kwh-per-teu",
                "label": "Normalized electricity per handled TEU",
                "unit": "kWh/TEU",
                "direction": "decrease",
                "baseline_value": 12.0,
                "target_value": 11.4,
                "current_value": 11.2,
                "measured_at": "2026-12-30T00:00:00Z",
                "owner_id": "energy-manager",
                "source_sha256": HASH_C,
            }
        ],
        "objectives": [
            {
                "objective_id": "objective-energy-intensity-2026",
                "enpi_id": "enpi-kwh-per-teu",
                "target_value": 11.4,
                "due_at": "2026-12-30T00:00:00Z",
                "owner_id": "energy-manager",
                "approved_by": "port-director",
                "approval_sha256": HASH_D,
            }
        ],
        "action_plans": [
            {
                "action_id": "action-crane-reefer-optimization",
                "objective_id": "objective-energy-intensity-2026",
                "owner_id": "operations-manager",
                "resources": ["metering engineer", "operations analyst"],
                "budget_cny": 500000.0,
                "start_at": "2026-01-02T00:00:00Z",
                "due_at": "2026-11-30T00:00:00Z",
                "status": "completed",
                "completion_evidence_sha256": HASH_E,
            }
        ],
        "monitoring": {
            "plan_id": "monitoring-plan-2026-v2",
            "measurement_frequency": "15-minute intervals",
            "meter_ids": ["METER-CRANES", "METER-REEFER"],
            "expected_record_count": 70080,
            "received_record_count": 70080,
            "minimum_coverage_pct": 99.0,
            "retention_days": 2555,
            "calibration_register_sha256": HASH_A,
            "correction_procedure_sha256": HASH_B,
            "measurement_verification_evidence_sha256": HASH_C,
            "approved_by": "energy-manager",
        },
        "operational_controls": [
            {
                "control_id": "CTRL-CRANES",
                "seu_id": "seu-cranes",
                "operational_criteria": "Use approved crane sequencing and demand ceiling",
                "owner_id": "operations-manager",
                "abnormal_response": "Revert to safe operating plan and notify energy manager",
                "control_record_sha256": HASH_D,
            },
            {
                "control_id": "CTRL-REEFER",
                "seu_id": "seu-reefer",
                "operational_criteria": "Maintain cargo-safe temperature bands and peak limits",
                "owner_id": "operations-manager",
                "abnormal_response": "Cargo safety overrides optimization and raises an alarm",
                "control_record_sha256": HASH_E,
            },
        ],
        "competence_records": [
            {
                "person_id": person,
                "role": role,
                "competence_assessed": True,
                "awareness_acknowledged": True,
                "completed_at": "2025-12-20T00:00:00Z",
                "valid_through": "2027-12-31T00:00:00Z",
                "evidence_sha256": HASH_A,
            }
            for role, person in [
                ("top_management", "port-director"),
                ("energy_manager", "energy-manager"),
                ("ghg_inventory_owner", "carbon-manager"),
                ("operations_owner", "operations-manager"),
                ("internal_auditor", "internal-auditor"),
            ]
        ],
        "ghg_inventory": {
            "inventory_report_id": "terminal-a-ghg-2026-r1",
            "inventory_period": {
                "start_at": "2026-01-01T00:00:00Z",
                "end_at": "2026-12-31T23:59:59Z",
            },
            "organizational_boundary_approach": "Operational control",
            "reporting_boundary": "Direct, energy indirect and material indirect port sources",
            "base_year": 2025,
            "expected_source_category_count": 7,
            "reported_source_category_count": 7,
            "factor_registry_id": "factor-register-2026",
            "factor_registry_version": "2026.12",
            "factor_registry_sha256": HASH_B,
            "inventory_evidence_sha256": HASH_C,
            "measurement_verification_evidence_sha256": HASH_D,
            "uncertainty_quantified": True,
            "recalculation_triggers": ["structural change", "methodology change", "material error"],
            "revision_id": "r1",
            "approved_by": "carbon-manager",
        },
        "internal_audit": {
            "audit_id": "internal-audit-2026",
            "auditor_id": "internal-auditor",
            "independence_attested": True,
            "completed_at": "2027-01-10T00:00:00Z",
            "scope_references": ["ISO 50001:2018", "ISO 14064-1:2018"],
            "conclusion": "minor_nonconformity",
            "finding_ids": ["FINDING-01"],
            "report_sha256": HASH_E,
        },
        "corrective_actions": [
            {
                "action_id": "CORRECTIVE-01",
                "finding_id": "FINDING-01",
                "root_cause": "A superseded work instruction remained visible",
                "owner_id": "operations-manager",
                "due_at": "2027-01-31T00:00:00Z",
                "status": "closed",
                "closed_at": "2027-01-20T00:00:00Z",
                "effectiveness_verified": True,
                "evidence_sha256": HASH_A,
            }
        ],
        "no_finding_declaration_sha256": None,
        "management_review": {
            "review_id": "management-review-2026",
            "reviewed_at": "2027-01-25T00:00:00Z",
            "chair_id": "port-director",
            "input_topics": [
                "energy_performance",
                "objectives_and_action_plans",
                "monitoring_and_measurement",
                "ghg_inventory",
                "internal_audit",
                "corrective_actions",
                "resources",
            ],
            "decisions": ["Continue EnPI target", "Expand feeder metering"],
            "resources_approved": ["2027 metering budget", "one energy analyst"],
            "review_sha256": HASH_B,
        },
        "independent_assurance": {
            "reviewer_id": "external-assurance-reviewer",
            "organization": "Independent Assurance Example",
            "independence_attested": True,
            "reviewed_at": "2027-02-01T00:00:00Z",
            "conclusion": "accepted",
            "key_id": AUDITOR_KEY_ID,
            "signed_evidence_sha256": HASH_A,
            "signature": base64.b64encode(b"0" * 64).decode("ascii"),
        },
    }
    provisional = EnergyCarbonManagementRequest(**payload).model_dump(mode="json")
    unsigned_assurance = dict(provisional["independent_assurance"])
    unsigned_assurance.pop("signature")
    unsigned_assurance.pop("signed_evidence_sha256")
    provisional["independent_assurance"] = unsigned_assurance
    signed_evidence_sha256 = canonical_sha256(provisional)
    payload["independent_assurance"]["signed_evidence_sha256"] = (
        signed_evidence_sha256
    )
    payload["independent_assurance"]["signature"] = base64.b64encode(
        AUDITOR_PRIVATE_KEY.sign(bytes.fromhex(signed_evidence_sha256))
    ).decode("ascii")
    return payload


def test_default_management_state_blocks_all_management_claims() -> None:
    service = EnergyCarbonManagementService(auditor_public_keys={})
    report = service.build_default(
        inventory_evidence_sha256=HASH_A,
        inventory_status="source_incomplete",
        measurement_verification_evidence_sha256=HASH_B,
        measurement_verification_status="blocked",
    )

    assert report.status == "blocked"
    assert len(report.gates) == 15
    assert all(not gate["passed"] for gate in report.gates)
    assert report.pdca["cycle_complete"] is False
    assert report.assurance["iso_50001_certified"] is False
    assert report.assurance["iso_14064_1_verified"] is False
    assert report.production_boundary["regulatory_submission_allowed"] is False


def test_complete_signed_management_cycle_passes_without_certification_claim() -> None:
    request = EnergyCarbonManagementRequest(**complete_management_payload())
    service = EnergyCarbonManagementService(
        auditor_public_keys={AUDITOR_KEY_ID: AUDITOR_PUBLIC_KEY_B64}
    )
    report = service.evaluate(request)

    assert report.status == "evidence_package_passed"
    assert all(gate["passed"] for gate in report.gates)
    assert report.pdca["cycle_complete"] is True
    assert report.performance["significant_energy_use_coverage_pct"] == 85.0
    assert report.performance["monitoring_coverage_pct"] == 100.0
    assert report.performance["objectives_on_target"] == 1
    assert report.audit["open_finding_count"] == 0
    assert report.assurance["independent_assurance_evidence_accepted"] is True
    assert report.assurance["software_is_certification_body"] is False
    assert report.assurance["iso_50001_certified"] is False
    assert report.assurance["iso_14064_1_verified"] is False
    assert report.production_boundary["regulatory_submission_allowed"] is False


def test_open_corrective_action_fails_closed() -> None:
    payload = deepcopy(complete_management_payload())
    payload["corrective_actions"][0]["status"] = "open"
    payload["corrective_actions"][0]["closed_at"] = None
    payload["corrective_actions"][0]["effectiveness_verified"] = False
    request = EnergyCarbonManagementRequest(**payload)
    service = EnergyCarbonManagementService(
        auditor_public_keys={AUDITOR_KEY_ID: AUDITOR_PUBLIC_KEY_B64}
    )
    report = service.evaluate(request)

    assert report.status == "blocked"
    assert "corrective_actions" in report.assurance["blocker_codes"]
    assert report.pdca["cycle_complete"] is False
    assert report.production_boundary["site_management_evidence_verified"] is False


def test_tampering_invalidates_independent_assurance_only() -> None:
    payload = complete_management_payload()
    payload["context"]["operational_boundary"] += " plus tenant reporting"
    request = EnergyCarbonManagementRequest(**payload)
    service = EnergyCarbonManagementService(
        auditor_public_keys={AUDITOR_KEY_ID: AUDITOR_PUBLIC_KEY_B64}
    )
    report = service.evaluate(request)

    assert report.status == "management_cycle_ready_pending_independent_assurance"
    assert report.pdca["cycle_complete"] is True
    assert report.assurance["independent_assurance_evidence_accepted"] is False
    assurance_gate = next(
        item for item in report.gates if item["gate_id"] == "independent_assurance"
    )
    assert assurance_gate["evidence"]["signature_valid"] is False


def test_management_evaluate_api_never_promotes_unconfigured_signature() -> None:
    response = TestClient(app).post(
        "/api/dashboard/energy-carbon-management/evaluate",
        json=complete_management_payload(),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "management_cycle_ready_pending_independent_assurance"
    assert payload["assurance"]["iso_50001_certified"] is False
    assert payload["assurance"]["iso_14064_1_verified"] is False
    assert len(payload["input_evidence_sha256"]) == 64
    assert len(payload["evidence_sha256"]) == 64


def test_dashboard_api_exposes_claim_safe_default_management_state() -> None:
    response = TestClient(app).get("/api/dashboard/energy-carbon-management")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "blocked"
    assert payload["pdca"]["plan_passed"] == 0
    assert payload["pdca"]["plan_total"] == 6
    assert payload["assurance"]["management_cycle_evidence_ready"] is False
