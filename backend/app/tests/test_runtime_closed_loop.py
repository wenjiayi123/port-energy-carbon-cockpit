from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.runtime_decision import RuntimeDecisionService
from app.services.runtime_forecast import runtime_forecast_model
from app.services.runtime_simulator import RealtimePortSimulator


def build_simulator() -> RealtimePortSimulator:
    return RealtimePortSimulator(seed=20260814, auto_advance=False)


def test_runtime_field_contract_is_complete_and_classified() -> None:
    snapshot = build_simulator().snapshot(advance=False)

    assert snapshot["schema_version"] == "energy-carbon-runtime.v1"
    assert snapshot["simulation_mode"] is True
    assert snapshot["live_data_verified"] is False
    assert snapshot["dispatch_allowed"] is False
    assert snapshot["production_authority"] is False
    assert snapshot["data_mode"] == "public_data_calibrated_realtime_simulation"
    assert len(snapshot["signals"]) >= 40
    required = {
        "value",
        "unit",
        "event_time",
        "ingest_time",
        "source_type",
        "source_id",
        "quality_status",
        "confidence",
        "is_measured",
        "is_simulated",
        "is_derived",
        "site_id",
        "asset_id",
        "schema_version",
        "trace_id",
    }
    for field in snapshot["signals"].values():
        assert required <= set(field)
        assert sum(
            bool(field[name])
            for name in ("is_measured", "is_simulated", "is_derived")
        ) == 1
    counts = snapshot["quality"]["classification_counts"]
    assert counts["measured"] > 0
    assert counts["simulated"] > 0
    assert counts["derived"] > 0


def test_runtime_is_seed_reproducible_conservative_and_physically_bounded() -> None:
    first = build_simulator()
    second = build_simulator()
    first_values = first.advance(8)
    second_values = second.advance(8)
    keys = (
        "grid.import_power_kw",
        "solar.available_power_kw",
        "battery.soc_pct",
        "battery.temperature_c",
        "operations.queue_teu",
        "hvac.load_kw",
    )
    assert {
        key: first_values["signals"][key]["value"] for key in keys
    } == {key: second_values["signals"][key]["value"] for key in keys}
    assert first_values["quality"]["energy_balance_error_kw"] < 1e-5
    assert 10.0 <= first_values["signals"]["battery.soc_pct"]["value"] <= 90.0
    assert (
        first_values["signals"]["grid.import_power_kw"]["value"]
        <= first_values["signals"]["transformer.capacity_kw"]["value"]
    )
    assert first_values["kpis"]["cumulative"]["energy_kwh"] > 0


def test_forecast_is_real_current_input_inference_with_time_isolation() -> None:
    snapshot = build_simulator().advance(2)
    forecast = runtime_forecast_model.predict(snapshot)
    model = runtime_forecast_model.metadata()

    assert forecast["true_model_inference"] is True
    assert forecast["input_snapshot_sha256"] == snapshot["snapshot_sha256"]
    assert [point["horizon_hours"] for point in forecast["points"]] == [1, 3, 6]
    assert all(point["predictions"]["terminal_load_kw"] > 0 for point in forecast["points"])
    assert model["train_split"] == "train"
    assert model["selection_split"] == "validation"
    assert model["test_split"] == "test"
    assert model["future_test_rows_accessed_during_inference"] is False
    assert model["fit_solver"] == "augmented_least_squares"
    assert model["coefficient_quantization_decimals"] == 8
    assert len(model["model_sha256"]) == 64
    assert all(
        evidence["held_out_test_mae"]["terminal_load_kw"] >= 0
        for evidence in model["evidence"].values()
    )


