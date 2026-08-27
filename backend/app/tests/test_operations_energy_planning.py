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
from app.schemas.operations_energy_planning import (
    SOURCE_DOMAINS,
    OperationsEnergyPlanningRequest,
)
from app.services.operations_energy_planning import (
    OperationsEnergyPlanningService,
    canonical_sha256,
    source_domain_payload,
)


HASH_A = "a" * 64
SOURCE_PRIVATE_KEYS = {
    domain: Ed25519PrivateKey.generate() for domain in sorted(SOURCE_DOMAINS)
}
SOURCE_KEY_IDS = {
    domain: f"test-{domain}-key" for domain in sorted(SOURCE_DOMAINS)
}
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


def unsigned_planning_payload() -> dict:
    start = "2026-08-01T00:00:00Z"
    payload = {
        "schema_version": "operations-energy-plan-input.v1",
        "plan_id": "terminal-a-joint-plan-2026-08-01",
        "site_id": "TERMINAL-A",
        "requested_at": start,
        "requested_by": "integrated-planning-manager",
        "horizon": {
            "start_at": start,
            "interval_minutes": 60,
            "slot_count": 8,
        },
        "policy": {
            "policy_id": "site-joint-planning-policy-v1",
            "minimum_service_coverage_pct": 100.0,
            "minimum_truck_appointment_coverage_pct": 100.0,
            "grid_reserve_margin_pct": 10.0,
            "maximum_source_age_seconds": 300,
            "maximum_source_alignment_seconds": 60,
            "berth_beam_width": 64,
            "cost_weight": 1.0,
            "carbon_weight": 0.3,
            "delay_weight": 1.0,
            "battery_degradation_cny_per_kwh": 0.05,
            "approved_by": "planning-director",
            "approval_record_sha256": HASH_A,
        },
        "source_attestations": [
            {
                "domain": domain,
                "source_system": f"site-{domain}",
                "source_record_ids": [f"{domain}-record-001"],
                "observed_at": "2026-07-31T23:59:30Z",
                "live_data_verified": True,
                "key_id": SOURCE_KEY_IDS[domain],
                "signed_payload_sha256": HASH_A,
                "signature": base64.b64encode(b"0" * 64).decode("ascii"),
            }
            for domain in sorted(SOURCE_DOMAINS)
        ],
        "vessel_calls": [
            {
                "vessel_call_id": "CALL-A",
                "imo_number": "IMO1234567",
                "vessel_length_m": 250.0,
                "eta": "2026-08-01T00:00:00Z",
                "required_departure_at": "2026-08-01T04:00:00Z",
                "import_teu": 60.0,
                "export_teu": 40.0,
                "total_moves_teu": 100.0,
                "minimum_cranes": 2,
                "maximum_cranes": 2,
                "candidate_berth_ids": ["B1"],
                "candidate_yard_block_ids": ["Y1"],
                "shore_power_compatible": True,
                "hotel_load_kw": 1000.0,
                "minimum_shore_energy_kwh": 1800.0,
                "priority": 3,
            },
            {
                "vessel_call_id": "CALL-B",
                "imo_number": "IMO7654321",
                "vessel_length_m": 210.0,
                "eta": "2026-08-01T02:00:00Z",
                "required_departure_at": "2026-08-01T07:00:00Z",
                "import_teu": 30.0,
                "export_teu": 30.0,
                "total_moves_teu": 60.0,
                "minimum_cranes": 1,
                "maximum_cranes": 1,
                "candidate_berth_ids": ["B2"],
                "candidate_yard_block_ids": ["Y2"],
                "shore_power_compatible": True,
                "hotel_load_kw": 800.0,
                "minimum_shore_energy_kwh": 1400.0,
                "priority": 2,
            },
        ],
        "berths": [
            {
                "berth_id": "B1",
                "available_from": start,
                "available_until": "2026-08-01T08:00:00Z",
                "maximum_vessel_length_m": 300.0,
                "maximum_simultaneous_cranes": 2,
                "shore_power_available": True,
                "shore_power_capacity_kw": 1200.0,
            },
            {
                "berth_id": "B2",
                "available_from": start,
                "available_until": "2026-08-01T08:00:00Z",
                "maximum_vessel_length_m": 260.0,
                "maximum_simultaneous_cranes": 1,
                "shore_power_available": True,
                "shore_power_capacity_kw": 900.0,
            },
        ],
        "cranes": [
            {
                "crane_id": "QC-01",
                "compatible_berth_ids": ["B1"],
                "available_from": start,
                "available_until": "2026-08-01T08:00:00Z",
                "moves_per_hour": 25.0,
                "active_power_kw": 200.0,
            },
            {
                "crane_id": "QC-02",
                "compatible_berth_ids": ["B1"],
                "available_from": start,
                "available_until": "2026-08-01T08:00:00Z",
                "moves_per_hour": 25.0,
                "active_power_kw": 200.0,
            },
            {
                "crane_id": "QC-03",
                "compatible_berth_ids": ["B2"],
                "available_from": start,
                "available_until": "2026-08-01T08:00:00Z",
                "moves_per_hour": 30.0,
                "active_power_kw": 180.0,
            },
        ],
        "yard_blocks": [
            {
                "yard_block_id": "Y1",
                "capacity_teu": 1000.0,
                "initial_occupancy_teu": 500.0,
                "reefer_plug_capacity": 50,
                "handling_energy_kwh_per_teu": 1.5,
            },
            {
                "yard_block_id": "Y2",
                "capacity_teu": 800.0,
                "initial_occupancy_teu": 400.0,
                "reefer_plug_capacity": 40,
                "handling_energy_kwh_per_teu": 1.2,
            },
        ],
        "truck_gates": [
            {
                "gate_id": "GATE-1",
                "maximum_teu_per_slot": 100.0,
                "service_energy_kwh_per_teu": 0.3,
            }
        ],
        "truck_appointments": [
            {
                "appointment_id": "APT-A-EXPORT",
                "vessel_call_id": "CALL-A",
                "direction": "export_dropoff",
                "window_start": "2026-08-01T00:00:00Z",
                "window_end": "2026-08-01T02:00:00Z",
                "teu": 40.0,
                "yard_block_id": "Y1",
                "candidate_gate_ids": ["GATE-1"],
            },
            {
                "appointment_id": "APT-A-IMPORT",
                "vessel_call_id": "CALL-A",
                "direction": "import_pickup",
                "window_start": "2026-08-01T02:00:00Z",
                "window_end": "2026-08-01T05:00:00Z",
                "teu": 60.0,
                "yard_block_id": "Y1",
                "candidate_gate_ids": ["GATE-1"],
            },
            {
                "appointment_id": "APT-B-EXPORT",
                "vessel_call_id": "CALL-B",
                "direction": "export_dropoff",
                "window_start": "2026-08-01T01:00:00Z",
                "window_end": "2026-08-01T03:00:00Z",
                "teu": 30.0,
                "yard_block_id": "Y2",
                "candidate_gate_ids": ["GATE-1"],
            },
            {
                "appointment_id": "APT-B-IMPORT",
                "vessel_call_id": "CALL-B",
                "direction": "import_pickup",
                "window_start": "2026-08-01T04:00:00Z",
                "window_end": "2026-08-01T07:00:00Z",
                "teu": 30.0,
                "yard_block_id": "Y2",
                "candidate_gate_ids": ["GATE-1"],
            },
        ],
        "reefer_batches": [
            {
                "batch_id": "REEFER-A",
                "vessel_call_id": "CALL-A",
                "yard_block_id": "Y1",
                "connected_from": "2026-08-01T00:00:00Z",
                "connected_until": "2026-08-01T04:00:00Z",
                "container_count": 10,
                "power_kw_per_container": 2.5,
                "uninterrupted_service_required": True,
            },
            {
                "batch_id": "REEFER-B",
                "vessel_call_id": "CALL-B",
                "yard_block_id": "Y2",
                "connected_from": "2026-08-01T02:00:00Z",
                "connected_until": "2026-08-01T06:00:00Z",
                "container_count": 8,
                "power_kw_per_container": 2.5,
                "uninterrupted_service_required": True,
            },
        ],
        "energy_slots": [
            {
                "slot_index": slot,
                "start_at": f"2026-08-01T{slot:02d}:00:00Z",
                "base_terminal_load_kw": 2500.0,
                "renewable_available_kw": 500.0 + slot * 100.0,
                "grid_import_limit_kw": 6000.0,
                "electricity_price_cny_per_kwh": 0.8 + slot * 0.1,
                "grid_carbon_kg_per_kwh": 0.45 - slot * 0.01,
            }
            for slot in range(8)
        ],
        "storage": {
            "storage_id": "BESS-01",
            "usable_capacity_kwh": 2000.0,
            "initial_soc_pct": 50.0,
            "minimum_soc_pct": 20.0,
            "maximum_soc_pct": 90.0,
            "terminal_minimum_soc_pct": 40.0,
            "maximum_charge_kw": 500.0,
            "maximum_discharge_kw": 500.0,
            "charge_efficiency": 0.95,
            "discharge_efficiency": 0.95,
        },
    }
    return payload


