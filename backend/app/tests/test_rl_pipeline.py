from __future__ import annotations

import json
import importlib.util
import time

import pytest

import app.rl.dataset as dataset_module
import app.rl.policy_selection as policy_selection
import app.rl.training as training_module
from app.rl.benchmark import select_validation_static_reference
from app.rl.dataset import PortDataset
from app.rl.catalog import ALGORITHM_CATALOG
from app.rl.environment import (
    DEFAULT_HYBRID_REWARD_WEIGHTS,
    DEPLOYMENT_OBSERVATION_KEYS,
    FLEXIBLE_OPERATIONS_OBSERVATION_KEYS,
    HYBRID_OBSERVATION_KEYS,
    OBSERVATION_KEYS,
    OPERATIONAL_OBSERVATION_KEYS,
    REGULATORY_OBSERVATION_KEYS,
    MPCPolicy,
    PortEnergyDispatchEnv,
    encode_continuous_controls,
)
from app.rl.hybrid_business_scope import hybrid_business_scope_contract
from app.rl.landing_readiness import assess_dataset_landing_readiness
from app.rl.operational_flex_benchmark import (
    _admission,
    _dominance_accepts,
    normalized_action_deviation,
)
from app.rl.robust import CausalForecastPortEnv, RiskAwareMPCPolicy, paired_bootstrap_interval
from app.rl.scenarios import (
    deployment_contract,
    hybrid_rl_contract,
    operational_flex_contract,
    resolve_training_scenario,
    scenario_items,
)
from app.rl.site_dataset_replacement import assess_site_replacement_readiness
from app.rl.training import TrainingService
from app.rl.tuning import load_search_space
from app.services.dispatch_simulator import DispatchSimulator


SB3_AVAILABLE = importlib.util.find_spec("stable_baselines3") is not None


def test_training_environment_never_renders_and_test_environment_does() -> None:
    training_env = PortEnergyDispatchEnv(split="train", episode_hours=4, render_mode=None)
    training_env.reset(seed=7)
    for _ in range(4):
        training_env.step(training_env.action_space.sample())
    assert training_env.render() is None

    test_env = PortEnergyDispatchEnv(split="test", episode_hours=4, render_mode="trajectory")
    test_env.reset(seed=7)
    for _ in range(4):
        test_env.step(test_env.action_space.sample())
    assert len(test_env.render() or []) == 4


def test_operational_flex_scenario_resolves_to_v5_dataset_and_contract() -> None:
    resolved = resolve_training_scenario(
        "port_la_operational_flex_benchmark",
        "port_la_2020_2024_operational_flex_hourly",
    )
    contract = operational_flex_contract()

    assert resolved["scenario_environment_id"] == "PortEnergyDispatchEnv-v5"
    assert contract["observation_count"] == 73
    assert len(contract["actions"]["continuous"]) == 10
    assert contract["actions"]["dqn_curated_templates"] == 243
    assert contract["production_authority"] is False


def test_hybrid_scenario_resolves_to_v6_dataset_and_contract() -> None:
    resolved = resolve_training_scenario(
        "port_la_hybrid_rl_benchmark",
        "port_la_2020_2024_hybrid_rl_hourly",
    )
    contract = hybrid_rl_contract()
    assert resolved["scenario_environment_id"] == "PortEnergyHybridResidualEnv-v6"
    assert contract["observation_count"] == 106
    assert contract["action_count"] == 16
    assert contract["decision_split"]["rl_or_hybrid_strategy_domains"] == 16
    assert contract["production_authority"] is False


def test_operational_flex_rl_contribution_measures_actual_ten_control_delta() -> None:
    baseline = {
        "shore_power_ratio": 0.5,
        "crane_ratio": 0.8,
        "yard_ratio": 0.8,
        "battery_power_ratio": 0.0,
        "inspection_readiness_ratio": 0.5,
        "recovery_priority_ratio": 0.5,
        "agv_charging_ratio": 0.5,
        "reefer_service_ratio": 0.875,
        "building_flexible_load_ratio": 0.675,
        "demand_response_ratio": 0.5,
    }
    identical = dict(baseline)
    shore_only = {**baseline, "shore_power_ratio": 1.0}

    assert normalized_action_deviation(identical, baseline) == 0.0
    assert normalized_action_deviation(shore_only, baseline) == pytest.approx(0.05)


