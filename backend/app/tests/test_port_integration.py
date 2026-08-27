from datetime import datetime, timedelta, timezone
import hashlib
import json

from app.integration.gateway import (
    DATA_ADAPTER_CONTRACTS,
    REQUIRED_SHADOW_FIELD_COUNT,
    PortIntegrationGateway,
    SnapshotEnvelope,
    canonical_json,
)


NOW = datetime(2026, 8, 8, 8, 0, tzinfo=timezone.utc)
SECRET = "adapter-specific-secret-with-at-least-32-characters"

SHADOW_PAYLOADS = {
    "terminal_operating_system": {
        "loaded_import_teu": 920.0,
        "loaded_export_teu": 870.0,
        "total_teu": 2040.0,
    },
    "energy_management_system": {
        "grid_carbon_kg_per_kwh": 0.31,
        "electricity_price_per_kwh": 0.62,
        "fuel_price_per_liter": 8.1,
        "grid_available_ratio": 0.98,
        "renewable_power_available_kw": 1250.0,
    },
    "berth_and_vessel_feed": {
        "vessels_at_anchor": 4.0,
        "vessels_at_berth": 7.0,
        "vessels_departed": 9.0,
        "average_days_at_berth": 1.4,
        "average_days_in_port": 2.2,
        "berth_available_ratio": 0.86,
    },
    "equipment_availability_feed": {
        "crane_available_ratio": 0.91,
        "yard_available_ratio": 0.88,
    },
    "weather_and_navigation_feed": {
        "wind_speed_m_s": 6.2,
        "wave_height_m": 0.8,
        "visibility_km": 12.0,
        "precipitation_mm": 0.0,
    },
    "shore_power_compatibility_registry": {
        "shore_power_compatible_ratio": 0.72,
    },
}

SHADOW_UNITS = {
    "loaded_import_teu": "TEU",
    "loaded_export_teu": "TEU",
    "total_teu": "TEU",
    "grid_carbon_kg_per_kwh": "kgCO2e/kWh",
    "electricity_price_per_kwh": "currency/kWh",
    "fuel_price_per_liter": "currency/liter",
    "grid_available_ratio": "ratio",
    "renewable_power_available_kw": "kW",
    "vessels_at_anchor": "vessel",
    "vessels_at_berth": "vessel",
    "vessels_departed": "vessel",
    "average_days_at_berth": "day",
    "average_days_in_port": "day",
    "berth_available_ratio": "ratio",
    "crane_available_ratio": "ratio",
    "yard_available_ratio": "ratio",
    "wind_speed_m_s": "m/s",
    "wave_height_m": "m",
    "visibility_km": "km",
    "precipitation_mm": "mm",
    "shore_power_compatible_ratio": "ratio",
}


def snapshot(
    *,
    snapshot_id: str = "ems:20260808T080000Z:0001",
    sequence: int = 1,
    observed_at: datetime = NOW,
    payload: dict | None = None,
) -> SnapshotEnvelope:
    values = payload or {
        "grid_carbon_kg_per_kwh": 0.31,
        "electricity_price_per_kwh": 0.62,
        "fuel_price_per_liter": 8.1,
        "grid_available_ratio": 0.98,
        "renewable_power_available_kw": 1250.0,
    }
    envelope = SnapshotEnvelope(
        snapshot_id=snapshot_id,
        port_id="PORT-TEST",
        adapter_id="energy_management_system",
        source_system="terminal-ems-primary",
        source_record_id="EMS-0001",
        sequence=sequence,
        observed_at=observed_at,
        received_at=NOW,
        payload=values,
        units={
            "grid_carbon_kg_per_kwh": "kgCO2e/kWh",
            "electricity_price_per_kwh": "currency/kWh",
            "fuel_price_per_liter": "currency/liter",
            "grid_available_ratio": "ratio",
            "renewable_power_available_kw": "kW",
        },
        payload_sha256=hashlib.sha256(canonical_json(values)).hexdigest(),
    )
    return envelope.signed(SECRET)


