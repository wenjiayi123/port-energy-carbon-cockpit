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
from app.schemas.electrical_network import (
    SOURCE_DOMAINS,
    ElectricalNetworkAssessmentRequest,
)
from app.services.electrical_network import (
    ElectricalNetworkAssessmentService,
    canonical_sha256,
    source_domain_payload,
)


HASH_A = "a" * 64
SOURCE_PRIVATE_KEYS = {
    domain: Ed25519PrivateKey.generate() for domain in sorted(SOURCE_DOMAINS)
}
SOURCE_KEY_IDS = {
    domain: f"test-electrical-{domain}-key" for domain in sorted(SOURCE_DOMAINS)
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


def unsigned_payload() -> dict:
    evaluated_at = "2026-08-01T00:00:00Z"
    return {
        "schema_version": "port-electrical-network-input.v1",
        "assessment_id": "terminal-a-electrical-2026-08-01",
        "site_id": "TERMINAL-A",
        "evaluated_at": evaluated_at,
        "interval_minutes": 60,
        "requested_by": "electrical-duty-engineer",
        "policy": {
            "policy_id": "terminal-a-electrical-policy-v1",
            "minimum_voltage_pu": 0.94,
            "maximum_voltage_pu": 1.06,
            "maximum_branch_loading_pct": 90.0,
            "minimum_power_factor": 0.95,
            "maximum_voltage_thd_pct": 5.0,
            "maximum_transformer_hot_spot_c": 120.0,
            "maximum_aging_acceleration_factor": 4.0,
            "minimum_n_minus_one_critical_load_coverage_pct": 100.0,
            "minimum_island_critical_load_coverage_pct": 100.0,
            "maximum_charger_utilization_pct": 85.0,
            "maximum_expected_charging_wait_minutes": 15.0,
            "maximum_source_age_seconds": 300,
            "maximum_source_alignment_seconds": 60,
            "approved_by": "chief-electrical-engineer",
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
        "buses": [
            {
                "bus_id": "GRID-11KV",
                "nominal_voltage_kv": 11.0,
                "active_load_kw": 0.0,
                "reactive_load_kvar": 0.0,
                "critical_active_load_kw": 0.0,
                "priority": 1,
                "energized_required": False,
            },
            {
                "bus_id": "MAIN-11KV",
                "nominal_voltage_kv": 11.0,
                "active_load_kw": 200.0,
                "reactive_load_kvar": 40.0,
                "critical_active_load_kw": 100.0,
                "priority": 10,
                "energized_required": True,
            },
            {
                "bus_id": "LOAD-400V",
                "nominal_voltage_kv": 0.4,
                "active_load_kw": 300.0,
                "reactive_load_kvar": 60.0,
                "critical_active_load_kw": 200.0,
                "priority": 9,
                "energized_required": True,
            },
        ],
        "branches": [
            {
                "branch_id": "PCC-INCOMER",
                "branch_type": "grid_intertie",
                "from_bus_id": "GRID-11KV",
                "to_bus_id": "MAIN-11KV",
                "resistance_pu": 0.002,
                "reactance_pu": 0.003,
                "rating_kva": 1000.0,
                "switch_id": "SW-PCC",
                "normally_open": False,
                "n_minus_one_contingency": True,
            },
            {
                "branch_id": "TX-01",
                "branch_type": "transformer",
                "from_bus_id": "MAIN-11KV",
                "to_bus_id": "LOAD-400V",
                "resistance_pu": 0.005,
                "reactance_pu": 0.008,
                "rating_kva": 800.0,
                "switch_id": "SW-TX",
                "normally_open": False,
                "n_minus_one_contingency": True,
            },
            {
                "branch_id": "BACKUP-FEEDER",
                "branch_type": "line",
                "from_bus_id": "GRID-11KV",
                "to_bus_id": "LOAD-400V",
                "resistance_pu": 0.004,
                "reactance_pu": 0.006,
                "rating_kva": 800.0,
                "switch_id": "SW-TIE",
                "normally_open": True,
                "n_minus_one_contingency": False,
            },
        ],
        "switches": [
            {
                "switch_id": "SW-PCC",
                "closed": True,
                "protection_healthy": True,
                "interlock_permissive": True,
                "remote_state": "closed",
            },
            {
                "switch_id": "SW-TX",
                "closed": True,
                "protection_healthy": True,
                "interlock_permissive": True,
                "remote_state": "closed",
            },
            {
                "switch_id": "SW-TIE",
                "closed": False,
                "protection_healthy": True,
                "interlock_permissive": True,
                "remote_state": "open",
            },
        ],
        "sources": [
            {
                "source_id": "UTILITY-GRID",
                "bus_id": "GRID-11KV",
                "source_type": "grid",
                "available": True,
                "active_power_kw": 0.0,
                "reactive_power_kvar": 0.0,
                "maximum_active_power_kw": 2000.0,
                "maximum_reactive_power_kvar": 1000.0,
                "grid_forming": True,
                "black_start_capable": False,
            },
            {
                "source_id": "BESS-01",
                "bus_id": "MAIN-11KV",
                "source_type": "storage",
                "available": True,
                "active_power_kw": 0.0,
                "reactive_power_kvar": 0.0,
                "maximum_active_power_kw": 800.0,
                "maximum_reactive_power_kvar": 300.0,
                "grid_forming": True,
                "black_start_capable": True,
            },
        ],
        "power_quality_measurements": [
            {
                "meter_id": "PQ-MAIN",
                "bus_id": "MAIN-11KV",
                "measured_voltage_pu": 0.998,
                "measured_active_power_kw": 500.0,
                "measured_reactive_power_kvar": 100.0,
                "voltage_harmonics_pct": {"3": 0.8, "5": 1.2, "7": 0.6},
                "measured_voltage_thd_pct": 1.6,
            },
            {
                "meter_id": "PQ-LOAD",
                "bus_id": "LOAD-400V",
                "measured_voltage_pu": 0.995,
                "measured_active_power_kw": 300.0,
                "measured_reactive_power_kvar": 60.0,
                "voltage_harmonics_pct": {"3": 0.5, "5": 1.0, "7": 0.5},
                "measured_voltage_thd_pct": 1.3,
            },
        ],
        "transformer_thermal_measurements": [
            {
                "transformer_id": "TX-01",
                "branch_id": "TX-01",
                "ambient_temperature_c": 25.0,
                "initial_top_oil_rise_c": 30.0,
                "initial_winding_hot_spot_rise_c": 20.0,
                "rated_top_oil_rise_c": 55.0,
                "rated_winding_hot_spot_rise_c": 30.0,
                "load_loss_ratio": 5.0,
                "top_oil_time_constant_minutes": 180.0,
                "winding_time_constant_minutes": 10.0,
                "oil_exponent": 0.8,
                "winding_exponent": 0.8,
            }
        ],
        "charging_pools": [
            {
                "pool_id": "AGV-CHARGERS",
                "bus_id": "LOAD-400V",
                "charger_count": 4,
                "available_charger_count": 4,
                "charger_power_kw": 60.0,
                "arrival_rate_per_hour": 4.0,
                "mean_service_minutes": 30.0,
                "observed_queue_vehicles": 1,
            }
        ],
        "storage_warranties": [
            {
                "storage_id": "BESS-01",
                "source_id": "BESS-01",
                "bus_id": "MAIN-11KV",
                "usable_capacity_kwh": 2000.0,
                "state_of_charge_pct": 80.0,
                "minimum_state_of_charge_pct": 20.0,
                "maximum_state_of_charge_pct": 95.0,
                "state_of_health_pct": 96.0,
                "minimum_state_of_health_pct": 80.0,
                "cell_temperature_c": 30.0,
                "maximum_cell_temperature_c": 45.0,
                "requested_active_power_kw": 100.0,
                "requested_reactive_power_kvar": 20.0,
                "maximum_charge_power_kw": 800.0,
                "maximum_discharge_power_kw": 800.0,
                "maximum_reactive_power_kvar": 300.0,
                "charge_efficiency": 0.95,
                "discharge_efficiency": 0.95,
                "daily_throughput_kwh": 500.0,
                "maximum_daily_throughput_kwh": 3000.0,
                "cumulative_throughput_kwh": 100000.0,
                "warranty_throughput_limit_kwh": 3000000.0,
                "equivalent_full_cycles": 200.0,
                "warranty_cycle_limit": 6000.0,
                "minimum_island_reserve_kwh": 100.0,
            }
        ],
        "n_minus_one_scenarios": [
            {
                "scenario_id": "N1-TX-01",
                "contingency_branch_id": "TX-01",
                "approved_tie_switch_ids": ["SW-TIE"],
                "minimum_critical_load_coverage_pct": 100.0,
            }
        ],
        "island_scenarios": [
            {
                "scenario_id": "ISLAND-PCC-60MIN",
                "pcc_switch_ids": ["SW-PCC"],
                "duration_minutes": 60,
                "minimum_critical_load_coverage_pct": 100.0,
            }
        ],
    }


def signed_request(payload: dict | None = None) -> ElectricalNetworkAssessmentRequest:
    payload = deepcopy(payload or unsigned_payload())
    placeholder = ElectricalNetworkAssessmentRequest(**payload)
    attestations = {item["domain"]: item for item in payload["source_attestations"]}
    for domain in sorted(SOURCE_DOMAINS):
        digest = canonical_sha256(source_domain_payload(placeholder, domain))
        attestations[domain]["signed_payload_sha256"] = digest
        attestations[domain]["signature"] = base64.b64encode(
            SOURCE_PRIVATE_KEYS[domain].sign(bytes.fromhex(digest))
        ).decode("ascii")
    return ElectricalNetworkAssessmentRequest(**payload)


def service() -> ElectricalNetworkAssessmentService:
    return ElectricalNetworkAssessmentService(source_public_keys=SOURCE_PUBLIC_KEYS)


def test_default_report_is_explicitly_blocked_without_site_evidence() -> None:
    report = service().build_default()

    assert report.status == "blocked"
    assert report.source_readiness["domain_count"] == 0
    assert report.source_readiness["required_domain_count"] == 6
    assert len(report.gates) == 14
    assert sum(item["passed"] for item in report.gates) == 0
    assert report.network_summary["minimum_voltage_pu"] is None
    assert report.production_boundary["switching_command_allowed"] is False
    assert report.production_boundary["production_authority"] is False


def test_complete_signed_radial_site_assessment_passes_all_gates() -> None:
    report = service().evaluate(signed_request())

    assert report.status == "assessment_ready"
    assert sum(item["passed"] for item in report.gates) == 14
    assert report.source_readiness["domain_count"] == 6
    assert report.network_summary["bus_count"] == 3
    assert report.network_summary["minimum_voltage_pu"] >= 0.94
    assert report.n_minus_one_results[0]["selected_restoration"][
        "closed_tie_switch_ids"
    ] == ["SW-TIE"]
    assert report.island_results[0]["passed"] is True
    assert report.charging_queue_results[0]["expected_wait_minutes"] < 15
    assert report.storage_warranty_results[0]["within_warranty"] is True
    assert report.production_boundary == {
        "simulation_mode": True,
        "live_site_data_verified": True,
        "advisory_only": True,
        "switching_command_allowed": False,
        "protection_setting_change_allowed": False,
        "islanding_command_allowed": False,
        "equipment_dispatch_allowed": False,
        "production_authority": False,
    }


def test_tampered_topology_is_blocked_by_source_signature() -> None:
    request = signed_request()
    payload = request.model_dump(mode="json")
    payload["buses"][1]["active_load_kw"] += 10
    report = service().evaluate(ElectricalNetworkAssessmentRequest(**payload))

    gates = {item["gate_id"]: item for item in report.gates}
    assert report.status == "blocked"
    assert gates["source_signatures"]["passed"] is False
    assert gates["source_signatures"]["evidence"]["single_line_topology"] is False


def test_voltage_harmonics_and_transformer_thermal_fail_closed() -> None:
    payload = unsigned_payload()
    payload["branches"][0]["resistance_pu"] = 0.12
    payload["power_quality_measurements"][0]["voltage_harmonics_pct"] = {"5": 8.0}
    payload["transformer_thermal_measurements"][0].update(
        {
            "ambient_temperature_c": 60.0,
            "initial_top_oil_rise_c": 100.0,
            "initial_winding_hot_spot_rise_c": 100.0,
        }
    )
    report = service().evaluate(signed_request(payload))
    gates = {item["gate_id"]: item["passed"] for item in report.gates}

    assert report.status == "infeasible"
    assert gates["bus_voltage_limits"] is False
    assert gates["harmonic_distortion"] is False
    assert gates["transformer_thermal_aging"] is False


def test_n_minus_one_without_restoration_and_island_without_grid_former_fail() -> None:
    payload = unsigned_payload()
    payload["n_minus_one_scenarios"][0]["approved_tie_switch_ids"] = []
    payload["sources"][1]["grid_forming"] = False
    report = service().evaluate(signed_request(payload))
    gates = {item["gate_id"]: item["passed"] for item in report.gates}

    assert report.status == "infeasible"
    assert gates["n_minus_one_resilience"] is False
    assert gates["island_operation"] is False


def test_unstable_queue_and_warranty_overrun_are_infeasible() -> None:
    payload = unsigned_payload()
    payload["charging_pools"][0]["arrival_rate_per_hour"] = 10.0
    payload["storage_warranties"][0]["daily_throughput_kwh"] = 2999.0
    report = service().evaluate(signed_request(payload))
    gates = {item["gate_id"]: item["passed"] for item in report.gates}

    assert report.status == "infeasible"
    assert gates["charging_queue_service"] is False
    assert gates["storage_warranty"] is False
    assert report.charging_queue_results[0]["stable"] is False
    assert report.storage_warranty_results[0]["checks"]["daily_throughput"] is False


def test_closed_tie_cycle_and_unhealthy_interlock_are_rejected() -> None:
    payload = unsigned_payload()
    payload["switches"][2].update({"closed": True, "remote_state": "closed"})
    payload["switches"][0]["interlock_permissive"] = False
    report = service().evaluate(signed_request(payload))
    gate = next(
        item for item in report.gates if item["gate_id"] == "switch_interlock_and_radiality"
    )

    assert report.status == "infeasible"
    assert gate["passed"] is False
    assert gate["evidence"]["radial"] is False
    assert gate["evidence"]["closed_switches_healthy"] is False
    assert gate["evidence"]["cycle_branch_ids"]


def test_feeder_overload_and_low_power_factor_are_rejected() -> None:
    payload = unsigned_payload()
    payload["branches"][1]["rating_kva"] = 300.0
    payload["buses"][1]["reactive_load_kvar"] = 500.0
    payload["buses"][2]["reactive_load_kvar"] = 500.0
    report = service().evaluate(signed_request(payload))
    gates = {item["gate_id"]: item["passed"] for item in report.gates}

    assert report.status == "infeasible"
    assert gates["feeder_transformer_loading"] is False
    assert gates["reactive_power_and_power_factor"] is False
    assert report.network_summary["maximum_branch_loading_pct"] > 90


def test_duplicate_asset_ids_fail_topology_reference_integrity() -> None:
    payload = unsigned_payload()
    duplicate = deepcopy(payload["switches"][2])
    duplicate["closed"] = True
    duplicate["remote_state"] = "closed"
    payload["switches"].append(duplicate)
    report = service().evaluate(signed_request(payload))
    gate = next(
        item for item in report.gates if item["gate_id"] == "topology_reference_integrity"
    )

    assert report.status == "infeasible"
    assert gate["passed"] is False
    assert gate["evidence"]["duplicate_ids"]["switch_ids"] == ["SW-TIE"]


def test_source_owner_signing_tool_binds_exact_domain_payload(tmp_path: Path) -> None:
    domain = "power_quality_meters"
    input_path = tmp_path / "assessment.json"
    key_path = tmp_path / "source-key.pem"
    output_path = tmp_path / "signed.json"
    input_path.write_text(json.dumps(unsigned_payload()), encoding="utf-8")
    key_path.write_bytes(
        SOURCE_PRIVATE_KEYS[domain].private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )

    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "sign_electrical_source.py"),
            "--input",
            str(input_path),
            "--domain",
            domain,
            "--private-key",
            str(key_path),
            "--key-id",
            SOURCE_KEY_IDS[domain],
            "--output",
            str(output_path),
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    request = ElectricalNetworkAssessmentRequest(
        **json.loads(output_path.read_text(encoding="utf-8"))
    )
    attestation = next(item for item in request.source_attestations if item.domain == domain)

    assert json.loads(completed.stdout)["domain"] == domain
    assert attestation.signed_payload_sha256 == canonical_sha256(
        source_domain_payload(request, domain)
    )
    assert ElectricalNetworkAssessmentService(
        source_public_keys={SOURCE_KEY_IDS[domain]: SOURCE_PUBLIC_KEYS[SOURCE_KEY_IDS[domain]]}
    )._source_signature_valid(request, attestation)


def test_dashboard_electrical_api_is_blocked_when_trust_keys_are_unconfigured() -> None:
    client = TestClient(app)
    default = client.get("/api/dashboard/electrical-network")
    evaluated = client.post(
        "/api/dashboard/electrical-network/evaluate",
        json=signed_request().model_dump(mode="json"),
    )

    assert default.status_code == 200
    assert default.json()["status"] == "blocked"
    assert evaluated.status_code == 200
    assert evaluated.json()["status"] == "blocked"
    assert evaluated.json()["assurance"]["source_authenticity_accepted"] is False
    snapshot = client.get("/api/dashboard/snapshot").json()
    assert snapshot["electrical_network"]["source_readiness"]["domain_count"] == 0
    assert len(snapshot["electrical_network"]["gates"]) == 14