def test_operational_flex_admission_rejects_low_demand_response_commitment() -> None:
    comparison = {
        "safety_violations": 0,
        "carbon_reduction_pct": 1.0,
        "cost_reduction_pct": 1.0,
        "throughput_change_pct": 0.0,
        "delay_reduction_pct": 0.0,
        "peak_reduction_pct": 1.0,
        "shore_power_change_pct": 0.0,
        "reward_change": 0.1,
        "agv_missed_required_kwh": 0.0,
        "reefer_thermal_violation_steps": 0,
        "demand_response_delivery_pct": 100.0,
        "demand_response_commitment_pct": 50.0,
        "carbon_reduction_ci95": {"ci95_low_pct": 0.1},
        "cost_reduction_ci95": {"ci95_low_pct": 0.1},
    }

    admission = _admission(comparison, contribution_pct=2.0)

    assert admission["status"] == "blocked"
    assert admission["checks"]["demand_response_delivery"] is True
    assert admission["checks"]["demand_response_commitment"] is False


def test_operational_flex_projection_rejects_low_commitment_before_execution() -> None:
    baseline = {
        "safety_violations": 0,
        "peak_violation_kw": 0.0,
        "agv_missed_required_kwh": 0.0,
        "reefer_thermal_violation_steps": 0,
        "processed_teu": 100.0,
        "delay_minutes": 1.0,
        "carbon_kg": 100.0,
        "cost": 100.0,
        "demand_response_target_kwh": 100.0,
        "demand_response_delivered_kwh": 100.0,
        "reward": 1.0,
    }
    low_commitment = {
        **baseline,
        "demand_response_target_kwh": 50.0,
        "demand_response_delivered_kwh": 50.0,
        "reward": 1.1,
    }
    covered = {
        **baseline,
        "demand_response_target_kwh": 98.0,
        "demand_response_delivered_kwh": 98.0,
        "reward": 1.1,
    }

    assert _dominance_accepts(low_commitment, baseline) is False
    assert _dominance_accepts(covered, baseline) is True


def test_causal_forecast_wrapper_never_reads_a_later_held_out_row() -> None:
    env = CausalForecastPortEnv(
        dataset="port_la_2020_2024_vessel_activity_hourly",
        split="test",
        episode_hours=2,
        render_mode=None,
    )
    env.reset(seed=7, options={"row_index": 0})
    _, reward, _, _, info = env.step([1.0, 0.8, 0.8, 0.0])
    assert isinstance(reward, float)
    assert "storage" in info["reward_terms"]
    assert env.reward_weights.get("storage", 0.0) == 0.0
    current_timestamp = str(env._row()["timestamp_utc"])
    assert str(env._row_at(1)["timestamp_utc"]) == current_timestamp
    assert str(env._row_at(3)["timestamp_utc"]) == current_timestamp

    policy = RiskAwareMPCPolicy(horizon=2, beam_width=2)
    controls = policy.predict(env)
    assert policy.last_certificate["future_test_rows_accessed"] is False
    env.step(encode_continuous_controls(controls))
    assert str(env._row()["timestamp_utc"]) != current_timestamp


def test_paired_bootstrap_is_deterministic_and_reports_window_count() -> None:
    first = paired_bootstrap_interval([80.0, 90.0, 100.0], [100.0, 100.0, 100.0], samples=500)
    second = paired_bootstrap_interval([80.0, 90.0, 100.0], [100.0, 100.0, 100.0], samples=500)
    assert first == second
    assert first["estimate_pct"] == 10.0
    assert first["paired_windows"] == 3


def test_algorithm_and_observation_contracts_match_executable_spaces() -> None:
    continuous = PortEnergyDispatchEnv(split="train", action_mode="continuous", episode_hours=1)
    discrete = PortEnergyDispatchEnv(split="train", action_mode="discrete", episode_hours=1)
    assert continuous.observation_space.shape == (len(OBSERVATION_KEYS),)
    assert len(OBSERVATION_KEYS) == 19
    assert discrete.action_space.n == 81
    assert "81" in ALGORITHM_CATALOG["dqn"]["description"]
    assert MPCPolicy().horizon == 4
    assert len(MPCPolicy().candidates()) == 27
    assert "Four-step" in ALGORITHM_CATALOG["mpc"]["description"]


def test_static_comparator_is_selected_on_validation_only() -> None:
    selection = select_validation_static_reference(
        "port_la_2020_2025_hourly",
        episode_hours=24,
        reward_weights={
            "carbon": 0.22,
            "shore_power": 0.08,
            "cost": 0.22,
            "delay": 0.15,
            "safety": 0.15,
            "peak": 0.10,
            "storage": 0.08,
        },
    )
    assert selection["selection_split"] == "validation"
    assert selection["candidate_count"] == 9
    assert selection["selected"]["controls"] == {
        "shore_power_ratio": 1.0,
        "crane_ratio": 0.8,
        "yard_ratio": 0.8,
        "battery_power_ratio": 0.0,
    }


