from urllib.parse import urlsplit

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings, settings
from app.main import app


client = TestClient(app)


def test_health_and_rl_capabilities_are_real() -> None:
    health = client.get("/api/health")
    assert health.json()["status"] == "ok"
    assert health.headers["x-request-id"]
    assert health.headers["x-content-type-options"] == "nosniff"
    assert client.get("/api/health/live").json()["status"] == "ok"
    ready = client.get("/api/health/ready")
    assert ready.status_code == 200
    assert ready.json()["checks"]["default_dataset"]["quality_score"] == 100
    metrics = client.get("/api/metrics")
    assert "energy_carbon_http_requests_total" in metrics.text
    payload = client.get("/api/rl/capabilities").json()

    assert payload["runtime"]["available"] is True
    assert {item["id"] for item in payload["algorithms"]} == {"ppo", "sac", "td3", "dqn", "mpc"}
    assert sum(item["family"] == "reinforcement_learning" for item in payload["algorithms"]) == 4
    assert sum(item["family"] == "control_theory" for item in payload["algorithms"]) == 1
    assert payload["training_render_mode"] is None
    assert payload["evaluation_render_mode"] == "trajectory"


def test_dashboard_uses_public_test_split_and_measured_trajectory() -> None:
    response = client.get("/api/dashboard/snapshot")
    payload = response.json()
    baseline, optimized = payload["strategies"]

    assert response.status_code == 200
    assert payload["scenario_id"] == "port_la_2025_public_benchmark"
    assert baseline["strategy"] == "Reference:FixedRule"
    assert optimized["strategy"] == "MPC"
    assert len(baseline["trajectory"]) == len(optimized["trajectory"]) == 24
    assert payload["rl_environment"]["environment_id"] == "PortEnergyDispatchEnv-v1"
    assert payload["rl_environment"]["dataset_id"] == "port_la_2020_2025_hourly"
    assert len(payload["rl_environment"]["dataset_sha256"]) == 64
    assert len(payload["timeseries"]) == 24

    point = optimized["trajectory"][0]
    assert point["load_kw"] > 0
    assert point["processed_teu"] > 0
    assert point["carbon_kg"] == point["grid_carbon_kg"] + point["fuel_carbon_kg"]
    assert point["peak_violation_kw"] >= 0


def test_carbon_model_is_traceable_to_dataset_hash() -> None:
    payload = client.get("/api/dashboard/snapshot").json()
    carbon = payload["carbon_model"]

    assert carbon["model_version"] == "dataset-carbon-accounting-v1.1"
    assert carbon["dataset_sha256"] == payload["rl_environment"]["dataset_sha256"]
    assert "Port of Los Angeles" in carbon["data_source"]
    assert "Scope 1" in carbon["calculation_method"]
    assert abs(sum(carbon["source_breakdown_kg"].values()) - carbon["total_carbon_kg"]) < 0.01
    assert carbon["scope1_auxiliary_fuel_kg"] >= 0
    assert carbon["scope2_location_based_kg"] > 0
    assert carbon["scope2_market_based_kg"] is None
    assert payload["data_quality"]["score"] == 100
    assert payload["data_drift"]["status"] == "review"
    assert 0.5 <= payload["data_drift"]["max_shift"] < 1.0
    assert payload["governance"]["production_dispatch_enabled"] is False
    assert {alert["code"] for alert in payload["alerts"]} >= {
        "SCOPE2_MARKET_BASED_UNAVAILABLE",
        "PRODUCTION_ADAPTERS_NOT_CONNECTED",
    }


def test_recompute_uses_request_parameters_without_changing_test_horizon() -> None:
    response = client.post(
        "/api/optimization/recompute",
        json={
            "scenario_id": "port_la_2025_public_benchmark",
            "green_preference": 0.75,
            "carbon_price_cny_per_ton": 120,
        },
    )
    payload = response.json()

    assert response.status_code == 200
    assert payload["green_preference"] == 0.75
    assert payload["carbon_market"]["carbon_price_cny_per_ton"] == 120
    assert payload["carbon_market"]["quota_basis"] == "scenario:baseline_emissions_reference"
    assert payload["carbon_market"]["price_basis"] == "scenario:user_input"
    assert len(payload["timeseries"]) == 24


