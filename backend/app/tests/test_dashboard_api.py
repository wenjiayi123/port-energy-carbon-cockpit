import hashlib
import json
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
    assert payload["business_scope"]["environment_id"] == "PortEnergyDispatchEnv-v5"
    assert payload["business_scope"]["observation_count"] == 73
    assert payload["business_scope"]["continuous_action_count"] == 10
    assert payload["business_scope"]["claim_boundary"]["production_authority"] is False
    assert payload["hybrid_business_scope"]["environment_id"] == (
        "PortEnergyHybridResidualEnv-v6"
    )
    assert payload["hybrid_business_scope"]["policy_output_count"] == 16

    coverage = client.get("/api/rl/business-coverage")
    assert coverage.status_code == 200
    assert coverage.json()["domain_count"] == 26
    authority = {
        item["domain"]: item for item in coverage.json()["domains"]
    }["authority_release"]
    assert authority["status"] == "prohibited_for_rl"

    hybrid_coverage = client.get("/api/rl/hybrid-business-coverage")
    assert hybrid_coverage.status_code == 200
    assert hybrid_coverage.json()["decision_counts"]["rl_or_hybrid_strategy"] == 16
    assert hybrid_coverage.json()["decision_counts"]["pure_control_or_physics"] == 1

    replacement = client.get(
        "/api/rl/datasets/port_la_2020_2024_operational_flex_hourly/replacement-readiness"
    )
    assert replacement.status_code == 200
    assert replacement.json()["offline_schema_compatible"] is True
    assert replacement.json()["site_training_ready"] is False
    hybrid_replacement = client.get(
        "/api/rl/datasets/port_la_2020_2024_hybrid_rl_hourly/replacement-readiness"
    )
    assert hybrid_replacement.status_code == 200
    assert len(hybrid_replacement.json()["required_measurement_columns"]) == 66
    assert len(hybrid_replacement.json()["blockers"]) == 13

    evidence = client.get("/api/rl/operational-flex-evidence")
    assert evidence.status_code == 200
    if evidence.json()["available"]:
        assert evidence.json()["schema_version"] == "operational-flex-business-value.v1"
        assert evidence.json()["production_boundary"]["production_authority"] is False
    else:
        assert evidence.json()["status"] == "training_or_evaluation_pending"
        assert evidence.json()["production_eligible"] is False
    hybrid_evidence = client.get("/api/rl/hybrid-evidence")
    assert hybrid_evidence.status_code == 200
    assert hybrid_evidence.json()["production_eligible"] is False


def test_shadow_snapshot_api_fails_closed_without_six_resident_live_sources() -> None:
    contract = client.get("/api/integration/contract")
    assert contract.status_code == 200
    assert contract.json()["composite_shadow_state"]["required_adapter_count"] == 6
    assert contract.json()["composite_shadow_state"]["required_field_count"] == 21

    response = client.get("/api/integration/shadow-snapshot")
    assert response.status_code == 200
    payload = response.json()
    assert payload["schema_version"] == "port-shadow-state.v1"
    assert payload["ready"] is False
    assert payload["quality"]["gate"] == "FAIL_CLOSED"
    assert payload["observation"] == {}
    assert payload["signals"] == {}
    assert payload["production_boundary"]["live_data_verified"] is False
    assert payload["production_boundary"]["production_authority"] is False


def test_public_rl_surfaces_do_not_expose_local_absolute_paths() -> None:
    for path in ("/api/rl/train/status", "/api/rl/registry", "/api/rl/strategies"):
        response = client.get(path)
        assert response.status_code == 200
        assert "/Users/" not in response.text
        assert "/home/" not in response.text


def test_public_linkage_surfaces_are_portable_and_do_not_expose_launch_commands() -> None:
    responses = [
        client.get("/api/linkage/health"),
        client.get("/api/xiaoyi/status"),
        client.get("/api/sailing/status"),
        client.get("/api/rl/actions/registry"),
        client.post(
            "/api/xiaoyi/launch",
            json={"dry_run": True, "source": "test"},
        ),
        client.post(
            "/api/sailing/launch",
            json={"dry_run": True, "source": "test"},
        ),
    ]

    for response in responses:
        assert response.status_code == 200
        assert "/Users/" not in response.text
        assert "/home/" not in response.text
        assert '"start_command"' not in response.text
        assert '"command"' not in response.text

    health = responses[0].json()
    assert health["systems"]["energy_carbon_cockpit"]["project_root"] == "."
    assert health["systems"]["runtime_closed_loop"]["production_boundary"] == {
        "simulation_mode": True,
        "live_data_verified": False,
        "dispatch_allowed": False,
        "production_authority": False,
    }


