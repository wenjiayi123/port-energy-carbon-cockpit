from __future__ import annotations

import calendar
from copy import deepcopy
from datetime import datetime
from typing import Any

import gymnasium as gym
from gymnasium import spaces
import numpy as np

from app.rl.dataset import DEFAULT_DATASET_ID, PortDataset


HOURLY_DEMAND_PROFILE = np.array(
    [
        0.72,
        0.66,
        0.62,
        0.60,
        0.64,
        0.78,
        0.92,
        1.08,
        1.18,
        1.22,
        1.17,
        1.10,
        1.04,
        1.08,
        1.16,
        1.24,
        1.30,
        1.25,
        1.14,
        1.02,
        0.94,
        0.88,
        0.82,
        0.76,
    ],
    dtype=np.float32,
)
HOURLY_DEMAND_PROFILE /= float(HOURLY_DEMAND_PROFILE.mean())

DEFAULT_REWARD_WEIGHTS = {
    "carbon": 0.22,
    "shore_power": 0.08,
    "cost": 0.22,
    "delay": 0.15,
    "safety": 0.15,
    "peak": 0.10,
    "storage": 0.08,
}

DEFAULT_ENVIRONMENT_PARAMETERS = {
    "crane_capacity_teu_per_hour": 1_850.0,
    "yard_capacity_teu_per_hour": 2_050.0,
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
    "battery_capacity_kwh": 18_000.0,
    "battery_power_kw": 5_000.0,
    "battery_initial_soc": 0.50,
    "battery_min_soc": 0.10,
    "battery_max_soc": 0.90,
    "battery_charge_efficiency": 0.95,
    "battery_discharge_efficiency": 0.95,
    "battery_degradation_cny_per_kwh": 0.18,
    "terminal_soc_tolerance": 0.05,
    "demand_charge_cny_per_kw": 0.0,
    "vessel_auxiliary_demand_kw": 650.0,
    "shore_power_available_ratio": 1.0,
}

OBSERVATION_KEYS = (
    "current_demand",
    "queue_backlog",
    "three_hour_mean_demand_forecast",
    "current_grid_carbon",
    "three_hour_mean_grid_carbon_forecast",
    "current_electricity_price",
    "three_hour_mean_electricity_price_forecast",
    "fuel_price",
    "grid_headroom_after_episode_peak",
    "battery_soc",
    "previous_battery_action",
    "hour_sin",
    "hour_cos",
    "month_sin",
    "month_cos",
    "loaded_import_share",
    "loaded_export_share",
    "cumulative_carbon",
    "cumulative_delay",
)
OPERATIONAL_OBSERVATION_KEYS = (
    "vessels_at_anchor",
    "vessels_at_berth",
    "vessels_departed",
    "average_days_at_berth",
    "average_days_in_port",
    "port_activity_observed",
)
DEPLOYMENT_OBSERVATION_KEYS = (
    "wind_speed_m_s",
    "wave_height_m",
    "visibility_km",
    "precipitation_mm",
    "berth_available_ratio",
    "crane_available_ratio",
    "yard_available_ratio",
    "grid_available_ratio",
    "shore_power_compatible_ratio",
    "renewable_power_available_kw",
)


def observation_keys_for_environment(environment_id: str) -> tuple[str, ...]:
    if environment_id == "PortEnergyDispatchEnv-v1":
        return OBSERVATION_KEYS
    if environment_id == "PortEnergyDispatchEnv-v2":
        return OBSERVATION_KEYS + OPERATIONAL_OBSERVATION_KEYS
    if environment_id == "PortEnergyDispatchEnv-v3":
        return OBSERVATION_KEYS + OPERATIONAL_OBSERVATION_KEYS + DEPLOYMENT_OBSERVATION_KEYS
    raise ValueError(f"Unsupported environment_id: {environment_id}")