def sign_all_sources(payload: dict) -> dict:
    payload = deepcopy(payload)
    provisional = OperationsEnergyPlanningRequest(**payload)
    by_domain = {
        item["domain"]: item for item in payload["source_attestations"]
    }
    for domain in sorted(SOURCE_DOMAINS):
        digest = canonical_sha256(source_domain_payload(provisional, domain))
        by_domain[domain]["signed_payload_sha256"] = digest
        by_domain[domain]["signature"] = base64.b64encode(
            SOURCE_PRIVATE_KEYS[domain].sign(bytes.fromhex(digest))
        ).decode("ascii")
    OperationsEnergyPlanningRequest(**payload)
    return payload


def test_default_joint_planning_state_is_explicitly_blocked() -> None:
    service = OperationsEnergyPlanningService(source_public_keys={})
    report = service.build_default()

    assert report.status == "blocked"
    assert len(report.gates) == 12
    assert all(not item["passed"] for item in report.gates)
    assert report.source_readiness["domain_count"] == 0
    assert report.assurance["solver_executed"] is False
    assert report.production_boundary["equipment_dispatch_allowed"] is False


def test_complete_signed_site_inputs_produce_feasible_joint_advisory_plan() -> None:
    request = OperationsEnergyPlanningRequest(
        **sign_all_sources(unsigned_planning_payload())
    )
    service = OperationsEnergyPlanningService(source_public_keys=SOURCE_PUBLIC_KEYS)
    report = service.evaluate(request)

    assert report.status == "advisory_plan_ready"
    assert all(item["passed"] for item in report.gates)
    assert len(report.vessel_assignments) == 2
    assert len(report.truck_schedule) == 4
    assert len(report.slot_plan) == 8
    assert report.kpis["service_coverage_pct"] == 100.0
    assert report.kpis["truck_appointment_coverage_pct"] == 100.0
    assert report.kpis["planned_moves_teu"] == 160.0
    assert report.kpis["shore_energy_kwh"] == 3600.0
    assert report.kpis["terminal_storage_soc_pct"] >= 40.0
    assert report.assurance["source_authenticity_accepted"] is True
    assert report.assurance["hard_constraints_passed"] is True
    assert report.production_boundary["advisory_only"] is True
    assert report.production_boundary["tos_writeback_allowed"] is False
    assert report.production_boundary["equipment_dispatch_allowed"] is False
    assert all(abs(item["energy_balance_error_kw"]) <= 1e-6 for item in report.slot_plan)


