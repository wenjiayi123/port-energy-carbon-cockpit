from __future__ import annotations

import calendar
from copy import deepcopy
from typing import Any

import gymnasium as gym
from gymnasium import spaces
import numpy as np

from app.rl.dataset import PortDataset


HOURLY_DEMAND_PROFILE = np.array(
    [0.72, 0.66, 0.62, 0.60, 0.64, 0.78, 0.92, 1.08, 1.18, 1.22, 1.17, 1.10,
     1.04, 1.08, 1.16, 1.24, 1.30, 1.25, 1.14, 1.02, 0.94, 0.88, 0.82, 0.76],
    dtype=np.float32,
)
HOURLY_DEMAND_PROFILE /= float(HOURLY_DEMAND_PROFILE.mean())

DEFAULT_REWARD_WEIGHTS = {
    "carbon": 0.28,
    "shore_power": 0.12,
    "cost": 0.20,
    "delay": 0.18,
    "safety": 0.12,
    "peak": 0.10,
}

DEFAULT_ENVIRONMENT_PARAMETERS = {
    "crane_capacity_teu_per_hour": 1_520.0,
    "yard_capacity_teu_per_hour": 1_650.0,
    "shore_demand_kw": 6_800.0,
    "base_load_kw": 2_200.0,
    "load_kw_per_teu": 0.62,
    "crane_load_kw": 2_900.0,
    "yard_load_kw": 1_250.0,
    "grid_capacity_kw": 17_000.0,
    "fuel_kwh_per_liter": 3.8,
    "fuel_carbon_kg_per_liter": 2.68,
    "delay_cost_cny_per_minute": 18.0,
    "delay_limit_minutes": 120.0,
}