def shadow_source_snapshot(
    adapter_id: str,
    *,
    observed_at: datetime = NOW,
    sequence: int = 1,
) -> SnapshotEnvelope:
    values = SHADOW_PAYLOADS[adapter_id]
    units = {field: SHADOW_UNITS[field] for field in values}
    envelope = SnapshotEnvelope(
        snapshot_id=f"{adapter_id}:20260808T080000Z:{sequence:04d}",
        port_id="PORT-TEST",
        adapter_id=adapter_id,
        source_system=f"test-{adapter_id}",
        source_record_id=f"record-{adapter_id}-{sequence}",
        sequence=sequence,
        observed_at=observed_at,
        received_at=NOW,
        payload=values,
        units=units,
        payload_sha256=hashlib.sha256(canonical_json(values)).hexdigest(),
    )
    return envelope.signed(SECRET)


def ready_shadow_settings(monkeypatch) -> None:
    monkeypatch.setattr("app.core.security.verify_audit_chain", lambda: {"ok": True})
    monkeypatch.setattr("app.integration.gateway.settings.api_auth_mode", "api_key")
    monkeypatch.setattr("app.integration.gateway.settings.port_operation_mode", "shadow")


def test_signed_snapshot_is_persisted_without_raw_operational_values(tmp_path) -> None:
    path = tmp_path / "integration-state.json"
    gateway = PortIntegrationGateway(
        signing_keys={"energy_management_system": SECRET},
        state_path=path,
        port_id="PORT-TEST",
        clock=lambda: NOW,
    )

    result = gateway.ingest(snapshot())

    assert result["accepted"] is True
    assert result["signature_valid"] is True
    assert result["payload_sha256"]
    persisted = json.loads(path.read_text(encoding="utf-8"))
    serialized = json.dumps(persisted)
    assert "payload" not in persisted["adapters"]["energy_management_system"]
    assert "0.62" not in serialized


def test_snapshot_replay_is_idempotent_but_sequence_rollback_fails(tmp_path) -> None:
    gateway = PortIntegrationGateway(
        signing_keys={"energy_management_system": SECRET},
        state_path=tmp_path / "state.json",
        port_id="PORT-TEST",
        clock=lambda: NOW,
    )
    envelope = snapshot()
    assert gateway.ingest(envelope)["accepted"] is True
    assert gateway.ingest(envelope)["idempotent_replay"] is True

    rollback = gateway.ingest(snapshot(snapshot_id="ems:rollback:0000", sequence=0))
    assert rollback["accepted"] is False
    assert "sequence_not_increasing" in rollback["errors"]


def test_unsigned_stale_or_incomplete_snapshots_fail_closed(tmp_path) -> None:
    gateway = PortIntegrationGateway(
        signing_keys={"energy_management_system": SECRET},
        state_path=tmp_path / "state.json",
        port_id="PORT-TEST",
        clock=lambda: NOW,
    )
    stale = snapshot(observed_at=NOW - timedelta(minutes=3)).model_copy(update={"signature": ""})
    result = gateway.ingest(stale)
    assert result["accepted"] is False
    assert {"snapshot_stale", "signature_invalid"} <= set(result["errors"])

    incomplete_values = {"grid_available_ratio": 0.5}
    incomplete = snapshot(
        snapshot_id="ems:incomplete:0002",
        sequence=2,
        payload=incomplete_values,
    )
    result = gateway.ingest(incomplete)
    assert result["accepted"] is False
    assert any(error.startswith("missing_fields:") for error in result["errors"])


def test_shadow_readiness_requires_every_fresh_signed_adapter(tmp_path) -> None:
    gateway = PortIntegrationGateway(
        signing_keys={"energy_management_system": SECRET},
        state_path=tmp_path / "state.json",
        port_id="PORT-TEST",
        clock=lambda: NOW,
    )
    gateway.ingest(snapshot())
    status = gateway.status()
    assert status["ready_adapter_count"] == 1
    assert status["read_only_shadow_ready"] is False
    assert "terminal_operating_system" in status["missing_adapters"]