def test_xiaoyi_runtime_actions_are_grounded_and_preserve_separation_of_duties() -> None:
    registry = client.get("/api/rl/actions/registry").json()
    actions = {item["id"]: item for item in registry["actions"]}
    expected = {
        "open_runtime_panel",
        "summarize_runtime_state",
        "prepare_runtime_handover",
        "triage_runtime_alerts",
        "create_runtime_recommendation",
        "explain_runtime_recommendation",
    }
    assert expected <= set(actions)
    assert actions["create_runtime_recommendation"]["requires_human_confirm"] is True
    assert actions["summarize_runtime_state"]["requires_human_confirm"] is False
    assert not any("approve" in action_id or "execute_runtime" in action_id for action_id in expected)

    results = {}
    for action_id in (
        "summarize_runtime_state",
        "prepare_runtime_handover",
        "triage_runtime_alerts",
        "explain_runtime_recommendation",
    ):
        response = client.post(
            "/api/assistant/actions/execute",
            json={
                "action_id": action_id,
                "instruction": action_id,
                "dry_run": False,
                "confirm": True,
            },
        )
        assert response.status_code == 200
        assert response.json()["matched"] is True
        assert "/Users/" not in response.text
        assert "/home/" not in response.text
        results[action_id] = response.json()["execution_result"]["result"]

    summary = results["summarize_runtime_state"]
    assert summary["field_count"] == 51
    assert summary["forecast"]["true_model_inference"] is True
    assert summary["production_boundary"]["production_authority"] is False
    assert results["prepare_runtime_handover"]["shift_handover"]["operator_note"]
    assert results["triage_runtime_alerts"]["operator_actions"]
    explanation = results["explain_runtime_recommendation"]
    assert explanation.get("production_authority", explanation.get("decision", {}).get("production_authority")) is False

    preview = client.post(
        "/api/assistant/actions/execute",
        json={
            "action_id": "create_runtime_recommendation",
            "instruction": "生成当前运行建议",
            "dry_run": False,
            "confirm": False,
        },
    ).json()
    assert preview["human_confirmation"]["needed_before_execution"] is True
    assert preview["execution_result"]["executed"] is False
    assert preview["execution_result"]["result"]["production_authority"] is False


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
        "PORT_EMISSIONS_INVENTORY_INCOMPLETE",
        "PRODUCTION_ADAPTERS_NOT_CONNECTED",
    }