def test_dataset_validation_endpoint_records_public_provenance() -> None:
    response = client.post(
        "/api/rl/datasets/validate",
        json={"dataset_id": "port_la_2020_2025_hourly"},
    )
    payload = response.json()["dataset"]

    assert response.status_code == 200
    assert payload["rows"] == 52_608
    assert payload["train_rows"] == 35_064
    assert payload["validation_rows"] == 8_784
    assert payload["test_rows"] == 8_760
    assert len(payload["sha256"]) == 64
    source_urls = payload["metadata"]["source_urls"]
    assert len(source_urls) >= 10
    parsed_sources = [urlsplit(url) for url in source_urls]
    assert any(
        source.scheme == "https"
        and (source.hostname == "www.eia.gov" or source.hostname == "api.eia.gov")
        for source in parsed_sources
    )
    assert any(
        source.scheme == "https" and source.hostname == "www.epa.gov"
        for source in parsed_sources
    )
    assert payload["quality"]["status"] == "pass"
    assert payload["quality"]["score"] == 100
    assert payload["drift"]["method"] == "absolute_standardized_mean_difference"


def test_landing_benchmark_endpoint_exposes_increment_and_adverse_tradeoffs() -> None:
    response = client.get("/api/evidence/landing-benchmark")
    payload = response.json()
    business = payload["business_metrics_vs_fixed_full_resources"]
    increment = payload["algorithm_increment_vs_causal_legacy_mpc"]

    assert response.status_code == 200
    assert response.headers["etag"].startswith('"')
    assert payload["evidence_label"] == "CAUSAL_OFFLINE_ROBUSTNESS_BENCHMARK_NOT_FIELD_KPI"
    assert payload["protocol"]["steps"] == 1_152
    assert business["carbon_reduction_pct"] == 8.7924
    assert business["constraint_success_rate_pct"] == 100.0
    assert increment["delay_reduction_pct"] == 43.8805
    assert increment["carbon_reduction_pct"] < 0
    assert payload["per_window_evidence_included"] is False
    assert "per_window" not in payload


def test_port_scenarios_expose_fail_closed_v3_contract() -> None:
    contract = client.get("/api/scenarios/contract")
    scenarios = client.get("/api/scenarios")

    assert contract.status_code == 200
    assert contract.json()["environment_id"] == "PortEnergyDispatchEnv-v3"
    assert "weather_and_navigation" in contract.json()["observations"]
    assert len(contract.json()["actions"]["continuous"]) == 4

    assert scenarios.status_code == 200
    items = {item["id"]: item for item in scenarios.json()}
    enhanced = items["port_la_vessel_activity_benchmark"]
    assert enhanced["readiness"]["offline_benchmark_ready"] is True
    assert enhanced["dataset"]["rows"] == 43_848
    live_templates = [item for item in items.values() if item["mode"] == "live_port_template"]
    assert live_templates
    assert all(not item["readiness"]["production_ready"] for item in live_templates)


def test_training_scenario_and_dataset_must_resolve_to_same_contract() -> None:
    valid = client.post(
        "/api/rl/train/start",
        json={
            "config": {
                "scenario": "port_la_vessel_activity_benchmark",
                "dataset_id": "port_la_2020_2024_vessel_activity_hourly",
                "algorithm": "dqn",
                "total_steps": 32,
            }
        },
    )
    mismatch = client.post(
        "/api/rl/train/start",
        json={
            "config": {
                "scenario": "port_la_public_benchmark",
                "dataset_id": "port_la_2020_2024_vessel_activity_hourly",
                "algorithm": "dqn",
                "total_steps": 32,
            }
        },
    )
    live_template = client.post(
        "/api/rl/train/start",
        json={
            "config": {
                "scenario": "port_rotterdam_live_template",
                "dataset_id": "port_la_2020_2024_vessel_activity_hourly",
                "algorithm": "dqn",
                "total_steps": 32,
            }
        },
    )

    assert valid.status_code == 200
    assert valid.json()["preview"]["scenario"] == "port_la_vessel_activity_benchmark"
    assert valid.json()["preview"]["environment_id"] == "PortEnergyDispatchEnv-v2"
    assert mismatch.status_code == 422
    assert mismatch.json()["detail"] == "training_configuration_invalid"
    assert live_template.status_code == 422
    assert live_template.json()["detail"] == "training_configuration_invalid"


def test_xiaoyi_training_preview_preserves_nested_ui_configuration() -> None:
    response = client.post(
        "/api/assistant/actions/execute",
        json={
            "instruction": "小懿，开始训练碳排最低目标",
            "action_id": "start_rl_training",
            "dry_run": True,
            "objective_id": "carbon_min",
            "config": {
                "objective_id": "carbon_min",
                "objective_label": "碳排最低目标",
                "algorithm": "dqn",
                "scenario": "port_la_vessel_activity_benchmark",
                "data_file": "port_la_2020_2024_vessel_activity_hourly",
                "total_steps": 32,
                "batch_size": 64,
                "learning_rate": 0.0001,
                "gamma": 0.99,
                "tau": 0,
                "entropy_coef": 0,
                "reward_weights": {"carbon": 0.8, "safety": 0.2},
            },
        },
    )

    assert response.status_code == 200
    config = response.json()["recommendation"]["config"]
    assert config["algorithm"] == "dqn"
    assert config["dataset_id"] == "port_la_2020_2024_vessel_activity_hourly"
    assert config["scenario"] == "port_la_vessel_activity_benchmark"
    assert config["total_steps"] == 32
    assert config["tau"] == 0
    assert config["reward_weights"] == {"carbon": 0.8, "safety": 0.2}