def test_six_sources_form_one_atomic_model_readable_shadow_state(tmp_path, monkeypatch) -> None:
    ready_shadow_settings(monkeypatch)
    gateway = PortIntegrationGateway(
        signing_keys={adapter_id: SECRET for adapter_id in DATA_ADAPTER_CONTRACTS},
        state_path=tmp_path / "state.json",
        port_id="PORT-TEST",
        clock=lambda: NOW,
    )
    for adapter_id in DATA_ADAPTER_CONTRACTS:
        assert gateway.ingest(shadow_source_snapshot(adapter_id))["accepted"] is True

    status = gateway.status()
    assert status["signed_feed_evidence_ready"] is True
    assert status["resident_payload_count"] == len(DATA_ADAPTER_CONTRACTS)
    assert status["dynamic_time_alignment"]["ready"] is True
    assert status["read_only_shadow_ready"] is True

    composite = gateway.shadow_snapshot()
    assert composite["schema_version"] == "port-shadow-state.v1"
    assert composite["status"] == "ready"
    assert composite["quality"]["gate"] == "PASS"
    assert composite["quality"]["available_field_count"] == REQUIRED_SHADOW_FIELD_COUNT
    assert len(composite["observation"]) == REQUIRED_SHADOW_FIELD_COUNT
    assert len(composite["signals"]) == REQUIRED_SHADOW_FIELD_COUNT
    assert composite["observation"]["total_teu"] == 2040.0
    assert composite["signals"]["total_teu"]["source_payload_sha256"]
    assert composite["signals"]["total_teu"]["measurement_verified"] is False
    assert composite["production_boundary"] == {
        "read_only_shadow": True,
        "source_reported_values": True,
        "measurement_calibration_verified": False,
        "live_data_verified": False,
        "dispatch_allowed": False,
        "production_authority": False,
        "production_dispatch_enabled": False,
    }
    assert len(composite["snapshot_sha256"]) == 64


def test_restart_requires_source_resend_before_values_are_released(tmp_path, monkeypatch) -> None:
    ready_shadow_settings(monkeypatch)
    path = tmp_path / "state.json"
    keys = {adapter_id: SECRET for adapter_id in DATA_ADAPTER_CONTRACTS}
    first = PortIntegrationGateway(
        signing_keys=keys,
        state_path=path,
        port_id="PORT-TEST",
        clock=lambda: NOW,
    )
    envelopes = [shadow_source_snapshot(adapter_id) for adapter_id in DATA_ADAPTER_CONTRACTS]
    for envelope in envelopes:
        assert first.ingest(envelope)["accepted"] is True
    assert first.shadow_snapshot()["ready"] is True

    restarted = PortIntegrationGateway(
        signing_keys=keys,
        state_path=path,
        port_id="PORT-TEST",
        clock=lambda: NOW,
    )
    blocked = restarted.shadow_snapshot()
    assert blocked["ready"] is False
    assert blocked["observation"] == {}
    assert blocked["signals"] == {}
    assert "resident_payload_missing" in blocked["quality"]["blocker_codes"]

    for envelope in envelopes:
        replay = restarted.ingest(envelope)
        assert replay["accepted"] is True
        assert replay["idempotent_replay"] is True
    assert restarted.shadow_snapshot()["ready"] is True


def test_dynamic_sources_outside_alignment_window_fail_closed(tmp_path, monkeypatch) -> None:
    ready_shadow_settings(monkeypatch)
    gateway = PortIntegrationGateway(
        signing_keys={adapter_id: SECRET for adapter_id in DATA_ADAPTER_CONTRACTS},
        state_path=tmp_path / "state.json",
        port_id="PORT-TEST",
        clock=lambda: NOW,
    )
    for adapter_id in DATA_ADAPTER_CONTRACTS:
        observed_at = (
            NOW - timedelta(minutes=8)
            if adapter_id == "weather_and_navigation_feed"
            else NOW
        )
        assert gateway.ingest(
            shadow_source_snapshot(adapter_id, observed_at=observed_at)
        )["accepted"] is True

    status = gateway.status()
    assert status["ready_adapter_count"] == len(DATA_ADAPTER_CONTRACTS)
    assert status["dynamic_time_alignment"]["observed_skew_seconds"] == 480.0
    assert status["dynamic_time_alignment"]["ready"] is False
    assert status["read_only_shadow_ready"] is False
    assert "dynamic_sources_not_time_aligned" in status["blocker_codes"]
    assert gateway.shadow_snapshot()["observation"] == {}