class PortEnergyDispatchEnv(gym.Env[np.ndarray, np.ndarray | int]):
    """Dataset-backed port energy dispatch environment.

    Training instances use ``render_mode=None``. Test instances may use
    ``render_mode='trajectory'`` and expose the exact rollout records through
    :meth:`render`, keeping training and visual replay strictly separated.
    """

    metadata = {"render_modes": ["trajectory"], "render_fps": 2}

    def __init__(
        self,
        dataset: str = "port_la_2025_monthly",
        split: str = "train",
        action_mode: str = "continuous",
        reward_weights: dict[str, float] | None = None,
        episode_hours: int = 24,
        render_mode: str | None = None,
    ) -> None:
        super().__init__()
        if action_mode not in {"continuous", "discrete"}:
            raise ValueError("action_mode must be continuous or discrete")
        if render_mode not in {None, "trajectory"}:
            raise ValueError("render_mode must be None during training or trajectory during testing")
        self.dataset = PortDataset.load(dataset)
        self.frame = self.dataset.split(split)
        self.temporal_mode = self.dataset.temporal_mode
        self.split_name = split
        self.action_mode = action_mode
        self.render_mode = render_mode
        self.episode_hours = max(1, min(168, int(episode_hours)))
        self.reward_weights = self._normalize_weights(reward_weights or DEFAULT_REWARD_WEIGHTS)
        self.action_space = (
            spaces.Discrete(27)
            if action_mode == "discrete"
            else spaces.Box(low=-1.0, high=1.0, shape=(3,), dtype=np.float32)
        )
        self.observation_space = spaces.Box(low=0.0, high=1.5, shape=(12,), dtype=np.float32)
        self._row_index = 0
        self._hour = 0
        self._queue_teu = 0.0
        self._trajectory: list[dict[str, Any]] = []
        self._totals: dict[str, float] = {}

    def reset(
        self,
        *,
        seed: int | None = None,
        options: dict[str, Any] | None = None,
    ) -> tuple[np.ndarray, dict[str, Any]]:
        super().reset(seed=seed)
        options = options or {}
        requested_index = options.get("row_index")
        if requested_index is None:
            self._row_index = int(self.np_random.integers(0, len(self.frame)))
        else:
            self._row_index = int(requested_index) % len(self.frame)
        self._hour = int(options.get("start_hour", 0)) % 24
        self._queue_teu = 0.0
        self._trajectory = []
        self._totals = {
            "reward": 0.0,
            "energy_kwh": 0.0,
            "carbon_kg": 0.0,
            "grid_carbon_kg": 0.0,
            "fuel_carbon_kg": 0.0,
            "cost": 0.0,
            "delay_cost_cny": 0.0,
            "delay_minutes": 0.0,
            "processed_teu": 0.0,
            "shore_power_kwh": 0.0,
            "shore_power_opportunity_kwh": 0.0,
            "safety_violations": 0.0,
            "peak_kw": 0.0,
        }
        return self._observation(), {
            "dataset_id": self.dataset.dataset_id,
            "dataset_path": str(self.dataset.csv_path),
            "dataset_sha256": self.dataset.package_sha256,
            "dataset_csv_sha256": self.dataset.sha256,
            "dataset_metadata_sha256": self.dataset.metadata_sha256,
            "split": self.split_name,
            "period": str(self._row()["period"]),
            "source_id": str(self._row()["source_id"]),
            "rendering": self.render_mode is not None,
        }

    def step(self, action: np.ndarray | int) -> tuple[np.ndarray, float, bool, bool, dict[str, Any]]:
        controls = self.decode_action(action)
        transition = self._calculate_transition(controls)
        transition["controls"] = controls
        self._queue_teu = transition["queue_teu"]
        for key in (
            "energy_kwh", "carbon_kg", "grid_carbon_kg", "fuel_carbon_kg",
            "cost", "delay_cost_cny", "delay_minutes", "processed_teu", "shore_power_kwh",
            "shore_power_opportunity_kwh", "safety_violations",
        ):
            self._totals[key] += float(transition[key])
        self._totals["reward"] += float(transition["reward"])
        self._totals["peak_kw"] = max(self._totals["peak_kw"], float(transition["load_kw"]))
        record = self._trajectory_record(transition)
        if self.render_mode == "trajectory":
            self._trajectory.append(record)
        self._hour += 1
        terminated = self._hour >= self.episode_hours
        info = {
            **transition,
            "controls": controls,
            "period": record["period"],
            "trajectory_event": record if self.render_mode == "trajectory" else None,
            "episode": deepcopy(self._totals) if terminated else None,
        }
        return self._observation(), float(transition["reward"]), terminated, False, info

    def render(self) -> list[dict[str, Any]] | None:
        if self.render_mode != "trajectory":
            return None
        return deepcopy(self._trajectory)

    def decode_action(self, action: np.ndarray | int) -> dict[str, float]:
        if self.action_mode == "discrete":
            value = int(action)
            if not self.action_space.contains(value):
                raise ValueError(f"Discrete action out of range: {value}")
            shore_level, crane_level, yard_level = np.unravel_index(value, (3, 3, 3))
            return {
                "shore_power_ratio": (0.0, 0.5, 1.0)[shore_level],
                "crane_ratio": (0.72, 1.0, 1.28)[crane_level],
                "yard_ratio": (0.72, 1.0, 1.28)[yard_level],
            }
        vector = np.asarray(action, dtype=np.float32).reshape(3)
        vector = np.clip(vector, -1.0, 1.0)
        return {
            "shore_power_ratio": float((vector[0] + 1.0) / 2.0),
            "crane_ratio": float(0.70 + (vector[1] + 1.0) * 0.30),
            "yard_ratio": float(0.70 + (vector[2] + 1.0) * 0.30),
        }

    def score_action(self, controls: dict[str, float]) -> float:
        """Return one-step cost without mutating state; used by the MPC baseline."""
        return -float(self._calculate_transition(controls)["reward"])

    def preview_transition(
        self,
        controls: dict[str, float],
        *,
        hour_offset: int = 0,
        queue_teu: float | None = None,
    ) -> dict[str, Any]:
        """Evaluate a future transition while restoring all environment state."""
        original_hour = self._hour
        original_queue = self._queue_teu
        try:
            self._hour = original_hour + int(hour_offset)
            self._queue_teu = original_queue if queue_teu is None else float(queue_teu)
            return self._calculate_transition(controls)
        finally:
            self._hour = original_hour
            self._queue_teu = original_queue

    def summary(self) -> dict[str, Any]:
        return {**deepcopy(self._totals), "steps": self._hour, "period": str(self._row()["period"])}

    def _row(self):
        index = self._row_index
        if self.temporal_mode == "sequential_rows":
            index = (index + self._hour) % len(self.frame)
        return self.frame.iloc[index]

    def _calendar_days(self) -> int:
        period = str(self._row()["period"])
        year, month = (int(part) for part in period.split("-")[:2])
        return calendar.monthrange(year, month)[1]

    def _demand_teu(self) -> float:
        row = self._row()
        period_hours = (
            float(row["observation_hours"])
            if "observation_hours" in row.index and not np.isnan(float(row["observation_hours"]))
            else self._calendar_days() * 24.0
        )
        base_hourly = float(row["total_teu"]) / max(1.0, period_hours)
        if self.temporal_mode == "sequential_rows":
            return base_hourly
        return base_hourly * float(HOURLY_DEMAND_PROFILE[self._hour % 24])

    def _parameter(self, name: str) -> float:
        row = self._row()
        if name in row.index and not np.isnan(float(row[name])):
            return float(row[name])
        configured = self.dataset.metadata.get("environment_parameters") or {}
        return float(configured.get(name, DEFAULT_ENVIRONMENT_PARAMETERS[name]))

    def _observation(self) -> np.ndarray:
        row = self._row()
        demand = self._demand_teu()
        hour_angle = 2 * np.pi * (self._hour % 24) / 24.0
        observation = np.array(
            [
                demand / 1800.0,
                self._queue_teu / 5000.0,
                float(row["grid_carbon_kg_per_kwh"]) / 0.8,
                float(row["electricity_price_per_kwh"]) / 1.0,
                float(row["fuel_price_per_liter"]) / 3.0,
                max(0.0, np.sin(hour_angle)),
                max(0.0, np.cos(hour_angle)),
                (self._hour % 24) / 23.0,
                float(row["loaded_import_teu"]) / max(1.0, float(row["total_teu"])),
                float(row["loaded_export_teu"]) / max(1.0, float(row["total_teu"])),
                self._totals.get("carbon_kg", 0.0) / 100_000.0,
                self._totals.get("delay_minutes", 0.0) / 2_000.0,
            ],
            dtype=np.float32,
        )
        return np.clip(observation, 0.0, 1.5)

    def _calculate_transition(self, controls: dict[str, float]) -> dict[str, Any]:
        row = self._row()
        demand_teu = self._demand_teu() + self._queue_teu
        crane_capacity = self._parameter("crane_capacity_teu_per_hour") * controls["crane_ratio"]
        yard_capacity = self._parameter("yard_capacity_teu_per_hour") * controls["yard_ratio"]
        processed_teu = min(demand_teu, crane_capacity, yard_capacity)
        queue_teu = max(0.0, demand_teu - processed_teu)
        delay_minutes = queue_teu / max(1.0, min(crane_capacity, yard_capacity)) * 60.0

        shore_demand_kw = self._parameter("shore_demand_kw")
        shore_power_kwh = shore_demand_kw * controls["shore_power_ratio"]
        auxiliary_energy_kwh = shore_demand_kw - shore_power_kwh
        auxiliary_fuel_liters = auxiliary_energy_kwh / max(0.001, self._parameter("fuel_kwh_per_liter"))
        base_load_kw = self._parameter("base_load_kw") + processed_teu * self._parameter("load_kw_per_teu")
        crane_load_kw = self._parameter("crane_load_kw") * controls["crane_ratio"]
        yard_load_kw = self._parameter("yard_load_kw") * controls["yard_ratio"]
        load_kw = base_load_kw + crane_load_kw + yard_load_kw + shore_power_kwh
        grid_capacity_kw = self._parameter("grid_capacity_kw")
        peak_violation_kw = max(0.0, load_kw - grid_capacity_kw)
        safety_violations = int(
            peak_violation_kw > 0.0 or delay_minutes > self._parameter("delay_limit_minutes")
        )

        grid_energy_kwh = load_kw
        energy_kwh = grid_energy_kwh + auxiliary_energy_kwh
        grid_carbon_kg = grid_energy_kwh * float(row["grid_carbon_kg_per_kwh"])
        fuel_carbon_kg = auxiliary_fuel_liters * self._parameter("fuel_carbon_kg_per_liter")
        carbon_kg = grid_carbon_kg + fuel_carbon_kg
        delay_cost_cny = delay_minutes * self._parameter("delay_cost_cny_per_minute")
        cost = (
            grid_energy_kwh * float(row["electricity_price_per_kwh"])
            + auxiliary_fuel_liters * float(row["fuel_price_per_liter"])
            + delay_cost_cny
        )
        terms = {
            "carbon": -carbon_kg / 4_500.0,
            "shore_power": controls["shore_power_ratio"],
            "cost": -cost / 6_000.0,
            "delay": -delay_minutes / 90.0,
            "safety": -float(safety_violations) * 4.0,
            "peak": -peak_violation_kw / 3_000.0,
        }
        throughput_bonus = 0.65 * processed_teu / max(1.0, demand_teu)
        reward = throughput_bonus + sum(self.reward_weights[key] * value for key, value in terms.items())
        return {
            "reward": float(reward),
            "reward_terms": {key: float(value) for key, value in terms.items()},
            "demand_teu": float(demand_teu),
            "processed_teu": float(processed_teu),
            "queue_teu": float(queue_teu),
            "delay_minutes": float(delay_minutes),
            "load_kw": float(load_kw),
            "peak_violation_kw": float(peak_violation_kw),
            "shore_power_kwh": float(shore_power_kwh),
            "shore_power_opportunity_kwh": float(shore_demand_kw),
            "shore_power_ratio": float(controls["shore_power_ratio"]),
            "energy_kwh": float(energy_kwh),
            "carbon_kg": float(carbon_kg),
            "grid_carbon_kg": float(grid_carbon_kg),
            "fuel_carbon_kg": float(fuel_carbon_kg),
            "cost": float(cost),
            "delay_cost_cny": float(delay_cost_cny),
            "safety_violations": float(safety_violations),
        }

    def _trajectory_record(self, transition: dict[str, Any]) -> dict[str, Any]:
        controls = transition.get("controls") or {}
        hour = self._hour % 24
        return {
            "step": self._hour + 1,
            "time": f"{hour:02d}:00",
            "event": "dataset_policy_dispatch",
            "period": str(self._row()["period"]),
            "source_id": str(self._row()["source_id"]),
            "vessel_id": f"PUBLIC-DATA-{str(self._row()['period'])}",
            "berth_id": f"B{(hour % 4) + 1}",
            "crane_count": max(1, round(float(controls.get("crane_ratio", 1.0)) * 4)),
            "yard_truck_count": max(1, round(float(controls.get("yard_ratio", 1.0)) * 12)),
            "shore_power_connected": float(transition["shore_power_ratio"]) >= 0.5,
            "energy_kwh": round(float(transition["energy_kwh"]), 3),
            "carbon_kg": round(float(transition["carbon_kg"]), 3),
            "delay_minutes": round(float(transition["delay_minutes"]), 3),
            "processed_teu": round(float(transition["processed_teu"]), 3),
            "queue_teu": round(float(transition["queue_teu"]), 3),
            "load_kw": round(float(transition["load_kw"]), 3),
            "peak_violation_kw": round(float(transition["peak_violation_kw"]), 3),
            "cost_cny": round(float(transition["cost"]), 3),
            "grid_carbon_kg": round(float(transition["grid_carbon_kg"]), 3),
            "fuel_carbon_kg": round(float(transition["fuel_carbon_kg"]), 3),
            "decision_reason": (
                f"policy action: shore={float(transition['shore_power_ratio']):.2f}, "
                f"load={float(transition['load_kw']):.0f}kW, queue={float(transition['queue_teu']):.1f}TEU"
            ),
        }

    @staticmethod
    def _normalize_weights(weights: dict[str, float]) -> dict[str, float]:
        selected = {key: max(0.0, float(weights.get(key, 0.0))) for key in DEFAULT_REWARD_WEIGHTS}
        total = sum(selected.values())
        if total <= 0:
            raise ValueError("At least one reward weight must be positive")
        return {key: value / total for key, value in selected.items()}


