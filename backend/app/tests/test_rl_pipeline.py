from __future__ import annotations

import json
import time

import pytest

import app.rl.training as training_module
from app.rl.dataset import PortDataset
from app.rl.environment import PortEnergyDispatchEnv, encode_continuous_controls
from app.rl.training import TrainingService


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


def test_public_dataset_has_required_train_test_boundary() -> None:
    dataset = PortDataset.load("port_la_2025_monthly")
    assert len(dataset.split("train")) == 9
    assert len(dataset.split("test")) == 3
    assert dataset.sha256 == "2e68b58e6e5bdf5167491dfe538fcdedf08541c197d8901c6683ae7f3e0bda52"


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
    for index in range(6):
        split = "train" if index < 4 else "test"
        base_load = 100 + index * 100
        rows.append(
            f"2026-01-01T{index:02d}:00:00Z,{split},60,40,100,0.2,0.5,8.0,terminal_meter,"
            f"1,1000,1000,50,{base_load},1,10,20,5000,4,2.5,3,30"
        )
    csv_path.write_text(header + "\n".join(rows) + "\n", encoding="utf-8")
    csv_path.with_suffix(".metadata.json").write_text(
        json.dumps({"id": "terminal_hourly", "temporal_mode": "sequential_rows"}),
        encoding="utf-8",
    )

    dataset = PortDataset.load(csv_path)
    assert dataset.evaluation_start_indices("train", 3) == [0, 3]
    env = PortEnergyDispatchEnv(dataset=str(csv_path), split="train", episode_hours=4, render_mode="trajectory")
    env.reset(seed=1, options={"row_index": 0})
    action = encode_continuous_controls({"shore_power_ratio": 0.0, "crane_ratio": 1.0, "yard_ratio": 1.0})
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
            "dataset_id": "port_la_2025_monthly",
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
