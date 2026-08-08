from datetime import datetime, timedelta, timezone
import hashlib
import json

from app.integration.gateway import PortIntegrationGateway, SnapshotEnvelope, canonical_json


NOW = datetime(2026, 8, 8, 8, 0, tzinfo=timezone.utc)
SECRET = "adapter-specific-secret-with-at-least-32-characters"


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
