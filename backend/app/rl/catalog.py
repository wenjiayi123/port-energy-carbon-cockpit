from __future__ import annotations

from typing import Any


ALGORITHM_CATALOG: dict[str, dict[str, Any]] = {
    "ppo": {
        "id": "ppo",
        "name": "PPO",
        "family": "reinforcement_learning",
        "action_space": "continuous",
        "description": "On-policy clipped policy-gradient baseline for continuous resource allocation.",
        "defaults": {"total_steps": 100_000, "batch_size": 128, "learning_rate": 0.0003, "gamma": 0.99},
    },
    "sac": {
        "id": "sac",
        "name": "SAC",
        "family": "reinforcement_learning",
        "action_space": "continuous",
        "description": "Entropy-regularized off-policy actor-critic for shore-power and equipment ratios.",
        "defaults": {"total_steps": 120_000, "batch_size": 256, "learning_rate": 0.0003, "gamma": 0.99},
    },
    "td3": {
        "id": "td3",
        "name": "TD3",
        "family": "reinforcement_learning",
        "action_space": "continuous",
        "description": "Twin delayed deterministic actor-critic for smooth continuous control.",
        "defaults": {"total_steps": 120_000, "batch_size": 256, "learning_rate": 0.001, "gamma": 0.99},
    },
    "dqn": {
        "id": "dqn",
        "name": "DQN",
        "family": "reinforcement_learning",
        "action_space": "discrete",
        "description": "Value-based baseline over 81 auditable 3×3×3×3 resource-allocation presets.",
        "defaults": {"total_steps": 120_000, "batch_size": 128, "learning_rate": 0.0001, "gamma": 0.99},
    },
    "mpc": {
        "id": "mpc",
        "name": "MPC",
        "family": "control_theory",
        "action_space": "continuous_grid",
        "description": "Four-step finite-horizon model-predictive control with constrained beam search over 27 full-shore-power resource actions.",
        "defaults": {"total_steps": 0, "batch_size": 0, "learning_rate": 0.0, "gamma": 1.0},
    },
}


def algorithm_items() -> list[dict[str, Any]]:
    return list(ALGORITHM_CATALOG.values())