def test_public_dataset_has_required_train_validation_test_boundary() -> None:
    dataset = PortDataset.load("port_la_2020_2025_hourly")
    assert len(dataset.frame) == 52_608
    assert len(dataset.split("train")) == 35_064
    assert len(dataset.split("validation")) == 8_784
    assert len(dataset.split("test")) == 8_760
    assert dataset.split("train").iloc[0]["timestamp_utc"] == "2020-01-01T00:00:00Z"
    assert dataset.split("validation").iloc[0]["timestamp_utc"] == "2024-01-01T00:00:00Z"
    assert dataset.split("test").iloc[-1]["timestamp_utc"] == "2025-12-31T23:00:00Z"
    assert dataset.frame["electricity_price_per_kwh"].nunique() > 200
    assert dataset.frame["grid_carbon_kg_per_kwh"].nunique() > 1_000
    assert dataset.metadata["public_source_evidence"]["eia930_responses"][0]["coverage"] > 0.98
    assert dataset.metadata["quality"]["duplicate_timestamps"] == 0

    env = PortEnergyDispatchEnv(split="test", episode_hours=1, render_mode=None)
    first, _ = env.reset(seed=1, options={"row_index": 0})
    second, _ = env.reset(seed=1, options={"row_index": 1})
    assert first[3] != second[3]
    assert 0.0 < first[3] < 1.0
    assert 0.0 < first[4] < 1.0


def test_vessel_activity_dataset_extends_observation_without_changing_actions() -> None:
    dataset_id = "port_la_2020_2024_vessel_activity_hourly"
    dataset = PortDataset.load(dataset_id)
    assert dataset.environment_id == "PortEnergyDispatchEnv-v2"
    assert len(dataset.frame) == 43_848
    assert len(dataset.split("train")) == 26_304
    assert len(dataset.split("validation")) == 8_760
    assert len(dataset.split("test")) == 8_784
    assert dataset.metadata["public_source_evidence"]["vessel_activity_daily_rows"] == 1_238
    assert dataset.metadata["public_source_evidence"][
        "vessel_activity_reported_day_coverage"
    ] == pytest.approx(0.677243)
    assert dataset.operational_feature_coverage()["status"] == "pass"

    continuous = PortEnergyDispatchEnv(
        dataset=dataset_id,
        split="test",
        action_mode="continuous",
        episode_hours=1,
    )
    discrete = PortEnergyDispatchEnv(
        dataset=dataset_id,
        split="test",
        action_mode="discrete",
        episode_hours=1,
    )
    observation, info = continuous.reset(seed=11, options={"row_index": 0})
    assert continuous.observation_space.shape == (
        len(OBSERVATION_KEYS) + len(OPERATIONAL_OBSERVATION_KEYS),
    )
    assert len(observation) == 25
    assert info["environment_id"] == "PortEnergyDispatchEnv-v2"
    assert discrete.action_space.n == 81

    readiness = assess_dataset_landing_readiness(dataset)
    assert readiness["row_volume"] == 43_848
    assert readiness["independent_operational_anchors"] == 1_238
    assert readiness["modeled_rows_per_operational_anchor"] == pytest.approx(35.418)
    assert readiness["offline_research_ready"] is True
    assert readiness["production_training_ready"] is False
    assert readiness["landing_grade"] == "D"
    assert "missing_live_deployment_observations" in readiness["blockers"]


def test_vessel_activity_controls_aggregate_shore_power_opportunity() -> None:
    dataset_id = "port_la_2020_2024_vessel_activity_hourly"
    dataset = PortDataset.load(dataset_id)
    test = dataset.split("test")
    row_index = int(test["vessels_at_berth"].idxmin())
    expected_kw = min(
        float(dataset.metadata["environment_parameters"]["shore_demand_kw"]),
        float(test.iloc[row_index]["vessels_at_berth"])
        * float(dataset.metadata["environment_parameters"]["vessel_auxiliary_demand_kw"]),
    )
    env = PortEnergyDispatchEnv(
        dataset=dataset_id,
        split="test",
        episode_hours=1,
    )
    env.reset(seed=11, options={"row_index": row_index})
    action = encode_continuous_controls(
        {
            "shore_power_ratio": 1.0,
            "crane_ratio": 1.0,
            "yard_ratio": 1.0,
            "battery_power_ratio": 0.0,
        }
    )
    _, _, _, _, info = env.step(action)
    assert info["shore_power_opportunity_kwh"] == pytest.approx(expected_kw)
    assert info["shore_power_kwh"] == pytest.approx(expected_kw)