def test_http_dataset_inputs_cannot_read_arbitrary_server_paths() -> None:
    validation = client.post("/api/rl/datasets/validate", json={"data_file": "/etc/passwd"})
    training = client.post(
        "/api/rl/train/start",
        json={"config": {"algorithm": "mpc", "data_file": "../../private.csv"}},
    )

    assert validation.status_code == 422
    assert training.status_code == 422
    assert validation.json()["detail"] == "dataset_validation_failed"
    assert training.json()["detail"] == "training_configuration_invalid"


def test_dispatch_endpoint_emits_idempotent_shadow_packet_and_rollback_target() -> None:
    payload = {
        "strategy_id": "auto:latest",
        "dry_run": True,
        "idempotency_key": "operator-shift-20260808-decision-001",
    }
    first = client.post("/api/rl/dispatch", json=payload)
    second = client.post("/api/rl/dispatch", json=payload)

    assert first.status_code == 200
    assert first.json()["status"] == "shadow_decision_recorded"
    assert first.json()["decision_id"] == second.json()["decision_id"]
    assert first.json()["execution_authorized"] is False
    assert first.json()["production_dispatch_enabled"] is False
    assert first.json()["rollback_target"] == "published:offline-mpc-v3"
    assert first.json()["artifact_sha256"]


def test_strategy_ids_reject_path_traversal() -> None:
    response = client.post("/api/rl/simulate", json={"strategy_id": "../../outside"})

    assert response.status_code == 404
    assert response.json()["detail"] == "policy_artifact_not_found"


def test_mpc_controller_artifact_and_held_out_evaluation() -> None:
    started = client.post(
        "/api/rl/train/start",
        json={
            "confirm": True,
            "config": {
                "algorithm": "mpc",
                "dataset_id": "port_la_2020_2025_hourly",
                "episode_hours": 2,
            },
        },
    ).json()["result"]

    assert started["status"] == "completed"
    assert started["total_steps"] == 0
    assert started["rendering"] is False
    evaluation = client.post("/api/rl/simulate", json={"strategy_id": started["job_id"]}).json()
    assert evaluation["status"] == "tested"
    assert evaluation["split"] == "test"
    assert evaluation["render_mode"] == "trajectory"
    assert evaluation["metrics"]["test_episodes"] == 48
    assert len(evaluation["trajectory"]) == 2
    registry = client.get("/api/rl/registry").json()
    policy = next(item for item in registry["policies"] if item["policy_id"] == started["job_id"])
    assert policy["artifact_integrity"] == "verified"
    assert policy["dataset_status"] == "verified"
    assert policy["drift"]["status"] == "review"
    # A review-level train/test shift remains visible but does not erase a
    # successful offline evaluation. Production eligibility is governed by the
    # separate fail-closed adapter and human-approval gate below.
    assert policy["stage"] == "validated_offline"
    assert policy["production_eligible"] is False


def test_production_security_configuration_and_mutation_gate() -> None:
    with pytest.raises(ValueError, match="Production requires"):
        Settings(app_env="production", api_auth_mode="disabled")
    secure = Settings(
        app_env="production",
        api_auth_mode="api_key",
        operator_api_key="operator-key-with-at-least-24-characters",
    )
    assert secure.production is True

    original_mode = settings.api_auth_mode
    original_operator = settings.operator_api_key
    try:
        settings.api_auth_mode = "api_key"
        settings.operator_api_key = "operator-key-with-at-least-24-characters"
        assert client.get("/api/health/live").status_code == 200
        assert client.post("/api/rl/train/stop").status_code == 401
        authorized = client.post(
            "/api/rl/train/stop",
            headers={"X-API-Key": settings.operator_api_key},
        )
        assert authorized.status_code == 200
    finally:
        settings.api_auth_mode = original_mode
        settings.operator_api_key = original_operator


def test_xiaoyi_summary_uses_new_strategy_names() -> None:
    response = client.post(
        "/api/assistant/actions/execute",
        json={
            "action_id": "set_low_carbon_priority",
            "instruction": "小懿，切到低碳优先",
            "dry_run": False,
            "confirm": True,
            "carbon_price_cny_per_ton": 120,
        },
    )
    result = response.json()["execution_result"]["result"]

    assert response.status_code == 200
    assert result["green_preference"] == 0.82
    assert result["optimized_policy"]["strategy"] in {"MPC", "RL:PPO", "RL:SAC", "RL:TD3", "RL:DQN"}
    assert result["carbon_reduction_ton"] > 0
