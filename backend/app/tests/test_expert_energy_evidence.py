from copy import deepcopy
from types import SimpleNamespace

import pandas as pd
import pytest

from app.services.expert_energy_evidence import project_trial


@pytest.fixture
def trial():
    dataset = SimpleNamespace(
        package_sha256="a" * 64,
        metadata={
            "id": "port_la_2020_2025_hourly",
            "temporal_mode": "sequential_rows",
            "time_column": "timestamp_utc",
        },
        frame=pd.DataFrame(
            [
                {
                    "source_id": "r1",
                    "timestamp_utc": "2025-01-01T23:00:00Z",
                    "period": "2025-01",
                    "total_teu": 100.0,
                    "observation_hours": 1.0,
                },
                {
                    "source_id": "r2",
                    "timestamp_utc": "2025-01-02T00:00:00Z",
                    "period": "2025-01",
                    "total_teu": 200.0,
                    "observation_hours": 1.0,
                },
            ]
        ),
    )
    selected = {
        "strategy": "MPC",
        "total_carbon_kg": 50.0,
        "total_cost_cny": 75.0,
        "trajectory": [
            {
                "step": 1,
                "source_id": "r1",
                "period": "2025-01",
                "processed_teu": 90.0,
                "queue_teu": 10.0,
            },
            {
                "step": 2,
                "source_id": "r2",
                "period": "2025-01",
                "processed_teu": 200.0,
                "queue_teu": 10.0,
            },
        ],
    }
    raw = {
        "scenario_id": "port_la_2025_public_benchmark",
        "strategies": [{}, selected],
        "rl_environment": {
            "dataset_sha256": "a" * 64,
            "dataset_id": "port_la_2020_2025_hourly",
            "status": "public_dataset_control_benchmark",
            "environment_id": "PortEnergyDispatchEnv-v1",
            "action_policy": "MPC",
            "episode_steps": 2,
        },
    }
    return raw, dataset


def test_uses_candidate_window_and_conservative_completion_not_runtime(trial):
    raw, dataset = trial
    raw["runtime"] = {"fulfillment_pct": 100}
    result = project_trial(raw, dataset)
    assert result["status"] == "ready"
    assert result["window"]["end_exclusive"] == "2025-01-02T01:00:00+00:00"
    assert result["service_pct"] == pytest.approx(289.999 / 300 * 100)
    assert result["service_pct"] < 97
    assert result["carbon_kg"] == 50


def test_window_identity_same_for_different_policy_outcomes(trial):
    raw, dataset = trial
    other = deepcopy(raw)
    other["strategies"][1]["total_carbon_kg"] = 99
    assert project_trial(raw, dataset)["window_id"] == project_trial(other, dataset)["window_id"]


@pytest.mark.parametrize(
    "defect",
    [
        "hash",
        "missing_row",
        "duplicate_row",
        "noncontiguous",
        "naive_time",
        "wrong_period",
        "bad_balance",
        "negative",
        "nan",
        "bool",
        "aggregate_policy",
        "wrong_length",
        "wrong_step",
        "unknown_site",
        "no_hour_basis",
        "zero_demand",
    ],
)
def test_missing_or_inconsistent_evidence_never_becomes_success(trial, defect):
    raw, ds = trial
    selected = raw["strategies"][1]
    if defect == "hash":
        raw["rl_environment"]["dataset_sha256"] = "b" * 64
    elif defect == "missing_row":
        selected["trajectory"][1]["source_id"] = "absent"
    elif defect == "duplicate_row":
        selected["trajectory"][1]["source_id"] = "r1"
    elif defect == "noncontiguous":
        ds.frame.loc[1, "timestamp_utc"] = "2025-01-03T00:00:00Z"
    elif defect == "naive_time":
        ds.frame.loc[1, "timestamp_utc"] = "2025-01-02T00:00:00"
    elif defect == "wrong_period":
        selected["trajectory"][1]["period"] = "2025-02"
    elif defect == "bad_balance":
        selected["trajectory"][1]["processed_teu"] = 299.0
    elif defect == "negative":
        selected["trajectory"][1]["processed_teu"] = -1.0
    elif defect == "nan":
        selected["trajectory"][1]["processed_teu"] = float("nan")
    elif defect == "bool":
        selected["trajectory"][1]["processed_teu"] = True
    elif defect == "aggregate_policy":
        raw["rl_environment"]["status"] = "trained_policy_test_evidence"
    elif defect == "wrong_length":
        raw["rl_environment"]["episode_steps"] = 3
    elif defect == "wrong_step":
        selected["trajectory"][1]["step"] = 1
    elif defect == "unknown_site":
        raw["rl_environment"]["dataset_id"] = "other"
    elif defect == "no_hour_basis":
        ds.frame = ds.frame.drop(columns="observation_hours")
    elif defect == "zero_demand":
        ds.frame["total_teu"] = 0.0
    # A non-JSON number is rejected before a receipt can be constructed.
    if defect == "nan":
        with pytest.raises(ValueError):
            project_trial(raw, ds)
    else:
        assert project_trial(raw, ds)["status"] == "needs_evidence"