def test_v4_regulatory_contract_is_additive_and_authority_release_is_exogenous() -> None:
    dataset_id = "port_la_2024_regulatory_resilience_hourly"
    dataset = PortDataset.load(dataset_id)
    assert dataset.environment_id == "PortEnergyDispatchEnv-v4"
    assert len(dataset.frame) == 8_784
    assert dataset.metadata["safety_boundary"] == {
        "simulation_mode": True,
        "live_data_verified": False,
        "dispatch_allowed": False,
        "production_authority": False,
    }
    env = PortEnergyDispatchEnv(
        dataset=dataset_id,
        split="train",
        action_mode="continuous",
        episode_hours=2,
    )
    observation, info = env.reset(seed=17, options={"row_index": 0})
    assert len(observation) == 35 + len(REGULATORY_OBSERVATION_KEYS) == 48
    assert env.action_space.shape == (6,)
    assert info["environment_id"] == "PortEnergyDispatchEnv-v4"
    discrete = PortEnergyDispatchEnv(
        dataset=dataset_id,
        split="train",
        action_mode="discrete",
        episode_hours=1,
    )
    assert discrete.action_space.n == 729

    action = encode_continuous_controls(
        {
            "shore_power_ratio": 1.0,
            "crane_ratio": 1.0,
            "yard_ratio": 1.0,
            "battery_power_ratio": 0.0,
            "inspection_readiness_ratio": 1.0,
            "recovery_priority_ratio": 1.0,
        }
    )
    _, _, _, _, first = env.step(action)
    assert first["maritime_released_teu"] == pytest.approx(
        first["maritime_inspection_arrivals_teu"]
        * float(dataset.split("train").iloc[0]["maritime_release_ratio"])
    )
    assert first["customs_released_teu"] == pytest.approx(
        first["customs_inspection_arrivals_teu"]
        * float(dataset.split("train").iloc[0]["customs_release_ratio"])
    )
    assert first["controls"]["inspection_readiness_ratio"] == 1.0
    assert first["controls"]["recovery_priority_ratio"] == 1.0


def test_v5_flexible_business_contract_is_additive_replaceable_and_hard_projected() -> None:
    dataset_id = "port_la_2020_2024_operational_flex_hourly"
    dataset = PortDataset.load(dataset_id)
    assert dataset.environment_id == "PortEnergyDispatchEnv-v5"
    assert len(dataset.frame) == 43_848
    assert dataset.metadata["field_provenance"]["independent_field_measurement_columns"] == []
    assert dataset.metadata["real_world_substitution_contract"]["calibration_required"] is True
    assert dataset.metadata["safety_boundary"]["production_authority"] is False
    assert dataset.operational_feature_coverage()["status"] == "pass"

    continuous = PortEnergyDispatchEnv(
        dataset=dataset_id,
        split="train",
        action_mode="continuous",
        episode_hours=24,
    )
    observation, info = continuous.reset(seed=23, options={"row_index": 0})
    assert len(observation) == 48 + len(FLEXIBLE_OPERATIONS_OBSERVATION_KEYS) == 73
    assert continuous.action_space.shape == (10,)
    assert info["environment_id"] == "PortEnergyDispatchEnv-v5"
    for _ in range(24):
        _, _, terminated, _, _ = continuous.step([-1.0] * 10)
        if terminated:
            break
    low_service_summary = continuous.summary()
    assert low_service_summary["agv_missed_required_kwh"] == 0
    assert low_service_summary["reefer_thermal_violation_steps"] == 0
    assert low_service_summary["flexible_load_projection_kwh"] > 0

    discrete = PortEnergyDispatchEnv(
        dataset=dataset_id,
        split="train",
        action_mode="discrete",
        episode_hours=24,
    )
    assert discrete.action_space.n == 243
    discrete.reset(seed=23, options={"row_index": 0})
    # Maximum shore/equipment/storage template crosses the declared derating
    # interval. The action shield must preserve grid, SOC, AGV-departure and
    # refrigerated-container hard constraints.
    for _ in range(24):
        _, _, terminated, _, _ = discrete.step(242)
        if terminated:
            break
    summary = discrete.summary()
    assert summary["peak_violation_steps"] == 0
    assert summary["soc_violation_steps"] == 0
    assert summary["agv_missed_required_kwh"] == 0
    assert summary["reefer_thermal_violation_steps"] == 0
    assert summary["flexible_load_projection_kwh"] > 0

    config = TrainingService().validate_config(
        {
            "algorithm": "sac",
            "dataset_id": dataset_id,
            "total_steps": 32,
            "episode_hours": 24,
        }
    )
    assert config["observation_count"] == 73
    assert config["action_contract"]["continuous"] == 10
    assert config["action_contract"]["dqn_discrete_combinations"] == 243

    replacement = assess_site_replacement_readiness(dataset)
    assert replacement["offline_schema_compatible"] is True
    assert replacement["site_training_ready"] is False
    assert len(replacement["required_measurement_columns"]) == 50
    assert replacement["modeled_or_unverified_columns"]
    assert replacement["missing_environment_parameters"] == []
    assert len(replacement["uncalibrated_environment_parameters"]) == 38
    assert "all_required_columns_independently_measured" in replacement["blockers"]
    assert replacement["production_boundary"]["production_authority"] is False


