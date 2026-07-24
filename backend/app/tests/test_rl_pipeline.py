from __future__ import annotations

import json
import time

import pytest

import app.rl.training as training_module
from app.rl.benchmark import select_validation_static_reference
from app.rl.dataset import PortDataset
from app.rl.catalog import ALGORITHM_CATALOG
from app.rl.environment import (
    OBSERVATION_KEYS,
    MPCPolicy,
    PortEnergyDispatchEnv,
    encode_continuous_controls,
)
from app.rl.training import TrainingService
from app.rl.tuning import load_search_space


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


def test_algorithm_and_observation_contracts_match_executable_spaces() -> None:
    continuous = PortEnergyDispatchEnv(
        split="train", action_mode="continuous", episode_hours=1
    )
    discrete = PortEnergyDispatchEnv(
        split="train", action_mode="discrete", episode_hours=1
    )
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


def test_hyperparameter_search_contract_keeps_test_out_of_selection() -> None:
    search = load_search_space()
    protocol = search["selection_protocol"]
    assert protocol["fit_split"] == "train"
    assert protocol["selection_split"] == "validation"
    assert protocol["final_report_split"] == "test"
    assert set(search["algorithms"]) == {"ppo", "sac", "td3", "dqn"}


def test_sequential_port_dataset_overrides_physical_model_without_code_changes(tmp_path) -> None:
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
    env = PortEnergyDispatchEnv(dataset=str(csv_path), split="train", episode_hours=4, render_mode="trajectory")
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


@pytest.mark.parametrize("algorithm", ["ppo", "sac", "td3", "dqn"])
def test_each_rl_algorithm_executes_real_learner_steps(tmp_path, monkeypatch, algorithm: str) -> None:
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
    assert all(point.get("validation_rendering") is False for point in history["series"] if "validation_rendering" in point)