def test_source_payload_tampering_blocks_plan_release() -> None:
    payload = sign_all_sources(unsigned_planning_payload())
    payload["truck_appointments"][0]["teu"] = 39.0
    request = OperationsEnergyPlanningRequest(**payload)
    service = OperationsEnergyPlanningService(source_public_keys=SOURCE_PUBLIC_KEYS)
    report = service.evaluate(request)

    assert report.status == "blocked"
    signature_gate = next(
        item for item in report.gates if item["gate_id"] == "source_signatures"
    )
    assert signature_gate["passed"] is False
    assert signature_gate["evidence"]["truck_appointments"] is False
    assert report.assurance["advisory_plan_release_allowed"] is False


def test_signed_yard_capacity_violation_returns_infeasible_not_ready() -> None:
    payload = unsigned_planning_payload()
    payload["yard_blocks"][0]["capacity_teu"] = 520.0
    payload = sign_all_sources(payload)
    request = OperationsEnergyPlanningRequest(**payload)
    service = OperationsEnergyPlanningService(source_public_keys=SOURCE_PUBLIC_KEYS)
    report = service.evaluate(request)

    assert report.status == "infeasible"
    assert report.assurance["source_authenticity_accepted"] is True
    assert report.assurance["hard_constraints_passed"] is False
    assert report.constraint_summary["yard_capacity_violations"]
    assert "yard_inventory_capacity" in report.assurance["blocker_codes"]


