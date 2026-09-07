from __future__ import annotations

import copy
import json

import numpy as np
import pytest

from app.rl.dispatch_policy_v7 import (
    DATASET_ID, SHAPE, CachedCausalEnv, DispatchEnvV7, DispatchPolicyV7, features,
)
from app.rl.robust import CausalForecastPortEnv
from app.rl.dispatch_switch_v7 import DispatchSwitcherV7
from app.rl.environment import MPCPolicy
from app.rl.evaluate_guarded_dispatch_v7 import MemoMPC
from app.rl.guarded_dispatch_v7 import GuardedDispatchPolicyV7


@pytest.fixture(scope="module")
def env():
    return DispatchEnvV7(dataset=DATASET_ID, split="validation")


def test_cache_preserves_causal_physics_and_observations():
    original = CausalForecastPortEnv(dataset=DATASET_ID, split="validation")
    cached = CachedCausalEnv(dataset=DATASET_ID, split="validation")
    for start in (0, 5208):
        a, _ = original.reset(seed=7, options={"row_index": start})
        b, _ = cached.reset(seed=7, options={"row_index": start})
        np.testing.assert_array_equal(a, b)
        for _ in range(24):
            action = np.linspace(-0.7, 0.8, 16).astype(np.float32)
            left = original.step(action)
            right = cached.step(action)
            np.testing.assert_array_equal(left[0], right[0])
            assert left[1:] == right[1:]


def test_roundoff_is_not_a_grid_violation(env):
    env.reset(seed=7, options={"row_index": 5208})
    policy = DispatchPolicyV7()
    for _ in range(18):
        _, _, _, _, info = env.step(policy.predict(env))
    assert 0 < info["numerical_peak_roundoff_kw"] < 1e-9
    assert info["safety_violations"] == 0
    assert info["peak_violation_steps"] == 0


def test_real_grid_excess_is_not_suppressed(env, monkeypatch):
    env.reset(seed=7, options={"row_index": 5208})
    transition = env.preview_transition(DispatchPolicyV7().predict(env))
    transition.update(peak_violation_kw=0.001, safety_violations=1.0, peak_violation_steps=1.0)
    monkeypatch.setattr(CachedCausalEnv, "_calculate_transition", lambda *args: copy.deepcopy(transition))
    result = env.preview_transition({})
    assert result["safety_violations"] == 1
    assert result["peak_violation_steps"] == 1


def test_policy_cannot_reduce_service_commitments(env):
    env.reset(seed=7, options={"row_index": 700})
    policy = DispatchPolicyV7(np.full(SHAPE, -10.0))
    for _ in range(24):
        reference = DispatchPolicyV7().predict(env)
        before = env.preview_transition(reference)
        action = policy.predict(env)
        after = env.preview_transition(action)
        assert action["shore_power_ratio"] == 1
        assert action["demand_response_ratio"] == reference["demand_response_ratio"]
        assert after["processed_teu"] >= before["processed_teu"] - 1e-8
        assert after["delay_minutes"] <= before["delay_minutes"] + 1e-8
        assert after["shore_power_kwh"] >= before["shore_power_kwh"] - 1e-8
        env.step(action)


def test_learner_features_and_planning_never_read_future_rows(env):
    env.reset(seed=7, options={"row_index": 50})
    observation = features(env)
    current = env._row()
    assert env._row_at(3) is current
    env.preview_transition(DispatchPolicyV7().predict(env), hour_offset=3)
    np.testing.assert_array_equal(features(env), observation)


def test_invalid_artifact_is_rejected():
    with pytest.raises(ValueError):
        DispatchPolicyV7(np.zeros((2, 2)))
    with pytest.raises(ValueError):
        DispatchPolicyV7(np.full(SHAPE, np.nan))


def test_battery_energy_is_accounted_from_actual_flow(env):
    rng = np.random.default_rng(31)
    for start in (0, 1700, 5208):
        env.reset(seed=7, options={"row_index": start})
        policy = DispatchPolicyV7(rng.normal(0, 0.5, SHAPE))
        for _ in range(24):
            before = env._battery_soc
            _, _, _, _, info = env.step(policy.predict(env))
            charge = info["battery_charge_kwh"]
            discharge = info["battery_discharge_kwh"]
            expected = before + (
                charge * env._parameter("battery_charge_efficiency")
                - discharge / env._parameter("battery_discharge_efficiency")
            ) / env._parameter("battery_capacity_kwh")
            assert info["battery_soc"] == pytest.approx(expected, abs=1e-10)
            assert max(charge, discharge) <= env._parameter("battery_power_kw") + 1e-8


def test_missing_admission_falls_back_without_resetting_state(env, tmp_path):
    env.reset(seed=7, options={"row_index": 600})
    switcher = DispatchSwitcherV7(env, tmp_path / "missing.json")
    for _ in range(3):
        switcher.step()
    before = env.summary()
    receipt = switcher.switch("learned_v7")
    assert receipt["to"] == "causal_mpc"
    assert receipt["reason"] == "admission_or_integrity_blocked"
    assert receipt["state_preserved"]
    assert before == env.summary()


def test_corrupted_runtime_artifact_reverts_before_next_step(env, tmp_path):
    env.reset(seed=7, options={"row_index": 600})
    switcher = DispatchSwitcherV7(env)
    artifact = tmp_path / "policy.json"
    artifact.write_text(json.dumps({"weights": []}))
    switcher.policy_path = artifact
    switcher.policy_sha = "invalid-digest"
    switcher.mode = "learned_v7"
    result = switcher.step()
    assert result["mode"] == "causal_mpc"
    assert result["hour"] == 1
    assert switcher.switch_receipts[-1]["reason"] == "runtime_artifact_integrity_failure"


def test_mpc_memoization_preserves_predictions_after_state_changes(env):
    env.reset(seed=7, options={"row_index": 600})
    memo = MemoMPC()
    direct = MPCPolicy()
    for _ in range(3):
        cached = memo.predict(env)
        assert cached == direct.predict(env)
        assert memo.predict(env) == cached
        env.step(cached)


def test_guarded_policy_respects_actual_mpc_business_and_inventory(env):
    env.reset(seed=7, options={"row_index": 600})
    policy = GuardedDispatchPolicyV7(np.full(SHAPE, -0.2))
    for _ in range(4):
        reference = env.preview_transition(MPCPolicy().predict(env))
        action = policy.predict(env)
        candidate = env.preview_transition(action)
        for key in ("cost", "carbon_kg", "load_kw", "delay_minutes", "safety_violations"):
            assert candidate[key] <= reference[key] + 1e-8
        for key in ("processed_teu", "shore_power_kwh", "battery_soc"):
            assert candidate[key] >= reference[key] - 1e-8
        env.step(action)