class MPCPolicy:
    """Auditable finite-horizon controller used as the non-RL baseline."""

    _levels = (0.0, 0.5, 1.0)
    _ratios = (0.72, 1.0, 1.28)

    def __init__(self, horizon: int = 3, beam_width: int = 4, discount: float = 0.96) -> None:
        self.horizon = max(1, int(horizon))
        self.beam_width = max(1, int(beam_width))
        self.discount = float(discount)

    def candidates(self) -> list[dict[str, float]]:
        return [
            {"shore_power_ratio": shore, "crane_ratio": crane, "yard_ratio": yard}
            for shore in self._levels
            for crane in self._ratios
            for yard in self._ratios
        ]

    def predict(self, env: PortEnergyDispatchEnv) -> dict[str, float]:
        actions = self.candidates()
        beam: list[tuple[float, float, dict[str, float]]] = []
        for controls in actions:
            transition = env.preview_transition(controls, queue_teu=env._queue_teu)
            beam.append((self._transition_cost(transition), float(transition["queue_teu"]), controls))
        beam = sorted(beam, key=lambda item: item[0])[: self.beam_width]

        for hour_offset in range(1, self.horizon):
            expanded: list[tuple[float, float, dict[str, float]]] = []
            for accumulated_cost, queue_teu, first_controls in beam:
                for controls in actions:
                    transition = env.preview_transition(
                        controls,
                        hour_offset=hour_offset,
                        queue_teu=queue_teu,
                    )
                    expanded.append(
                        (
                            accumulated_cost + self.discount ** hour_offset * self._transition_cost(transition),
                            float(transition["queue_teu"]),
                            first_controls,
                        )
                    )
            beam = sorted(expanded, key=lambda item: item[0])[: self.beam_width]
        return min(beam, key=lambda item: item[0])[2]

    @staticmethod
    def _transition_cost(transition: dict[str, Any]) -> float:
        return -float(transition["reward"]) + 1_000_000.0 * float(transition["safety_violations"])


def encode_continuous_controls(controls: dict[str, float]) -> np.ndarray:
    return np.array(
        [
            controls["shore_power_ratio"] * 2.0 - 1.0,
            (controls["crane_ratio"] - 0.70) / 0.30 - 1.0,
            (controls["yard_ratio"] - 0.70) / 0.30 - 1.0,
        ],
        dtype=np.float32,
    )
