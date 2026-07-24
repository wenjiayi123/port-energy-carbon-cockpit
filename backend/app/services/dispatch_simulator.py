from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.rl.dataset import PortDataset
from app.rl.environment import (
    MPCPolicy,
    OBSERVATION_KEYS,
    PortEnergyDispatchEnv,
    encode_continuous_controls,
)
from app.rl.training import RUNS_DIR


class DispatchSimulator:
    """Build dashboard snapshots from executable policies and held-out public data."""

    def simulate(self, green_preference: float) -> dict[str, object]:
        evaluation = self._latest_evaluation()
        if evaluation:
            baseline = self._strategy_from_evaluation(evaluation, baseline=True)
            optimized = self._strategy_from_evaluation(evaluation, baseline=False)
            algorithm = str(evaluation["policy"]["algorithm"]).upper()
            reward_trace: list[dict[str, Any]] = []
            status = "trained_policy_test_evidence"
            dataset_id = str(evaluation["policy"]["dataset_id"])
            dataset_path = str(evaluation["policy"]["data_file"])
            dataset_sha256 = str(evaluation["policy"]["dataset_sha256"])
        else:
            weights = self._weights(green_preference)
            weight_items = tuple(sorted(weights.items()))
            baseline_rollout = self._rollout("fixed_rule", weight_items)
            optimized_rollout = self._rollout("mpc", weight_items)
            baseline = self._strategy_from_rollout("Reference:FixedRule", baseline_rollout)
            optimized = self._strategy_from_rollout("MPC", optimized_rollout)
            algorithm = "MPC"
            reward_trace = optimized_rollout["reward_trace"]
            status = "public_dataset_control_benchmark"
            dataset_id = str(optimized_rollout["dataset_id"])
            dataset_path = str(optimized_rollout["dataset_path"])
            dataset_sha256 = str(optimized_rollout["dataset_sha256"])
        return {
            "strategies": [baseline, optimized],
            "rl_environment": {
                "status": status,
                "environment_id": "PortEnergyDispatchEnv-v1",
                "dataset_id": dataset_id,
                "dataset_path": dataset_path,
                "dataset_sha256": dataset_sha256,
                "action_policy": algorithm,
                "episode_steps": len(optimized["trajectory"]),
                "total_reward": round(sum(point["reward"] for point in reward_trace), 6) if reward_trace else 0.0,
                "average_reward": round(sum(point["reward"] for point in reward_trace) / max(1, len(reward_trace)), 6) if reward_trace else 0.0,
                "terminated": True,
                "truncated": False,
                "observation_keys": list(OBSERVATION_KEYS),
                "reward_trace": reward_trace,
            },
        }

    def compare(self, green_preference: float) -> list[dict[str, float | str]]:
        return list(self.simulate(green_preference=green_preference)["strategies"])

    @staticmethod
    @lru_cache(maxsize=64)
    def _rollout(policy: str, weight_items: tuple[tuple[str, float], ...]) -> dict[str, Any]:
        weights = dict(weight_items)
        env = PortEnergyDispatchEnv(
            split="test",
            action_mode="continuous",
            reward_weights=weights,
            episode_hours=24,
            render_mode="trajectory",
        )
        observation, reset_info = env.reset(seed=20260720, options={"row_index": 0, "start_hour": 0})
        del observation
        reward_trace: list[dict[str, Any]] = []
        controller = MPCPolicy()
        terminated = truncated = False
        while not (terminated or truncated):
            if policy == "mpc":
                controls = controller.predict(env)
            else:
                controls = {"shore_power_ratio": 0.25, "crane_ratio": 1.0, "yard_ratio": 1.0}
            _, reward, terminated, truncated, info = env.step(encode_continuous_controls(controls))
            terms = info["reward_terms"]
            reward_trace.append(
                {
                    "step": len(reward_trace) + 1,
                    "reward": round(float(reward), 6),
                    "carbon_penalty": round(float(terms["carbon"]), 6),
                    "delay_penalty": round(float(terms["delay"]), 6),
                    "energy_penalty": round(float(terms["cost"]), 6),
                    "shore_power_bonus": round(float(terms["shore_power"]), 6),
                }
            )
        return {
            "trajectory": env.render() or [],
            "totals": env.summary(),
            "reward_trace": reward_trace,
            "dataset_id": reset_info["dataset_id"],
            "dataset_path": reset_info["dataset_path"],
            "dataset_sha256": reset_info["dataset_sha256"],
        }

    @staticmethod
    def _strategy_from_rollout(name: str, rollout: dict[str, Any]) -> dict[str, Any]:
        totals = rollout["totals"]
        trajectory = rollout["trajectory"]
        shore_rate = totals["shore_power_kwh"] / max(1.0, totals["shore_power_opportunity_kwh"]) * 100.0
        return {
            "strategy": name,
            "total_energy_kwh": round(totals["energy_kwh"], 3),
            "total_carbon_kg": round(totals["carbon_kg"], 3),
            "carbon_intensity_kg_per_teu": round(totals["carbon_kg"] / max(1.0, totals["processed_teu"]), 6),
            "shore_power_usage_rate": round(shore_rate, 3),
            "delay_cost_cny": round(totals["delay_cost_cny"], 3),
            "total_cost_cny": round(totals["cost"], 3),
            "trajectory": trajectory,
        }

    @staticmethod
    def _strategy_from_evaluation(evaluation: dict[str, Any], baseline: bool) -> dict[str, Any]:
        totals = evaluation["control_baseline_totals"] if baseline else evaluation["policy_totals"]
        trajectory = evaluation["baseline_trajectory"] if baseline else evaluation["trajectory"]
        algorithm = str(evaluation["policy"]["algorithm"]).upper()
        shore_opportunity = totals.get("shore_power_opportunity_kwh", 6_800.0 * max(1, len(trajectory)))
        return {
            "strategy": "Control:MPC" if baseline else f"RL:{algorithm}",
            "total_energy_kwh": totals["energy_kwh"],
            "total_carbon_kg": totals["carbon_kg"],
            "carbon_intensity_kg_per_teu": round(totals["carbon_kg"] / max(1.0, totals["processed_teu"]), 6),
            "shore_power_usage_rate": round(
                totals["shore_power_kwh"] / max(1.0, shore_opportunity) * 100.0,
                3,
            ),
            "delay_cost_cny": round(totals.get("delay_cost_cny", totals["delay_minutes"] * 18.0), 3),
            "total_cost_cny": totals["cost"],
            "trajectory": trajectory,
        }

    @staticmethod
    def _latest_evaluation() -> dict[str, Any] | None:
        for path in sorted(RUNS_DIR.glob("*/evaluation.json"), reverse=True):
            try:
                manifest = json.loads((path.parent / "manifest.json").read_text(encoding="utf-8"))
                # Tiny runs are useful dependency smoke tests but must never
                # silently become the dashboard's selected operational policy.
                if int(manifest.get("step") or 0) < 5_000:
                    continue
                config = manifest["config"]
                dataset = PortDataset.load(config["data_file"])
                if dataset.package_sha256 != config.get("dataset_sha256"):
                    continue
                artifact = Path(str(manifest.get("artifact_path") or ""))
                recorded_artifact_sha256 = manifest.get("artifact_sha256")
                if not artifact.is_file() or not recorded_artifact_sha256:
                    continue
                if hashlib.sha256(artifact.read_bytes()).hexdigest() != recorded_artifact_sha256:
                    continue
                evaluation = json.loads(path.read_text(encoding="utf-8"))
                if evaluation.get("policy", {}).get("artifact_sha256") != recorded_artifact_sha256:
                    continue
                return evaluation
            except Exception:
                continue
        return None

    @staticmethod
    def _weights(green_preference: float) -> dict[str, float]:
        preference = min(1.0, max(0.0, float(green_preference)))
        return {
            "carbon": 0.18 + preference * 0.24,
            "shore_power": 0.05 + preference * 0.22,
            "cost": 0.30 - preference * 0.12,
            "delay": 0.25 - preference * 0.10,
            "safety": 0.14,
            "peak": 0.08,
        }