def test_port_emissions_inventory_exposes_complete_source_contract_and_assurance_gate() -> None:
    response = client.get("/api/dashboard/carbon-inventory")
    inventory = response.json()

    assert response.status_code == 200
    assert inventory["schema_version"] == "port-emissions-inventory.v1"
    assert inventory["dataset_sha256"] == client.get("/api/dashboard/snapshot").json()[
        "rl_environment"
    ]["dataset_sha256"]
    sources = {item["source_id"]: item for item in inventory["source_categories"]}
    assert len(sources) == 7
    assert sources["purchased_electricity"]["availability"] == "calculated_scenario"
    assert sources["ocean_going_vessels_at_berth"]["ghg_scope"].startswith(
        "unassigned_requires"
    )
    assert sources["heavy_duty_vehicles"]["co2e_kg"] is None
    assert sources["rail_locomotives"]["co2e_kg"] is None
    assert all(
        value is None
        for source in sources.values()
        for value in source["pollutants_kg"].values()
    )
    assert inventory["coverage"] == {
        "source_category_count": 7,
        "co2e_calculated_count": 2,
        "live_measured_count": 0,
        "criteria_pollutant_ready_count": 0,
        "criteria_pollutant_count": 8,
        "modeled_source_coverage_pct": 28.6,
        "inventory_complete": False,
        "live_inventory_ready": False,
    }
    assert inventory["assurance"]["status"] == "blocked"
    assert inventory["production_boundary"] == {
        "simulation_mode": True,
        "live_data_verified": False,
        "inventory_assured": False,
        "regulatory_submission_allowed": False,
    }
    unsigned = {key: value for key, value in inventory.items() if key != "evidence_sha256"}
    expected_hash = hashlib.sha256(
        json.dumps(
            unsigned,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    assert inventory["evidence_sha256"] == expected_hash


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


def test_regulatory_resilience_endpoint_exposes_qualified_increment_and_boundary() -> None:
    response = client.get("/api/evidence/regulatory-resilience")
    payload = response.json()
    metrics = payload["business_metrics_vs_preserved_legacy"]

    assert response.status_code == 200
    assert response.headers["etag"].startswith('"')
    assert payload["status"] == "qualified_offline"
    assert payload["offline_admission_gate"]["status"] == "passed"
    assert payload["boundary"]["authority_signals"] == "exogenous"
    assert payload["production_authority"] is False
    assert metrics["scenario_cost_reduction_pct"] == 0.666
    assert metrics["carbon_reduction_pct"] == 0.688
    assert metrics["total_delay_reduction_pct"] == 0.0
    assert metrics["peak_change_pct"] == -0.601
    assert payload["history_preservation"]["history_preserved"] is True
    assert len(payload["preserved_failed_candidates"]) == 2
    assert payload["per_window_evidence_included"] is False


def test_evidence_history_preserves_blocked_candidate_without_local_paths() -> None:
    response = client.get("/api/evidence/history")
    payload = response.json()
    entries = {entry["evidence_id"]: entry for entry in payload["entries"]}

    assert response.status_code == 200
    assert payload["schema_version"] == "history-evidence.v1"
    assert payload["history_preserved"] is True
    assert payload["production_authority"] is False
    assert payload["entry_count"] == 8
    blocked = entries["td3-rl-20260725-233109-6ac68e"]
    assert blocked["status"] == "blocked"
    assert blocked["decision"] == "rejected_by_admission_gate"
    assert "carbon_non_regression" in blocked["failed_checks"]
    assert len(blocked["artifact_sha256"]) == 64
    assert entries["public-calibrated-causal-ridge-v1"][
        "future_test_rows_accessed_during_inference"
    ] is False
    assert entries["regulatory_resilience_v1_full_action_sac"]["status"] == (
        "blocked_candidate_preserved"
    )
    assert entries["regulatory_resilience_v2_simple_shield"]["status"] == (
        "blocked_candidate_preserved"
    )
    assert entries["regulatory_resilience_v3_dominance_projected_sac"]["status"] == (
        "qualified_offline"
    )
    assert "/Users/" not in response.text


def test_port_scenarios_expose_fail_closed_v3_contract() -> None:
    contract = client.get("/api/scenarios/contract")
    operational_flex_contract = client.get("/api/scenarios/operational-flex-contract")
    hybrid_contract = client.get("/api/scenarios/hybrid-rl-contract")
    scenarios = client.get("/api/scenarios")

    assert contract.status_code == 200
    assert contract.json()["environment_id"] == "PortEnergyDispatchEnv-v3"
    assert "weather_and_navigation" in contract.json()["observations"]
    assert len(contract.json()["actions"]["continuous"]) == 4
    assert operational_flex_contract.status_code == 200
    assert operational_flex_contract.json()["environment_id"] == "PortEnergyDispatchEnv-v5"
    assert len(operational_flex_contract.json()["actions"]["continuous"]) == 10
    assert hybrid_contract.status_code == 200
    assert hybrid_contract.json()["environment_id"] == "PortEnergyHybridResidualEnv-v6"
    assert hybrid_contract.json()["observation_count"] == 106
    assert hybrid_contract.json()["action_count"] == 16

    assert scenarios.status_code == 200
    items = {item["id"]: item for item in scenarios.json()}
    enhanced = items["port_la_vessel_activity_benchmark"]
    operational_flex = items["port_la_operational_flex_benchmark"]
    hybrid = items["port_la_hybrid_rl_benchmark"]
    assert enhanced["readiness"]["offline_benchmark_ready"] is True
    assert enhanced["dataset"]["rows"] == 43_848
    assert operational_flex["readiness"]["offline_benchmark_ready"] is True
    assert operational_flex["dataset"]["environment_id"] == "PortEnergyDispatchEnv-v5"
    assert hybrid["readiness"]["offline_benchmark_ready"] is True
    assert hybrid["dataset"]["environment_id"] == "PortEnergyHybridResidualEnv-v6"
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


def test_xiaoyi_training_preview_defaults_to_hybrid_rl_v6() -> None:
    response = client.post(
        "/api/assistant/actions/execute",
        json={
            "instruction": "小懿，开始训练碳排最低目标",
            "action_id": "start_rl_training",
            "dry_run": True,
            "objective_id": "carbon_min",
        },
    )

    assert response.status_code == 200
    config = response.json()["recommendation"]["config"]
    assert config["dataset_id"] == "port_la_2020_2024_hybrid_rl_hourly"
    assert config["scenario"] == "port_la_hybrid_rl_benchmark"
    assert config["scenario_environment_id"] == "PortEnergyHybridResidualEnv-v6"
    assert config["asset_group"] == "vessel_berth_crane_yard_truck_energy_maintenance"
    assert len(config["reward_weights"]) == 17
    assert config["reward_weights"]["jit_service"] > 0
    assert config["reward_weights"]["maintenance_risk"] > 0


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