def test_v6_hybrid_residual_contract_is_additive_causal_and_replaceable() -> None:
    dataset_id = "port_la_2020_2024_hybrid_rl_hourly"
    dataset = PortDataset.load(dataset_id)
    assert dataset.environment_id == "PortEnergyHybridResidualEnv-v6"
    assert len(dataset.frame) == 43_848
    assert len(dataset.frame.columns) == 79
    assert dataset.metadata["field_provenance"]["independent_field_measurement_columns"] == []
    assert dataset.operational_feature_coverage()["status"] == "pass"

    env = CausalForecastPortEnv(
        dataset=dataset_id,
        split="train",
        action_mode="continuous",
        episode_hours=24,
    )
    observation, info = env.reset(seed=29, options={"row_index": 0})
    assert len(observation) == 73 + len(HYBRID_OBSERVATION_KEYS) == 106
    assert env.action_space.shape == (16,)
    assert info["environment_id"] == "PortEnergyHybridResidualEnv-v6"
    assert len(env.reward_weights) == len(DEFAULT_HYBRID_REWARD_WEIGHTS) == 17
    assert env.reward_weights["storage"] == 0.0
    for _ in range(24):
        _, _, terminated, _, _ = env.step([0.0] * 16)
        if terminated:
            break
    summary = env.summary()
    assert summary["hybrid_solver_constraint_violations"] == 0
    assert summary["safety_violations"] == 0
    assert summary["crane_task_late_teu"] >= 0
    assert summary["truck_queue_teu_hours"] >= 0

    config = TrainingService().validate_config(
        {"algorithm": "ppo", "dataset_id": dataset_id, "total_steps": 32}
    )
    assert config["observation_count"] == 106
    assert config["action_contract"]["continuous"] == 16
    assert config["action_contract"]["dqn_discrete_combinations"] is None
    with pytest.raises(ValueError, match="continuous-only"):
        TrainingService().validate_config(
            {"algorithm": "dqn", "dataset_id": dataset_id, "total_steps": 32}
        )

    scope = hybrid_business_scope_contract()
    assert scope["decision_counts"] == {
        "rl_or_hybrid_strategy": 16,
        "pure_control_or_physics": 1,
        "deterministic_governance_authority_or_safety": 10,
    }
    replacement = assess_site_replacement_readiness(dataset)
    assert replacement["offline_schema_compatible"] is True
    assert replacement["site_training_ready"] is False
    assert len(replacement["required_measurement_columns"]) == 66
    assert len(replacement["blockers"]) == 13


def test_additive_reward_terms_do_not_break_legacy_custom_weight_profiles() -> None:
    env = PortEnergyDispatchEnv(
        dataset="port_la_2020_2024_vessel_activity_hourly",
        split="test",
        action_mode="continuous",
        reward_weights={
            "carbon": 0.25,
            "shore_power": 0.10,
            "cost": 0.25,
            "delay": 0.15,
            "safety": 0.15,
            "peak": 0.10,
        },
        episode_hours=2,
    )
    env.reset(seed=7, options={"row_index": 0})