class PortEnergyDispatchEnv(gym.Env[np.ndarray, np.ndarray | int]):
    """Dataset-backed port energy dispatch environment.

    Training instances use ``render_mode=None``. Test instances may use
    ``render_mode='trajectory'`` and expose the exact rollout records through
    :meth:`render`, keeping training and visual replay strictly separated.
    """

    metadata = {"render_modes": ["trajectory"], "render_fps": 2}

    def __init__(
        self,
        dataset: str = DEFAULT_DATASET_ID,
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
            raise ValueError(
                "render_mode must be None during training or trajectory during testing"
            )
        self.dataset = PortDataset.load(dataset)
        self.frame = self.dataset.split(split)
        self.environment_id = self.dataset.environment_id
        self.observation_keys = observation_keys_for_environment(self.environment_id)
        required_observations = (
            set(OPERATIONAL_OBSERVATION_KEYS)
            if self.environment_id == "PortEnergyDispatchEnv-v2"
            else set(OPERATIONAL_OBSERVATION_KEYS + DEPLOYMENT_OBSERVATION_KEYS)
            if self.environment_id == "PortEnergyDispatchEnv-v3"
            else set()
        )
        if required_observations:
            missing_operational = required_observations - set(self.frame.columns)
            if missing_operational:
                raise ValueError(
                    f"{self.environment_id} requires operational columns: "
                    + ", ".join(sorted(missing_operational))
                )
        train_frame = self.dataset.split("train")
        self._operational_normalizers = {
            name: max(1.0, float(train_frame[name].quantile(0.95)))
            for name in OPERATIONAL_OBSERVATION_KEYS + DEPLOYMENT_OBSERVATION_KEYS
            if name in train_frame.columns
        }
        configured_parameters = self.dataset.metadata.get("environment_parameters") or {}
        self._resolved_parameters = {
            name: float(configured_parameters.get(name, default))
            for name, default in DEFAULT_ENVIRONMENT_PARAMETERS.items()
        }
        self._parameter_columns = set(DEFAULT_ENVIRONMENT_PARAMETERS) & set(self.frame.columns)
        self.temporal_mode = self.dataset.temporal_mode
        self.split_name = split
        self.action_mode = action_mode
        self.render_mode = render_mode
        self.episode_hours = max(1, min(744, int(episode_hours)))
        self.reward_weights = self._normalize_weights(reward_weights or DEFAULT_REWARD_WEIGHTS)
        self.action_space = (
            spaces.Discrete(81)
            if action_mode == "discrete"
            else spaces.Box(low=-1.0, high=1.0, shape=(4,), dtype=np.float32)
        )
        self.observation_space = spaces.Box(
            low=0.0,
            high=1.5,
            shape=(len(self.observation_keys),),
            dtype=np.float32,
        )
        self._row_index = 0
        self._hour = 0
        self._queue_teu = 0.0
        self._battery_soc = self._parameter_default("battery_initial_soc")
        self._last_battery_power_ratio = 0.0
        self._episode_start_period = ""
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
        maximum_start = (
            max(1, len(self.frame) - self.episode_hours + 1)
            if self.temporal_mode == "sequential_rows"
            else len(self.frame)
        )
        if requested_index is None:
            self._row_index = int(self.np_random.integers(0, maximum_start))
        else:
            self._row_index = int(requested_index) % maximum_start
        self._hour = int(options.get("start_hour", 0)) % (
            24 if self.temporal_mode != "sequential_rows" else 1
        )
        self._queue_teu = 0.0
        self._battery_soc = float(
            options.get("battery_soc", self._parameter("battery_initial_soc"))
        )
        self._last_battery_power_ratio = 0.0
        self._episode_start_period = str(self._row()["period"])
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
            "peak_violation_steps": 0.0,
            "delay_violation_steps": 0.0,
            "soc_violation_steps": 0.0,
            "battery_charge_kwh": 0.0,
            "battery_discharge_kwh": 0.0,
            "battery_throughput_kwh": 0.0,
            "battery_degradation_cost_cny": 0.0,
            "demand_charge_cost_cny": 0.0,
            "battery_constraint_projection_kwh": 0.0,
            "peak_kw": 0.0,
            "crane_activation_ratio_sum": 0.0,
            "yard_activation_ratio_sum": 0.0,
        }
        return self._observation(), {
            "dataset_id": self.dataset.dataset_id,
            "dataset_path": str(self.dataset.csv_path),
            "dataset_sha256": self.dataset.package_sha256,
            "dataset_csv_sha256": self.dataset.sha256,
            "dataset_metadata_sha256": self.dataset.metadata_sha256,
            "environment_id": self.environment_id,
            "observation_keys": list(self.observation_keys),
            "split": self.split_name,
            "period": str(self._row()["period"]),
            "source_id": str(self._row()["source_id"]),
            "rendering": self.render_mode is not None,
        }

    def step(
        self, action: np.ndarray | int
    ) -> tuple[np.ndarray, float, bool, bool, dict[str, Any]]:
        controls = self.decode_action(action)
        transition = self._calculate_transition(controls)
        transition["controls"] = controls
        self._queue_teu = transition["queue_teu"]
        self._battery_soc = transition["battery_soc"]
        self._last_battery_power_ratio = controls["battery_power_ratio"]
        for key in (
            "energy_kwh",
            "carbon_kg",
            "grid_carbon_kg",
            "fuel_carbon_kg",
            "cost",
            "delay_cost_cny",
            "delay_minutes",
            "processed_teu",
            "shore_power_kwh",
            "shore_power_opportunity_kwh",
            "safety_violations",
            "peak_violation_steps",
            "delay_violation_steps",
            "soc_violation_steps",
            "battery_charge_kwh",
            "battery_discharge_kwh",
            "battery_throughput_kwh",
            "battery_degradation_cost_cny",
            "demand_charge_cost_cny",
            "battery_constraint_projection_kwh",
            "crane_activation_ratio_sum",
            "yard_activation_ratio_sum",
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
            shore_level, crane_level, yard_level, battery_level = np.unravel_index(
                value, (3, 3, 3, 3)
            )
            return {
                "shore_power_ratio": (0.0, 0.5, 1.0)[shore_level],
                "crane_ratio": (0.60, 0.80, 1.00)[crane_level],
                "yard_ratio": (0.60, 0.80, 1.00)[yard_level],
                # Positive discharges to the port load; negative charges.
                "battery_power_ratio": (-1.0, 0.0, 1.0)[battery_level],
            }
        vector = np.asarray(action, dtype=np.float32).reshape(4)
        vector = np.clip(vector, -1.0, 1.0)
        return {
            "shore_power_ratio": float((vector[0] + 1.0) / 2.0),
            # Ratios are fractions of the available equipment fleet. Values
            # above 1.0 would imply operation beyond rated capacity and are
            # deliberately excluded.
            "crane_ratio": float(0.60 + (vector[1] + 1.0) * 0.20),
            "yard_ratio": float(0.60 + (vector[2] + 1.0) * 0.20),
            "battery_power_ratio": float(vector[3]),
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
        battery_soc: float | None = None,
    ) -> dict[str, Any]:
        """Evaluate a future transition while restoring all environment state."""
        original_hour = self._hour
        original_queue = self._queue_teu
        original_soc = self._battery_soc
        try:
            self._hour = original_hour + int(hour_offset)
            self._queue_teu = original_queue if queue_teu is None else float(queue_teu)
            self._battery_soc = original_soc if battery_soc is None else float(battery_soc)
            return self._calculate_transition(controls)
        finally:
            self._hour = original_hour
            self._queue_teu = original_queue
            self._battery_soc = original_soc

    def summary(self) -> dict[str, Any]:
        return {
            **deepcopy(self._totals),
            "steps": self._hour,
            "period": self._episode_start_period,
            "ending_battery_soc": self._battery_soc,
            "ending_queue_teu": self._queue_teu,
        }

    def _row(self):
        return self._row_at(0)

    def _row_at(self, hour_offset: int):
        index = self._row_index
        if self.temporal_mode == "sequential_rows":
            index = min(len(self.frame) - 1, index + self._hour + int(hour_offset))
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
        if name in self._parameter_columns:
            row = self._row()
            if not np.isnan(float(row[name])):
                return float(row[name])
        return self._resolved_parameters[name]

    def _parameter_default(self, name: str) -> float:
        if name in self._resolved_parameters:
            return self._resolved_parameters[name]
        configured = self.dataset.metadata.get("environment_parameters") or {}
        if name in configured:
            return float(configured[name])
        if name in DEFAULT_ENVIRONMENT_PARAMETERS:
            return float(DEFAULT_ENVIRONMENT_PARAMETERS[name])
        raise KeyError(name)

    def _row_value(self, name: str, default: float = 0.0) -> float:
        row = self._row()
        if name not in row.index:
            return float(default)
        value = float(row[name])
        return float(default) if np.isnan(value) else value

    def _shore_power_opportunity_kw(self) -> float:
        capacity = self._parameter("shore_demand_kw")
        if self.environment_id == "PortEnergyDispatchEnv-v1":
            return capacity
        per_vessel = self._parameter("vessel_auxiliary_demand_kw")
        availability = float(
            np.clip(
                self._row_value(
                    "shore_power_available_ratio",
                    self._parameter("shore_power_available_ratio"),
                ),
                0.0,
                1.0,
            )
        )
        if self.environment_id == "PortEnergyDispatchEnv-v3":
            availability *= float(
                np.clip(
                    self._row_value("shore_power_compatible_ratio"),
                    0.0,
                    1.0,
                )
            )
        demand = self._row_value("vessels_at_berth") * per_vessel
        return min(capacity * availability, demand)

    def _observation(self) -> np.ndarray:
        row = self._row()
        demand = self._demand_teu()
        forecast_rows = [self._row_at(offset) for offset in (1, 2, 3)]
        forecast_demand = float(
            np.mean(
                [
                    float(item["total_teu"]) / max(1.0, float(item.get("observation_hours", 1.0)))
                    for item in forecast_rows
                ]
            )
        )
        forecast_carbon = float(
            np.mean([float(item["grid_carbon_kg_per_kwh"]) for item in forecast_rows])
        )
        forecast_price = float(
            np.mean([float(item["electricity_price_per_kwh"]) for item in forecast_rows])
        )
        timestamp = None
        time_column = str(self.dataset.metadata.get("time_column") or "")
        if time_column and time_column in row.index:
            timestamp = datetime.fromisoformat(str(row[time_column]).replace("Z", "+00:00"))
        if timestamp is not None:
            hour = int(timestamp.hour)
            month = int(timestamp.month)
        else:
            hour = self._hour % 24
            month = int(str(row["period"]).split("-")[1])
        hour_angle = 2 * np.pi * hour / 24.0
        month_angle = 2 * np.pi * (month - 1) / 12.0
        grid_capacity = self._parameter("grid_capacity_kw")
        previous_peak = self._totals.get("peak_kw", 0.0)
        values = [
            demand / 1800.0,
            self._queue_teu / 5000.0,
            forecast_demand / 1800.0,
            float(row["grid_carbon_kg_per_kwh"]) / 0.8,
            forecast_carbon / 0.8,
            float(row["electricity_price_per_kwh"]) / 3.5,
            forecast_price / 3.5,
            float(row["fuel_price_per_liter"]) / 12.0,
            max(0.0, 1.0 - previous_peak / max(1.0, grid_capacity)),
            self._battery_soc,
            (self._last_battery_power_ratio + 1.0) / 2.0,
            (np.sin(hour_angle) + 1.0) / 2.0,
            (np.cos(hour_angle) + 1.0) / 2.0,
            (np.sin(month_angle) + 1.0) / 2.0,
            (np.cos(month_angle) + 1.0) / 2.0,
            float(row["loaded_import_teu"]) / max(1.0, float(row["total_teu"])),
            float(row["loaded_export_teu"]) / max(1.0, float(row["total_teu"])),
            self._totals.get("carbon_kg", 0.0) / 100_000.0,
            self._totals.get("delay_minutes", 0.0) / 2_000.0,
        ]
        if self.environment_id in {
            "PortEnergyDispatchEnv-v2",
            "PortEnergyDispatchEnv-v3",
        }:
            values.extend(
                self._row_value(name) / self._operational_normalizers.get(name, 1.0)
                for name in OPERATIONAL_OBSERVATION_KEYS
            )
        if self.environment_id == "PortEnergyDispatchEnv-v3":
            values.extend(
                self._row_value(name) / self._operational_normalizers.get(name, 1.0)
                for name in DEPLOYMENT_OBSERVATION_KEYS
            )
        observation = np.array(values, dtype=np.float32)
        return np.clip(observation, 0.0, 1.5)

    def _calculate_transition(self, controls: dict[str, float]) -> dict[str, Any]:
        row = self._row()
        demand_teu = self._demand_teu() + self._queue_teu
        crane_availability = (
            float(
                np.clip(
                    self._row_value("crane_available_ratio", 1.0),
                    0.0,
                    1.0,
                )
            )
            if self.environment_id == "PortEnergyDispatchEnv-v3"
            else 1.0
        )
        yard_availability = (
            float(
                np.clip(
                    self._row_value("yard_available_ratio", 1.0),
                    0.0,
                    1.0,
                )
            )
            if self.environment_id == "PortEnergyDispatchEnv-v3"
            else 1.0
        )
        berth_availability = (
            float(
                np.clip(
                    self._row_value("berth_available_ratio", 1.0),
                    0.0,
                    1.0,
                )
            )
            if self.environment_id == "PortEnergyDispatchEnv-v3"
            else 1.0
        )
        crane_availability *= berth_availability
        yard_availability *= berth_availability
        crane_capacity = (
            self._parameter("crane_capacity_teu_per_hour")
            * controls["crane_ratio"]
            * crane_availability
        )
        yard_capacity = (
            self._parameter("yard_capacity_teu_per_hour")
            * controls["yard_ratio"]
            * yard_availability
        )
        processed_teu = min(demand_teu, crane_capacity, yard_capacity)
        queue_teu = max(0.0, demand_teu - processed_teu)
        delay_minutes = queue_teu / max(1.0, min(crane_capacity, yard_capacity)) * 60.0

        shore_demand_kw = self._shore_power_opportunity_kw()
        shore_power_kwh = shore_demand_kw * controls["shore_power_ratio"]
        auxiliary_energy_kwh = shore_demand_kw - shore_power_kwh
        auxiliary_fuel_liters = auxiliary_energy_kwh / max(
            0.001, self._parameter("fuel_kwh_per_liter")
        )
        base_load_kw = self._parameter("base_load_kw") + processed_teu * self._parameter(
            "load_kw_per_teu"
        )
        crane_load_kw = self._parameter("crane_load_kw") * controls["crane_ratio"]
        yard_load_kw = self._parameter("yard_load_kw") * controls["yard_ratio"]
        gross_load_kw = base_load_kw + crane_load_kw + yard_load_kw + shore_power_kwh
        battery_capacity = self._parameter("battery_capacity_kwh")
        battery_power_limit = self._parameter("battery_power_kw")
        charge_efficiency = self._parameter("battery_charge_efficiency")
        discharge_efficiency = self._parameter("battery_discharge_efficiency")
        min_soc = self._parameter("battery_min_soc")
        max_soc = self._parameter("battery_max_soc")
        requested_battery_kw = controls["battery_power_ratio"] * battery_power_limit
        grid_availability = (
            float(
                np.clip(
                    self._row_value("grid_available_ratio", 1.0),
                    0.0,
                    1.0,
                )
            )
            if self.environment_id == "PortEnergyDispatchEnv-v3"
            else 1.0
        )
        grid_capacity_kw = self._parameter("grid_capacity_kw") * grid_availability
        # Safety layer 1: charging may not push the grid import above its hard
        # capacity. Positive battery power discharges to the port load.
        safe_charge_limit = max(0.0, grid_capacity_kw - gross_load_kw)
        grid_safe_battery_kw = float(
            np.clip(
                requested_battery_kw,
                -min(battery_power_limit, safe_charge_limit),
                battery_power_limit,
            )
        )
        available_discharge = max(
            0.0, (self._battery_soc - min_soc) * battery_capacity * discharge_efficiency
        )
        available_charge = max(
            0.0, (max_soc - self._battery_soc) * battery_capacity / charge_efficiency
        )
        battery_discharge_kwh = min(max(0.0, grid_safe_battery_kw), available_discharge)
        battery_charge_kwh = min(max(0.0, -grid_safe_battery_kw), available_charge)
        next_battery_soc = self._battery_soc
        next_battery_soc += battery_charge_kwh * charge_efficiency / battery_capacity
        next_battery_soc -= battery_discharge_kwh / (discharge_efficiency * battery_capacity)
        next_battery_soc = float(np.clip(next_battery_soc, min_soc, max_soc))
        # Safety layer 2: preserve reachability of the declared terminal SOC.
        # This is an explicit action projection, not a learned soft penalty.
        remaining_after_step = max(0, self.episode_hours - (self._hour + 1))
        target_soc = self._parameter("battery_initial_soc")
        worst_case_base_load = (
            self._parameter("base_load_kw")
            + min(
                self._parameter("crane_capacity_teu_per_hour"),
                self._parameter("yard_capacity_teu_per_hour"),
            )
            * self._parameter("load_kw_per_teu")
            + self._parameter("crane_load_kw")
            + self._parameter("yard_load_kw")
            + self._parameter("shore_demand_kw")
        )
        conservative_charge_limit = max(
            0.0, min(battery_power_limit, grid_capacity_kw - worst_case_base_load)
        )
        future_charge_soc = (
            remaining_after_step * conservative_charge_limit * charge_efficiency / battery_capacity
        )
        future_discharge_soc = (
            remaining_after_step * battery_power_limit / (discharge_efficiency * battery_capacity)
        )
        reachable_low = max(min_soc, target_soc - future_charge_soc)
        reachable_high = min(max_soc, target_soc + future_discharge_soc)
        projected_next_soc = float(np.clip(next_battery_soc, reachable_low, reachable_high))
        if projected_next_soc >= self._battery_soc:
            battery_charge_kwh = min(
                safe_charge_limit,
                (projected_next_soc - self._battery_soc) * battery_capacity / charge_efficiency,
            )
            battery_discharge_kwh = 0.0
        else:
            battery_discharge_kwh = (
                (self._battery_soc - projected_next_soc) * battery_capacity * discharge_efficiency
            )
            battery_charge_kwh = 0.0
        next_battery_soc = projected_next_soc
        actual_battery_kw = battery_discharge_kwh - battery_charge_kwh
        projected_battery_kwh = abs(requested_battery_kw - actual_battery_kw)
        load_kw = gross_load_kw + battery_charge_kwh - battery_discharge_kwh
        peak_violation_kw = max(0.0, load_kw - grid_capacity_kw)
        peak_violation = int(peak_violation_kw > 0.0)
        delay_violation = int(delay_minutes > self._parameter("delay_limit_minutes"))
        terminal_soc_error = abs(next_battery_soc - self._parameter("battery_initial_soc"))
        terminal_soc_violation = int(
            self._hour + 1 >= self.episode_hours
            and terminal_soc_error > self._parameter("terminal_soc_tolerance")
        )
        safety_violations = int(peak_violation or delay_violation or terminal_soc_violation)

        renewable_power_kw = (
            self._row_value("renewable_power_available_kw")
            if self.environment_id == "PortEnergyDispatchEnv-v3"
            else 0.0
        )
        renewable_energy_kwh = min(max(0.0, load_kw), renewable_power_kw)
        grid_energy_kwh = max(0.0, load_kw - renewable_energy_kwh)
        energy_kwh = grid_energy_kwh + renewable_energy_kwh + auxiliary_energy_kwh
        grid_carbon_kg = grid_energy_kwh * float(row["grid_carbon_kg_per_kwh"])
        fuel_carbon_kg = auxiliary_fuel_liters * self._parameter("fuel_carbon_kg_per_liter")
        carbon_kg = grid_carbon_kg + fuel_carbon_kg
        delay_cost_cny = delay_minutes * self._parameter("delay_cost_cny_per_minute")
        battery_throughput_kwh = battery_charge_kwh + battery_discharge_kwh
        battery_degradation_cost_cny = battery_throughput_kwh * self._parameter(
            "battery_degradation_cny_per_kwh"
        )
        previous_peak = self._totals.get("peak_kw", 0.0)
        demand_charge_cost_cny = max(0.0, load_kw - previous_peak) * self._parameter(
            "demand_charge_cny_per_kw"
        )
        remaining_hours = max(1, self.episode_hours - (self._hour + 1))
        # The terminal value begins to matter eight hours ahead. This avoids
        # a short receding horizon postponing all recharging to the last few
        # slots, which would be economically myopic and could create a false
        # peak even when cheap low-load hours were available earlier.
        restoration_pressure = min(1.0, 4.0 / remaining_hours)
        cost = (
            grid_energy_kwh * float(row["electricity_price_per_kwh"])
            + auxiliary_fuel_liters * float(row["fuel_price_per_liter"])
            + delay_cost_cny
            + battery_degradation_cost_cny
            + demand_charge_cost_cny
        )
        terms = {
            "carbon": -carbon_kg / 6_000.0,
            "shore_power": controls["shore_power_ratio"],
            "cost": -cost / 12_000.0,
            "delay": -delay_minutes / 90.0,
            "safety": -float(safety_violations) * 4.0,
            # Penalize the actual capacity ratio so a peak-smoothing objective
            # has a gradient before the hard grid-capacity constraint is hit.
            "peak": -((load_kw / max(1.0, grid_capacity_kw)) ** 2),
            "storage": -(
                terminal_soc_error
                / max(self._parameter("terminal_soc_tolerance"), 0.01)
                * (1.0 if self._hour + 1 >= self.episode_hours else restoration_pressure)
            ),
        }
        throughput_bonus = 0.65 * processed_teu / max(1.0, demand_teu)
        reward = throughput_bonus + sum(
            self.reward_weights[key] * value for key, value in terms.items()
        )
        return {
            "reward": float(reward),
            "reward_terms": {key: float(value) for key, value in terms.items()},
            "demand_teu": float(demand_teu),
            "processed_teu": float(processed_teu),
            "queue_teu": float(queue_teu),
            "delay_minutes": float(delay_minutes),
            "load_kw": float(load_kw),
            "gross_load_kw": float(gross_load_kw),
            "peak_load_ratio": float(load_kw / max(1.0, grid_capacity_kw)),
            "peak_violation_kw": float(peak_violation_kw),
            "shore_power_kwh": float(shore_power_kwh),
            "shore_power_opportunity_kwh": float(shore_demand_kw),
            "shore_power_ratio": float(controls["shore_power_ratio"]),
            "energy_kwh": float(energy_kwh),
            "carbon_kg": float(carbon_kg),
            "grid_carbon_kg": float(grid_carbon_kg),
            "fuel_carbon_kg": float(fuel_carbon_kg),
            "renewable_energy_kwh": float(renewable_energy_kwh),
            "cost": float(cost),
            "delay_cost_cny": float(delay_cost_cny),
            "battery_soc": next_battery_soc,
            "battery_power_kw": float(battery_discharge_kwh - battery_charge_kwh),
            "battery_charge_kwh": float(battery_charge_kwh),
            "battery_discharge_kwh": float(battery_discharge_kwh),
            "battery_throughput_kwh": float(battery_throughput_kwh),
            "battery_degradation_cost_cny": float(battery_degradation_cost_cny),
            "battery_constraint_projection_kwh": float(projected_battery_kwh),
            "terminal_soc_error": float(terminal_soc_error),
            "demand_charge_cost_cny": float(demand_charge_cost_cny),
            "crane_activation_ratio_sum": float(controls["crane_ratio"]),
            "yard_activation_ratio_sum": float(controls["yard_ratio"]),
            "safety_violations": float(safety_violations),
            "peak_violation_steps": float(peak_violation),
            "delay_violation_steps": float(delay_violation),
            "soc_violation_steps": float(terminal_soc_violation),
        }

    def _trajectory_record(self, transition: dict[str, Any]) -> dict[str, Any]:
        controls = transition.get("controls") or {}
        row = self._row()
        time_column = str(self.dataset.metadata.get("time_column") or "")
        timestamp = (
            datetime.fromisoformat(str(row[time_column]).replace("Z", "+00:00"))
            if time_column and time_column in row.index
            else None
        )
        hour = timestamp.hour if timestamp else self._hour % 24
        aggregate_label = (
            f"AGGREGATED-{int(self._row_value('vessels_at_berth'))}-VESSELS"
            if self.environment_id == "PortEnergyDispatchEnv-v2"
            else f"PUBLIC-DATA-{str(row['period'])}"
        )
        return {
            "step": self._hour + 1,
            "time": f"{hour:02d}:00",
            "event": "dataset_policy_dispatch",
            "period": str(row["period"]),
            "source_id": str(row["source_id"]),
            "vessel_id": aggregate_label,
            "berth_id": "PORT-AGG"
            if self.environment_id == "PortEnergyDispatchEnv-v2"
            else f"B{(hour % 4) + 1}",
            "vessels_at_anchor": self._row_value("vessels_at_anchor"),
            "vessels_at_berth": self._row_value("vessels_at_berth"),
            "vessels_departed": self._row_value("vessels_departed"),
            "average_days_at_berth": self._row_value("average_days_at_berth"),
            "average_days_in_port": self._row_value("average_days_in_port"),
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
            "battery_soc": round(float(transition["battery_soc"]), 5),
            "battery_power_kw": round(float(transition["battery_power_kw"]), 3),
            "electricity_price_cny_per_kwh": round(
                float(self._row()["electricity_price_per_kwh"]), 5
            ),
            "grid_carbon_kg_per_kwh": round(float(self._row()["grid_carbon_kg_per_kwh"]), 5),
            "decision_reason": (
                f"policy action: shore={float(transition['shore_power_ratio']):.2f}, "
                f"battery={float(transition['battery_power_kw']):+.0f}kW, "
                f"load={float(transition['load_kw']):.0f}kW, "
                f"queue={float(transition['queue_teu']):.1f}TEU"
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

    _levels = (1.0,)
    _ratios = (0.60, 0.80, 1.00)
    # Half-power storage moves keep the finite action lattice compatible with
    # the 17 MW import cap while the RL policies retain the full continuous
    # [-1, 1] battery command.
    _battery_levels = (-0.5, 0.0, 0.5)

    def __init__(
        self,
        horizon: int = 4,
        beam_width: int = 4,
        discount: float = 0.96,
        terminal_soc_weight: float = 2.0,
    ) -> None:
        self.horizon = max(1, int(horizon))
        self.beam_width = max(1, int(beam_width))
        self.discount = float(discount)
        self.terminal_soc_weight = max(0.0, float(terminal_soc_weight))

    def candidates(self) -> list[dict[str, float]]:
        return [
            {
                "shore_power_ratio": shore,
                "crane_ratio": crane,
                "yard_ratio": yard,
                "battery_power_ratio": battery,
            }
            for shore in self._levels
            for crane in self._ratios
            for yard in self._ratios
            for battery in self._battery_levels
        ]

    def predict(self, env: PortEnergyDispatchEnv) -> dict[str, float]:
        actions = self.candidates()
        target_soc = env._parameter("battery_initial_soc")

        def search_rank(item: tuple[float, float, float, dict[str, float]]) -> float:
            return item[0] + 0.5 * self.terminal_soc_weight * abs(item[2] - target_soc)

        beam: list[tuple[float, float, float, dict[str, float]]] = []
        for controls in actions:
            transition = env.preview_transition(
                controls,
                queue_teu=env._queue_teu,
                battery_soc=env._battery_soc,
            )
            beam.append(
                (
                    self._transition_cost(transition),
                    float(transition["queue_teu"]),
                    float(transition["battery_soc"]),
                    controls,
                )
            )
        beam = sorted(beam, key=search_rank)[: self.beam_width]

        for hour_offset in range(1, self.horizon):
            expanded: list[tuple[float, float, float, dict[str, float]]] = []
            for accumulated_cost, queue_teu, battery_soc, first_controls in beam:
                for controls in actions:
                    transition = env.preview_transition(
                        controls,
                        hour_offset=hour_offset,
                        queue_teu=queue_teu,
                        battery_soc=battery_soc,
                    )
                    expanded.append(
                        (
                            accumulated_cost
                            + self.discount**hour_offset * self._transition_cost(transition),
                            float(transition["queue_teu"]),
                            float(transition["battery_soc"]),
                            first_controls,
                        )
                    )
            beam = sorted(expanded, key=search_rank)[: self.beam_width]
        return min(
            beam,
            key=lambda item: item[0] + self.terminal_soc_weight * abs(item[2] - target_soc),
        )[3]

    @staticmethod
    def _transition_cost(transition: dict[str, Any]) -> float:
        return -float(transition["reward"]) + 1_000_000.0 * float(transition["safety_violations"])


class FixedDispatchPolicy:
    """Strong comparator with full shore power and fixed equipment resources.

    Both this baseline and MPC use shore power. The comparison therefore
    isolates dynamic crane/yard allocation instead of attributing the whole
    shore-power transition to the optimizer.
    """

    def __init__(
        self,
        shore_power_ratio: float = 1.0,
        crane_ratio: float = 1.0,
        yard_ratio: float = 1.0,
        battery_power_ratio: float = 0.0,
    ) -> None:
        self.controls = {
            "shore_power_ratio": float(shore_power_ratio),
            "crane_ratio": float(crane_ratio),
            "yard_ratio": float(yard_ratio),
            "battery_power_ratio": float(battery_power_ratio),
        }

    def predict(self, env: PortEnergyDispatchEnv) -> dict[str, float]:
        del env
        return dict(self.controls)


def encode_continuous_controls(controls: dict[str, float]) -> np.ndarray:
    return np.array(
        [
            controls["shore_power_ratio"] * 2.0 - 1.0,
            (controls["crane_ratio"] - 0.60) / 0.20 - 1.0,
            (controls["yard_ratio"] - 0.60) / 0.20 - 1.0,
            controls.get("battery_power_ratio", 0.0),
        ],
        dtype=np.float32,
    )