def test_decision_requires_distinct_approvers_then_executes_and_rolls_back(tmp_path) -> None:
    simulator = build_simulator()
    service = RuntimeDecisionService(
        simulator,
        runtime_forecast_model,
        state_path=tmp_path / "decisions.json",
        audit_writer=None,
    )
    record = service.create(
        objective="balanced",
        idempotency_key="closed-loop-create-001",
        requested_by="operator-a",
    )
    replay = service.create(
        objective="balanced",
        idempotency_key="closed-loop-create-001",
        requested_by="operator-a",
    )

    assert replay["decision_id"] == record["decision_id"]
    assert set(record["projected_action"]) == {
        "battery_power_kw",
        "hvac_setpoint_c",
        "shore_power_limit_kw",
        "agv_charging_limit_kw",
    }
    assert record["required_approvals"] == 2
    with pytest.raises(ValueError, match="requester_cannot_self_approve"):
        service.approve(
            record["decision_id"],
            approver_id="operator-a",
            decision="approve",
            comment="self approval",
            idempotency_key="approval-self-001",
        )
    first_approval = service.approve(
        record["decision_id"],
        approver_id="supervisor-b",
        decision="approve",
        comment="operations review passed",
        idempotency_key="approval-b-001",
    )
    assert first_approval["status"] == "awaiting_approval"
    with pytest.raises(RuntimeError, match="decision_not_approved"):
        service.execute(
            record["decision_id"],
            idempotency_key="execute-too-early-001",
            executor_id="sim-executor",
        )
    approved = service.approve(
        record["decision_id"],
        approver_id="energy-manager-c",
        decision="approve",
        comment="energy review passed",
        idempotency_key="approval-c-001",
    )
    assert approved["status"] == "approved"
    executed = service.execute(
        record["decision_id"],
        idempotency_key="execute-001",
        executor_id="sim-executor",
    )
    assert executed["status"] == "executed_simulation"
    assert executed["execution_receipt"]["status"] == "acknowledged"
    assert executed["execution_receipt"]["production_dispatch"] is False
    assert executed["execution_receipt"]["kpi_delta"]
    assert service.audit(record["decision_id"])["chain_valid"] is True
    assert service.audit(record["decision_id"])["record_sha256_valid"] is True
    rolled_back = service.rollback(
        record["decision_id"],
        idempotency_key="rollback-001",
        requested_by="operator-a",
        reason="acceptance-test rollback",
    )
    assert rolled_back["status"] == "rolled_back_simulation"
    assert rolled_back["rollback"]["status"] == "acknowledged"


def test_runtime_loss_fails_closed_for_prediction_and_decision(tmp_path) -> None:
    simulator = build_simulator()
    simulator.inject_scenario("communications_loss", 3)
    snapshot = simulator.snapshot(advance=False)
    service = RuntimeDecisionService(
        simulator,
        runtime_forecast_model,
        state_path=tmp_path / "decisions.json",
        audit_writer=None,
    )

    assert snapshot["decision_allowed"] is False
    assert snapshot["quality"]["status"] == "fail_closed"
    assert all(
        signal["quality_status"] == "失联" for signal in snapshot["signals"].values()
    )
    with pytest.raises(RuntimeError, match="runtime_quality_gate_failed"):
        runtime_forecast_model.predict(snapshot)
    with pytest.raises(RuntimeError, match="runtime_quality_gate_failed"):
        service.create(
            objective="peak",
            idempotency_key="closed-loop-loss-001",
            requested_by="operator-a",
        )
    stopped = simulator.stop()
    assert stopped["simulator_state"] == "stopped"
    assert stopped["decision_allowed"] is False


def test_runtime_http_surface_exposes_contract_and_fail_closed_control() -> None:
    client = TestClient(app)
    reset = client.post(
        "/api/runtime/control",
        json={"action": "reset", "idempotency_key": "http-reset-001"},
    )
    contract = client.get("/api/runtime/contract")
    forecast = client.get("/api/runtime/forecast")
    stop = client.post(
        "/api/runtime/control",
        json={"action": "stop", "idempotency_key": "http-stop-001"},
    )
    blocked_forecast = client.get("/api/runtime/forecast")
    client.post(
        "/api/runtime/control",
        json={"action": "start", "idempotency_key": "http-start-001"},
    )

    assert reset.status_code == 200
    assert contract.status_code == 200
    assert contract.json()["field_count"] >= 40
    assert forecast.status_code == 200
    assert stop.json()["decision_allowed"] is False
    assert blocked_forecast.status_code == 409