def test_signed_grid_shortfall_returns_infeasible_with_slot_receipt() -> None:
    payload = unsigned_planning_payload()
    for slot in payload["energy_slots"]:
        slot["grid_import_limit_kw"] = 1200.0
    payload = sign_all_sources(payload)
    request = OperationsEnergyPlanningRequest(**payload)
    service = OperationsEnergyPlanningService(source_public_keys=SOURCE_PUBLIC_KEYS)
    report = service.evaluate(request)

    assert report.status == "infeasible"
    assert report.constraint_summary["grid_limit_violations"]
    assert "energy_balance_and_grid" in report.assurance["blocker_codes"]
    assert report.production_boundary["equipment_dispatch_allowed"] is False


def test_api_runs_solver_but_rejects_unconfigured_source_keys() -> None:
    response = TestClient(app).post(
        "/api/dashboard/operations-energy-plan/evaluate",
        json=sign_all_sources(unsigned_planning_payload()),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "blocked"
    assert payload["assurance"]["solver_executed"] is True
    assert payload["assurance"]["source_authenticity_accepted"] is False
    assert payload["assurance"]["hard_constraints_passed"] is True
    assert payload["production_boundary"]["equipment_dispatch_allowed"] is False
    assert len(payload["input_evidence_sha256"]) == 64
    assert len(payload["evidence_sha256"]) == 64


def test_dashboard_exposes_aggregate_data_blocked_state() -> None:
    response = TestClient(app).get("/api/dashboard/operations-energy-plan")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "blocked"
    assert payload["source_readiness"]["domain_count"] == 0
    assert len(payload["gates"]) == 12


def test_source_owner_signing_helper_updates_exactly_one_domain(tmp_path: Path) -> None:
    payload = unsigned_planning_payload()
    input_path = tmp_path / "input.json"
    output_path = tmp_path / "signed.json"
    private_key_path = tmp_path / "source.pem"
    private_key = Ed25519PrivateKey.generate()
    input_path.write_text(json.dumps(payload), encoding="utf-8")
    private_key_path.write_bytes(
        private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )

    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "sign_operations_energy_source.py"),
            "--input",
            str(input_path),
            "--domain",
            "truck_appointments",
            "--private-key",
            str(private_key_path),
            "--key-id",
            "truck-owner-key-2026q3",
            "--output",
            str(output_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    signed = json.loads(output_path.read_text(encoding="utf-8"))
    target = next(
        item
        for item in signed["source_attestations"]
        if item["domain"] == "truck_appointments"
    )
    untouched = next(
        item
        for item in signed["source_attestations"]
        if item["domain"] == "yard_inventory"
    )
    request = OperationsEnergyPlanningRequest(**signed)
    digest = canonical_sha256(source_domain_payload(request, "truck_appointments"))
    private_key.public_key().verify(
        base64.b64decode(target["signature"]),
        bytes.fromhex(digest),
    )
    assert target["key_id"] == "truck-owner-key-2026q3"
    assert target["signed_payload_sha256"] == digest
    assert untouched["signed_payload_sha256"] == HASH_A
    assert json.loads(result.stdout)["domain"] == "truck_appointments"
