"""Compatibility adapter for the dataset-backed Gymnasium environment.

New code should import :class:`app.rl.environment.PortEnergyDispatchEnv`
directly.  This adapter exists for API clients that prefer JSON-compatible
reset/step packets.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from app.rl.environment import MPCPolicy, PortEnergyDispatchEnv, encode_continuous_controls


class GymnasiumDispatchAdapter:
    def __init__(self, env: PortEnergyDispatchEnv | None = None) -> None:
        self.env = env or PortEnergyDispatchEnv(
            split="test",
            action_mode="continuous",
            render_mode="trajectory",
        )

    def reset(self, *, seed: int = 20260720, row_index: int = 0) -> dict[str, Any]:
        observation, info = self.env.reset(seed=seed, options={"row_index": row_index, "start_hour": 0})
        return {
            "status": "ready",
            "environment_id": "PortEnergyDispatchEnv-v1",
            "observation": observation.tolist(),
            "info": info,
        }

    def step(self, action: list[float] | np.ndarray | int) -> dict[str, Any]:
        observation, reward, terminated, truncated, info = self.env.step(action)
        return {
            "observation": observation.tolist(),
            "reward": reward,
            "terminated": terminated,
            "truncated": truncated,
            "info": info,
        }

    def run_mpc_episode(self, *, seed: int = 20260720, row_index: int = 0) -> dict[str, Any]:
        observation, info = self.env.reset(seed=seed, options={"row_index": row_index, "start_hour": 0})
        controller = MPCPolicy()
        terminated = truncated = False
        rewards: list[float] = []
        while not (terminated or truncated):
            action = encode_continuous_controls(controller.predict(self.env))
            observation, reward, terminated, truncated, _ = self.env.step(action)
            rewards.append(float(reward))
        return {
            "status": "tested",
            "environment_id": "PortEnergyDispatchEnv-v1",
            "dataset_id": info["dataset_id"],
            "dataset_sha256": info["dataset_sha256"],
            "split": info["split"],
            "episode_steps": len(rewards),
            "terminated": terminated,
            "truncated": truncated,
            "total_reward": sum(rewards),
            "trajectory": self.env.render(),
            "summary": self.env.summary(),
        }
