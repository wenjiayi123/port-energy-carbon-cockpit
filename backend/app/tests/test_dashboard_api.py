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
    assert payload["rl_environment"]["dataset_id"] == "port_la_2025_monthly"
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
    response = client.post("/api/rl/datasets/validate", json={"dataset_id": "port_la_2025_monthly"})
    payload = response.json()["dataset"]

    assert response.status_code == 200
    assert payload["train_rows"] == 9
    assert payload["test_rows"] == 3
    assert len(payload["sha256"]) == 64
    assert len(payload["metadata"]["source_urls"]) == 2
    assert payload["quality"]["status"] == "pass"
    assert payload["quality"]["score"] == 100
    assert payload["drift"]["method"] == "absolute_standardized_mean_difference"


def test_http_dataset_inputs_cannot_read_arbitrary_server_paths() -> None:
    validation = client.post("/api/rl/datasets/validate", json={"data_file": "/etc/passwd"})
    training = client.post(
        "/api/rl/train/start",
        json={"config": {"algorithm": "mpc", "data_file": "../../private.csv"}},
    )

    assert validation.status_code == 422
    assert training.status_code == 422
    assert "registered dataset ID" in validation.json()["detail"]
    assert "registered dataset ID" in training.json()["detail"]


def test_strategy_ids_reject_path_traversal() -> None:
    response = client.post("/api/rl/simulate", json={"strategy_id": "../../outside"})

    assert response.status_code == 404
    assert "Invalid strategy ID" in response.json()["detail"]


def test_mpc_controller_artifact_and_held_out_evaluation() -> None:
    started = client.post(
        "/api/rl/train/start",
        json={"confirm": True, "config": {"algorithm": "mpc", "dataset_id": "port_la_2025_monthly"}},
    ).json()["result"]

    assert started["status"] == "completed"
    assert started["total_steps"] == 0
    assert started["rendering"] is False
    evaluation = client.post("/api/rl/simulate", json={"strategy_id": started["job_id"]}).json()
    assert evaluation["status"] == "tested"
    assert evaluation["split"] == "test"
    assert evaluation["render_mode"] == "trajectory"
    assert evaluation["metrics"]["test_episodes"] == 3
    assert len(evaluation["trajectory"]) == 24
    registry = client.get("/api/rl/registry").json()
    policy = next(item for item in registry["policies"] if item["policy_id"] == started["job_id"])
    assert policy["artifact_integrity"] == "verified"
    assert policy["dataset_status"] == "verified"
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