def test_v5_training_accepts_all_business_reward_terms() -> None:
    weights = {
        "carbon": 0.15,
        "shore_power": 0.06,
        "cost": 0.15,
        "delay": 0.12,
        "safety": 0.18,
        "peak": 0.08,
        "storage": 0.05,
        "agv_service": 0.06,
        "reefer_safety": 0.07,
        "demand_response": 0.05,
        "equipment_health": 0.03,
    }
    config = TrainingService().validate_config(
        {
            "algorithm": "ppo",
            "dataset_id": "port_la_2020_2024_operational_flex_hourly",
            "total_steps": 32,
            "reward_weights": weights,
        }
    )
    env = PortEnergyDispatchEnv(
        dataset=config["dataset_id"],
        split="train",
        action_mode="continuous",
        reward_weights=config["reward_weights"],
        episode_hours=1,
    )

    assert set(env.reward_weights) == set(weights)
    assert sum(env.reward_weights.values()) == pytest.approx(1.0)
    env.reset(seed=7, options={"row_index": 0})
    _, reward, _, _, info = env.step([0.0] * 10)
    assert isinstance(reward, float)
    assert {"agv_service", "reefer_safety", "demand_response", "equipment_health"} <= set(
        info["reward_terms"]
    )


def test_live_port_contract_is_fail_closed_and_v3_affects_dispatch(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(dataset_module, "DATASET_DIR", tmp_path)
    csv_path = tmp_path / "live_port.csv"
    columns = [
        "period",
        "split",
        "loaded_import_teu",
        "loaded_export_teu",
        "total_teu",
        "grid_carbon_kg_per_kwh",
        "electricity_price_per_kwh",
        "fuel_price_per_liter",
        "source_id",
        "observation_hours",
        "crane_capacity_teu_per_hour",
        "yard_capacity_teu_per_hour",
        "shore_demand_kw",
        "base_load_kw",
        "load_kw_per_teu",
        "crane_load_kw",
        "yard_load_kw",
        "grid_capacity_kw",
        *OPERATIONAL_OBSERVATION_KEYS,
        *DEPLOYMENT_OBSERVATION_KEYS,
    ]
    rows = []
    for index in range(6):
        split = "train" if index < 2 else "validation" if index < 4 else "test"
        rows.append(
            [
                f"2026-01-01T{index:02d}:00:00Z",
                split,
                60,
                40,
                100,
                0.2,
                0.5,
                8.0,
                "terminal_approved",
                1,
                100,
                100,
                50,
                100,
                1,
                10,
                20,
                5_000,
                1,
                2,
                1,
                1,
                2,
                1,
                5,
                1,
                10,
                0,
                0.5,
                0.5,
                0.5,
                0.5,
                0.5,
                20,
            ]
        )
    csv_path.write_text(
        ",".join(columns)
        + "\n"
        + "\n".join(",".join(str(value) for value in row) for row in rows)
        + "\n",
        encoding="utf-8",
    )
    csv_path.with_suffix(".metadata.json").write_text(
        json.dumps(
            {
                "id": "live_port",
                "temporal_mode": "sequential_rows",
                "time_column": "period",
                "environment_id": "PortEnergyDispatchEnv-v3",
            }
        ),
        encoding="utf-8",
    )
    env = PortEnergyDispatchEnv(
        dataset=str(csv_path),
        split="test",
        episode_hours=1,
    )
    observation, _ = env.reset(seed=1, options={"row_index": 0})
    assert len(observation) == 35
    action = encode_continuous_controls(
        {
            "shore_power_ratio": 1.0,
            "crane_ratio": 1.0,
            "yard_ratio": 1.0,
            "battery_power_ratio": 0.0,
        }
    )
    _, _, _, _, info = env.step(action)
    assert info["processed_teu"] == pytest.approx(25.0)
    assert info["shore_power_opportunity_kwh"] == pytest.approx(25.0)
    assert info["renewable_energy_kwh"] == pytest.approx(20.0)

    contract = deployment_contract()
    assert contract["environment_id"] == "PortEnergyDispatchEnv-v3"
    templates = {
        item["id"]: item for item in scenario_items() if item["mode"] == "live_port_template"
    }
    assert templates
    assert all(not item["readiness"]["production_ready"] for item in templates.values())
    assert all(item["readiness"]["missing_adapters"] for item in templates.values())


def test_hyperparameter_search_contract_keeps_test_out_of_selection() -> None:
    search = load_search_space()
    protocol = search["selection_protocol"]
    assert protocol["fit_split"] == "train"
    assert protocol["selection_split"] == "validation"
    assert protocol["final_report_split"] == "test"
    assert set(search["algorithms"]) == {"ppo", "sac", "td3", "dqn"}


def test_sequential_port_dataset_overrides_physical_model_without_code_changes(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(dataset_module, "DATASET_DIR", tmp_path)
    csv_path = tmp_path / "terminal_hourly.csv"
    header = (
        "period,split,loaded_import_teu,loaded_export_teu,total_teu,"
        "grid_carbon_kg_per_kwh,electricity_price_per_kwh,fuel_price_per_liter,source_id,"
        "observation_hours,crane_capacity_teu_per_hour,yard_capacity_teu_per_hour,"
        "shore_demand_kw,base_load_kw,load_kw_per_teu,crane_load_kw,yard_load_kw,"
        "grid_capacity_kw,fuel_kwh_per_liter,fuel_carbon_kg_per_liter,"
        "delay_cost_cny_per_minute,delay_limit_minutes\n"
    )
    rows = []
    for index in range(8):
        split = "train" if index < 4 else "validation" if index < 6 else "test"
        base_load = 100 + index * 100
        rows.append(
            f"2026-01-01T{index:02d}:00:00Z,{split},60,40,100,0.2,0.5,8.0,terminal_meter,"
            f"1,1000,1000,50,{base_load},1,10,20,5000,4,2.5,3,30"
        )
    csv_path.write_text(header + "\n".join(rows) + "\n", encoding="utf-8")
    csv_path.with_suffix(".metadata.json").write_text(
        json.dumps(
            {
                "id": "terminal_hourly",
                "temporal_mode": "sequential_rows",
                "time_column": "period",
            }
        ),
        encoding="utf-8",
    )

    dataset = PortDataset.load(csv_path)
    assert dataset.evaluation_start_indices("train", 3) == [0]
    env = PortEnergyDispatchEnv(
        dataset=str(csv_path), split="train", episode_hours=4, render_mode="trajectory"
    )
    env.reset(seed=1, options={"row_index": 0})
    action = encode_continuous_controls(
        {
            "shore_power_ratio": 0.0,
            "crane_ratio": 1.0,
            "yard_ratio": 1.0,
            "battery_power_kw": 0.0,
        }
    )
    _, _, _, _, first = env.step(action)
    _, _, _, _, second = env.step(action)

    assert first["period"] == "2026-01-01T00:00:00Z"
    assert second["period"] == "2026-01-01T01:00:00Z"
    assert first["processed_teu"] == pytest.approx(100.0)
    assert first["load_kw"] == pytest.approx(230.0)
    assert second["load_kw"] == pytest.approx(330.0)


def test_dataset_cache_invalidates_when_package_changes(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(dataset_module, "DATASET_DIR", tmp_path)
    csv_path = tmp_path / "cache_check.csv"
    rows = [
        (
            "period,split,loaded_import_teu,loaded_export_teu,total_teu,"
            "grid_carbon_kg_per_kwh,electricity_price_per_kwh,"
            "fuel_price_per_liter,source_id"
        ),
        "2026-01,train,1,1,2,0.2,0.5,8,source-a",
        "2026-02,validation,1,1,2,0.2,0.5,8,source-a",
        "2026-03,test,1,1,2,0.2,0.5,8,source-a",
    ]
    csv_path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    first = PortDataset.load(csv_path)
    rows[-1] = "2026-03,test,2,1,3,0.2,0.5,8,source-b"
    csv_path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    second = PortDataset.load(csv_path)
    assert second.sha256 != first.sha256
    assert second.frame.iloc[-1]["total_teu"] == pytest.approx(3.0)


def test_training_history_skips_newer_control_run_without_callback_metrics(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(training_module, "RUNS_DIR", tmp_path)
    runs = (
        ("rl-20260825-143526-aaaaaa", "ppo", True),
        ("rl-20260825-143527-bbbbbb", "mpc", False),
    )
    for run_id, algorithm, has_metrics in runs:
        run_dir = tmp_path / run_id
        run_dir.mkdir()
        artifact = run_dir / ("model.zip" if algorithm == "ppo" else "mpc_policy.json")
        artifact.write_text("evidence", encoding="utf-8")
        manifest = {
            "job_id": run_id,
            "policy_version": f"{algorithm}-{run_id}",
            "status": "completed",
            "step": 32 if has_metrics else 0,
            "started_at": "2026-08-25T06:00:00Z",
            "completed_at": "2026-08-25T06:01:00Z",
            "duration_sec": 60,
            "run_dir": str(run_dir),
            "artifact_path": str(artifact),
            "artifact_sha256": "recorded",
            "config": {
                "algorithm": algorithm,
                "objective_id": "carbon_min",
                "dataset_id": "test_dataset",
                "dataset_sha256": "dataset-sha",
                "data_file": "test_dataset",
                "environment_id": "PortEnergyDispatchEnv-v2",
                "seed": 7,
            },
        }
        (run_dir / "manifest.json").write_text(
            json.dumps(manifest), encoding="utf-8"
        )
        if has_metrics:
            (run_dir / "metrics.jsonl").write_text(
                json.dumps({"step": 32, "reward": 1.25, "episode_complete": True})
                + "\n",
                encoding="utf-8",
            )

    history = TrainingService().history()
    assert history["run_id"] == "rl-20260825-143526-aaaaaa"
    assert history["algorithm"] == "PPO"
    assert history["series"][0]["reward"] == pytest.approx(1.25)


def test_auto_strategy_selection_skips_smoke_and_blocked_runs(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(policy_selection, "RUNS_DIR", tmp_path)
    for run_id, steps, verification_status in (
        ("rl-20260725-120000-substantial", 100_000, "verified"),
        ("rl-20260726-001000-smoke", 32, "verified"),
        ("rl-20260727-001000-blocked", 100_000, "blocked"),
    ):
        run_dir = tmp_path / run_id
        run_dir.mkdir()
        (run_dir / "manifest.json").write_text(
            json.dumps(
                {
                    "job_id": run_id,
                    "status": "completed",
                    "step": steps,
                    "artifact_path": str(run_dir / "model.zip"),
                    "artifact_sha256": "recorded",
                }
            ),
            encoding="utf-8",
        )
        (run_dir / "verification.json").write_text(
            json.dumps({"status": verification_status}), encoding="utf-8"
        )

    assert policy_selection.resolve_requested_strategy("auto:latest") == (
        "rl-20260725-120000-substantial"
    )
    assert policy_selection.resolve_requested_strategy("explicit-policy") == (
        "explicit-policy"
    )


def test_auto_strategy_selection_fails_closed_without_verified_policy(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(policy_selection, "RUNS_DIR", tmp_path)
    run_dir = tmp_path / "rl-20260727-001000-blocked"
    run_dir.mkdir()
    (run_dir / "manifest.json").write_text(
        json.dumps(
            {
                "job_id": run_dir.name,
                "status": "completed",
                "step": 100_000,
                "artifact_path": str(run_dir / "model.zip"),
                "artifact_sha256": "recorded",
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "verification.json").write_text(
        json.dumps({"status": "blocked"}), encoding="utf-8"
    )

    assert policy_selection.resolve_requested_strategy("auto:latest") == (
        "auto:no-admitted-policy"
    )


def test_dashboard_admission_rejects_safe_but_underperforming_policy() -> None:
    metrics = {
        "test_steps": 1_152,
        "safety_violations": 0,
        "constraint_success_rate_pct": 100.0,
        "carbon_reduction_pct": -9.806,
        "cost_saving_pct": -10.293,
        "fixed_baseline_carbon_reduction_pct": -0.029,
        "fixed_baseline_cost_saving_pct": -1.232,
        "fixed_baseline_throughput_change_pct": 0.0,
    }
    rejected = {"split": "test", "metrics": metrics}
    admitted = {
        "split": "test",
        "metrics": {
            **metrics,
            "carbon_reduction_pct": 1.0,
            "cost_saving_pct": 1.0,
            "fixed_baseline_carbon_reduction_pct": 1.0,
            "fixed_baseline_cost_saving_pct": 1.0,
        },
    }

    assert not DispatchSimulator._dashboard_policy_admitted(rejected)
    assert DispatchSimulator._dashboard_policy_admitted(admitted)


@pytest.mark.parametrize("algorithm", ["ppo", "sac", "td3", "dqn"])
@pytest.mark.skipif(
    not SB3_AVAILABLE,
    reason="neural RL runtime is unavailable on unsupported Intel macOS hosts",
)
def test_each_rl_algorithm_executes_real_learner_steps(
    tmp_path, monkeypatch, algorithm: str
) -> None:
    run_root = tmp_path / algorithm
    run_root.mkdir()
    monkeypatch.setattr(training_module, "RUNS_DIR", run_root)
    service = TrainingService()
    started = service.start(
        {
            "algorithm": algorithm,
            "dataset_id": "port_la_2020_2025_monthly",
            "total_steps": 32,
            "episode_hours": 4,
            "eval_interval": 16,
            "checkpoint_interval": 16,
            "seed": 11,
        }
    )
    deadline = time.monotonic() + 30
    status = started
    while status["status"] in {"running", "paused", "stopping"} and time.monotonic() < deadline:
        time.sleep(0.05)
        status = service.status()

    assert status["status"] == "completed", status.get("error")
    assert status["step"] >= 32
    assert status["progress"] == 100.0
    assert status["artifact_path"].endswith("model.zip")
    history = service.history()
    assert history["series"]
    assert history["checkpoints"]
    assert all(
        point.get("validation_rendering") is False
        for point in history["series"]
        if "validation_rendering" in point
    )
