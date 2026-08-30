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

DEFAULT_FLEX_REWARD_WEIGHTS = {
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

DEFAULT_HYBRID_REWARD_WEIGHTS = {
    "carbon": 0.12,
    "shore_power": 0.04,
    "cost": 0.12,
    "delay": 0.10,
    "safety": 0.18,
    "peak": 0.06,
    "storage": 0.04,
    "agv_service": 0.05,
    "reefer_safety": 0.06,
    "demand_response": 0.04,
    "equipment_health": 0.03,
    "jit_service": 0.035,
    "green_berth": 0.025,
    "crane_schedule": 0.025,
    "yard_slotting": 0.025,
    "truck_flow": 0.025,
    "maintenance_risk": 0.025,
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
    "inspection_readiness_load_kw": 240.0,
    "regulatory_recovery_load_kw": 520.0,
    "inspection_auxiliary_kwh_per_teu_hour": 0.08,
    "released_staging_capacity_teu_per_hour": 900.0,
    "recovery_capacity_ratio": 0.35,
    "agv_charger_capacity_kw": 4_000.0,
    "agv_charge_efficiency": 0.94,
    "reefer_minimum_service_ratio": 0.75,
    "reefer_thermal_debt_limit": 1.0,
    "reefer_thermal_recovery_rate": 0.45,
    "building_minimum_flexible_load_ratio": 0.35,
    "demand_response_non_delivery_cny_per_kwh": 5.0,
    "agv_missed_energy_cny_per_kwh": 3.0,
    "reefer_safety_cny_per_degree_hour": 1_200.0,
}

HYBRID_ENVIRONMENT_PARAMETERS = {
    "hybrid_residual_trust_ratio": 0.20,
    "jit_deviation_cost_cny_per_hour": 2_400.0,
    "berth_conflict_cost_cny_per_hour": 4_000.0,
    "crane_task_lateness_cny_per_teu": 9.0,
    "yard_rehandle_cost_cny_per_teu": 7.0,
    "truck_queue_cost_cny_per_teu_hour": 11.0,
    "maintenance_overdue_cost_cny_per_hour": 8_000.0,
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
REGULATORY_OBSERVATION_KEYS = (
    "maritime_inspection_ratio",
    "customs_inspection_ratio",
    "maritime_release_ratio",
    "customs_release_ratio",
    "document_readiness_ratio",
    "inspection_resource_available_ratio",
    "regulatory_scenario_observed",
    "expected_hold_hours",
    "maritime_hold_queue_teu",
    "customs_hold_queue_teu",
    "released_recovery_queue_teu",
    "previous_inspection_readiness_action",
    "previous_recovery_priority_action",
)
REGULATORY_DATA_KEYS = REGULATORY_OBSERVATION_KEYS[:8]
FLEXIBLE_OPERATIONS_OBSERVATION_KEYS = (
    "agv_fleet_available_ratio",
    "agv_mean_soc",
    "agv_charge_demand_kwh",
    "agv_departure_requirement_kwh",
    "charger_available_ratio",
    "reefer_connected_count",
    "reefer_baseline_load_kw",
    "reefer_thermal_margin_c",
    "building_critical_load_kw",
    "building_flexible_load_kw",
    "shore_power_reserved_kw",
    "shore_power_window_remaining_hours",
    "equipment_health_ratio",
    "crane_fault_risk",
    "yard_fault_risk",
    "demand_response_active",
    "demand_response_target_kw",
    "demand_response_remaining_hours",
    "renewable_power_forecast_kw",
    "maintenance_window_active",
    "reefer_thermal_debt",
    "previous_agv_charging_action",
    "previous_reefer_service_action",
    "previous_building_flexible_load_action",
    "previous_demand_response_action",
)
FLEXIBLE_OPERATIONS_DATA_KEYS = FLEXIBLE_OPERATIONS_OBSERVATION_KEYS[:20]
HYBRID_OPERATIONS_DATA_KEYS = (
    "jit_window_feasible_ratio",
    "pilot_tug_readiness_ratio",
    "arrival_uncertainty_hours",
    "anchorage_auxiliary_fuel_l_per_hour",
    "green_berth_candidate_ratio",
    "berth_conflict_ratio",
    "crane_task_backlog_teu",
    "crane_precedence_pressure_ratio",
    "yard_rehandle_ratio",
    "yard_slot_capacity_ratio",
    "truck_gate_queue_teu",
    "truck_appointment_pressure_ratio",
    "truck_gate_capacity_teu_per_hour",
    "maintenance_due_ratio",
    "maintenance_resource_available_ratio",
    "failure_risk_forecast",
)
HYBRID_STATE_OBSERVATION_KEYS = (
    "maintenance_debt",
    "previous_jit_arrival_priority",
    "previous_green_berth_priority",
    "previous_crane_task_priority",
    "previous_yard_slotting_priority",
    "previous_truck_gate_priority",
    "previous_maintenance_priority",
)
HYBRID_CONTROL_REFERENCE_OBSERVATION_KEYS = (
    "controller_shore_power_ratio",
    "controller_crane_ratio",
    "controller_yard_ratio",
    "controller_battery_power_ratio",
    "controller_inspection_readiness_ratio",
    "controller_recovery_priority_ratio",
    "controller_agv_charging_ratio",
    "controller_reefer_service_ratio",
    "controller_building_flexible_load_ratio",
    "controller_demand_response_ratio",
)
HYBRID_OBSERVATION_KEYS = (
    HYBRID_OPERATIONS_DATA_KEYS
    + HYBRID_STATE_OBSERVATION_KEYS
    + HYBRID_CONTROL_REFERENCE_OBSERVATION_KEYS
)

OPERATIONAL_ENVIRONMENTS = {
    "PortEnergyDispatchEnv-v2",
    "PortEnergyDispatchEnv-v3",
    "PortEnergyDispatchEnv-v4",
    "PortEnergyDispatchEnv-v5",
    "PortEnergyHybridResidualEnv-v6",
}
DEPLOYMENT_ENVIRONMENTS = {
    "PortEnergyDispatchEnv-v3",
    "PortEnergyDispatchEnv-v4",
    "PortEnergyDispatchEnv-v5",
    "PortEnergyHybridResidualEnv-v6",
}
REGULATORY_ENVIRONMENTS = {
    "PortEnergyDispatchEnv-v4",
    "PortEnergyDispatchEnv-v5",
    "PortEnergyHybridResidualEnv-v6",
}
FLEXIBLE_ENVIRONMENTS = {
    "PortEnergyDispatchEnv-v5",
    "PortEnergyHybridResidualEnv-v6",
}


def observation_keys_for_environment(environment_id: str) -> tuple[str, ...]:
    if environment_id == "PortEnergyDispatchEnv-v1":
        return OBSERVATION_KEYS
    if environment_id == "PortEnergyDispatchEnv-v2":
        return OBSERVATION_KEYS + OPERATIONAL_OBSERVATION_KEYS
    if environment_id == "PortEnergyDispatchEnv-v3":
        return OBSERVATION_KEYS + OPERATIONAL_OBSERVATION_KEYS + DEPLOYMENT_OBSERVATION_KEYS
    if environment_id == "PortEnergyDispatchEnv-v4":
        return (
            OBSERVATION_KEYS
            + OPERATIONAL_OBSERVATION_KEYS
            + DEPLOYMENT_OBSERVATION_KEYS
            + REGULATORY_OBSERVATION_KEYS
        )
    if environment_id == "PortEnergyDispatchEnv-v5":
        return (
            OBSERVATION_KEYS
            + OPERATIONAL_OBSERVATION_KEYS
            + DEPLOYMENT_OBSERVATION_KEYS
            + REGULATORY_OBSERVATION_KEYS
            + FLEXIBLE_OPERATIONS_OBSERVATION_KEYS
        )
    if environment_id == "PortEnergyHybridResidualEnv-v6":
        return (
            OBSERVATION_KEYS
            + OPERATIONAL_OBSERVATION_KEYS
            + DEPLOYMENT_OBSERVATION_KEYS
            + REGULATORY_OBSERVATION_KEYS
            + FLEXIBLE_OPERATIONS_OBSERVATION_KEYS
            + HYBRID_OBSERVATION_KEYS
        )
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
            if self.environment_id in DEPLOYMENT_ENVIRONMENTS
            else set()
        )
        if self.environment_id in REGULATORY_ENVIRONMENTS:
            required_observations |= set(REGULATORY_DATA_KEYS)
        if self.environment_id in FLEXIBLE_ENVIRONMENTS:
            required_observations |= set(FLEXIBLE_OPERATIONS_DATA_KEYS)
        if self.environment_id == "PortEnergyHybridResidualEnv-v6":
            required_observations |= set(HYBRID_OPERATIONS_DATA_KEYS)
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
            for name in (
                OPERATIONAL_OBSERVATION_KEYS
                + DEPLOYMENT_OBSERVATION_KEYS
                + REGULATORY_DATA_KEYS
                + FLEXIBLE_OPERATIONS_DATA_KEYS
                + HYBRID_OPERATIONS_DATA_KEYS
            )
            if name in train_frame.columns
        }
        configured_parameters = self.dataset.metadata.get("environment_parameters") or {}
        parameter_defaults = {
            **DEFAULT_ENVIRONMENT_PARAMETERS,
            **(
                HYBRID_ENVIRONMENT_PARAMETERS
                if self.environment_id == "PortEnergyHybridResidualEnv-v6"
                else {}
            ),
        }
        self._resolved_parameters = {
            name: float(configured_parameters.get(name, default))
            for name, default in parameter_defaults.items()
        }
        self._parameter_columns = set(parameter_defaults) & set(self.frame.columns)
        self.temporal_mode = self.dataset.temporal_mode
        self.split_name = split
        self.action_mode = action_mode
        self.render_mode = render_mode
        self.episode_hours = max(1, min(744, int(episode_hours)))
        default_weights = (
            DEFAULT_HYBRID_REWARD_WEIGHTS
            if self.environment_id == "PortEnergyHybridResidualEnv-v6"
            else DEFAULT_FLEX_REWARD_WEIGHTS
            if self.environment_id == "PortEnergyDispatchEnv-v5"
            else DEFAULT_REWARD_WEIGHTS
        )
        self.reward_weights = self._normalize_weights(reward_weights or default_weights)
        regulatory = self.environment_id in REGULATORY_ENVIRONMENTS
        flexible = self.environment_id in FLEXIBLE_ENVIRONMENTS
        hybrid = self.environment_id == "PortEnergyHybridResidualEnv-v6"
        if hybrid and action_mode == "discrete":
            raise ValueError("PortEnergyHybridResidualEnv-v6 supports continuous actions only")
        self.action_space = (
            spaces.Discrete(243 if flexible else 729 if regulatory else 81)
            if action_mode == "discrete"
            else spaces.Box(
                low=-1.0,
                high=1.0,
                shape=(16 if hybrid else 10 if flexible else 6 if regulatory else 4,),
                dtype=np.float32,
            )
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
        self._maritime_hold_teu = 0.0
        self._customs_hold_teu = 0.0
        self._released_recovery_teu = 0.0
        self._last_inspection_readiness_ratio = 0.0
        self._last_recovery_priority_ratio = 0.0
        self._reefer_thermal_debt = 0.0
        self._last_agv_charging_ratio = 1.0
        self._last_reefer_service_ratio = 1.0
        self._last_building_flexible_load_ratio = 1.0
        self._last_demand_response_ratio = 0.0
        self._maintenance_debt = 0.0
        self._last_hybrid_priorities = {
            "jit_arrival_priority": 0.5,
            "green_berth_priority": 0.5,
            "crane_task_priority": 0.5,
            "yard_slotting_priority": 0.5,
            "truck_gate_priority": 0.5,
            "maintenance_priority": 0.5,
        }
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
        self._maritime_hold_teu = 0.0
        self._customs_hold_teu = 0.0
        self._released_recovery_teu = 0.0
        self._last_inspection_readiness_ratio = 0.0
        self._last_recovery_priority_ratio = 0.0
        self._reefer_thermal_debt = float(options.get("reefer_thermal_debt", 0.0))
        self._last_agv_charging_ratio = 1.0
        self._last_reefer_service_ratio = 1.0
        self._last_building_flexible_load_ratio = 1.0
        self._last_demand_response_ratio = 0.0
        self._maintenance_debt = float(options.get("maintenance_debt", 0.0))
        self._last_hybrid_priorities = {
            "jit_arrival_priority": 0.5,
            "green_berth_priority": 0.5,
            "crane_task_priority": 0.5,
            "yard_slotting_priority": 0.5,
            "truck_gate_priority": 0.5,
            "maintenance_priority": 0.5,
        }
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
            "maritime_inspection_arrivals_teu": 0.0,
            "customs_inspection_arrivals_teu": 0.0,
            "maritime_released_teu": 0.0,
            "customs_released_teu": 0.0,
            "processed_recovery_teu": 0.0,
            "regulatory_delay_minutes": 0.0,
            "regulatory_auxiliary_energy_kwh": 0.0,
            "inspection_readiness_energy_kwh": 0.0,
            "recovery_energy_kwh": 0.0,
            "inspection_readiness_ratio_sum": 0.0,
            "recovery_priority_ratio_sum": 0.0,
            "agv_charge_demand_kwh": 0.0,
            "agv_charged_kwh": 0.0,
            "agv_missed_required_kwh": 0.0,
            "reefer_energy_kwh": 0.0,
            "reefer_thermal_violation_steps": 0.0,
            "building_energy_kwh": 0.0,
            "demand_response_target_kwh": 0.0,
            "demand_response_delivered_kwh": 0.0,
            "demand_response_non_delivery_kwh": 0.0,
            "flexible_load_projection_kwh": 0.0,
            "equipment_health_projection_steps": 0.0,
            "hybrid_solver_projection_l1": 0.0,
            "hybrid_solver_constraint_violations": 0.0,
            "jit_deviation_hours": 0.0,
            "anchorage_auxiliary_fuel_liters": 0.0,
            "berth_conflict_hours": 0.0,
            "crane_task_late_teu": 0.0,
            "yard_rehandles_teu": 0.0,
            "truck_queue_teu_hours": 0.0,
            "maintenance_overdue_hours": 0.0,
            "maintenance_performed_ratio": 0.0,
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
        self, action: np.ndarray | int | dict[str, float]
    ) -> tuple[np.ndarray, float, bool, bool, dict[str, Any]]:
        controls = self.decode_action(action)
        transition = self._calculate_transition(controls)
        transition["controls"] = controls
        self._queue_teu = transition["queue_teu"]
        self._battery_soc = transition["battery_soc"]
        self._last_battery_power_ratio = controls["battery_power_ratio"]
        self._maritime_hold_teu = transition["maritime_hold_queue_teu"]
        self._customs_hold_teu = transition["customs_hold_queue_teu"]
        self._released_recovery_teu = transition["released_recovery_queue_teu"]
        self._last_inspection_readiness_ratio = controls.get(
            "inspection_readiness_ratio", 0.0
        )
        self._last_recovery_priority_ratio = controls.get("recovery_priority_ratio", 0.0)
        self._reefer_thermal_debt = float(transition["reefer_thermal_debt"])
        self._last_agv_charging_ratio = controls.get("agv_charging_ratio", 1.0)
        self._last_reefer_service_ratio = controls.get("reefer_service_ratio", 1.0)
        self._last_building_flexible_load_ratio = controls.get(
            "building_flexible_load_ratio", 1.0
        )
        self._last_demand_response_ratio = controls.get("demand_response_ratio", 0.0)
        self._maintenance_debt = float(transition["maintenance_debt"])
        for key in self._last_hybrid_priorities:
            self._last_hybrid_priorities[key] = controls.get(key, 0.5)
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
            "maritime_inspection_arrivals_teu",
            "customs_inspection_arrivals_teu",
            "maritime_released_teu",
            "customs_released_teu",
            "processed_recovery_teu",
            "regulatory_delay_minutes",
            "regulatory_auxiliary_energy_kwh",
            "inspection_readiness_energy_kwh",
            "recovery_energy_kwh",
            "inspection_readiness_ratio_sum",
            "recovery_priority_ratio_sum",
            "agv_charge_demand_kwh",
            "agv_charged_kwh",
            "agv_missed_required_kwh",
            "reefer_energy_kwh",
            "reefer_thermal_violation_steps",
            "building_energy_kwh",
            "demand_response_target_kwh",
            "demand_response_delivered_kwh",
            "demand_response_non_delivery_kwh",
            "flexible_load_projection_kwh",
            "equipment_health_projection_steps",
            "hybrid_solver_projection_l1",
            "hybrid_solver_constraint_violations",
            "jit_deviation_hours",
            "anchorage_auxiliary_fuel_liters",
            "berth_conflict_hours",
            "crane_task_late_teu",
            "yard_rehandles_teu",
            "truck_queue_teu_hours",
            "maintenance_overdue_hours",
            "maintenance_performed_ratio",
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

    def decode_action(
        self, action: np.ndarray | int | dict[str, float]
    ) -> dict[str, float]:
        if isinstance(action, dict):
            return {str(key): float(value) for key, value in action.items()}
        if self.environment_id == "PortEnergyHybridResidualEnv-v6":
            from app.rl.hybrid_control import decode_hybrid_action

            controls, solver_result = decode_hybrid_action(self, np.asarray(action))
            return {
                **controls,
                "hybrid_solver_projection_l1": solver_result.projection_l1,
                "hybrid_solver_constraint_violations": float(
                    solver_result.hard_constraint_violations
                ),
            }
        if self.action_mode == "discrete":
            value = int(action)
            if not self.action_space.contains(value):
                raise ValueError(f"Discrete action out of range: {value}")
            flexible = self.environment_id == "PortEnergyDispatchEnv-v5"
            shape = (
                (3, 3, 3, 3, 3)
                if flexible
                else (3, 3, 3, 3, 3, 3)
                if self.environment_id == "PortEnergyDispatchEnv-v4"
                else (3, 3, 3, 3)
            )
            levels = np.unravel_index(value, shape)
            if flexible:
                shore_level, equipment_level, battery_level, regulatory_level, flex_level = levels
                crane_level = yard_level = equipment_level
            else:
                shore_level, crane_level, yard_level, battery_level = levels[:4]
            controls = {
                "shore_power_ratio": (0.0, 0.5, 1.0)[shore_level],
                "crane_ratio": (0.60, 0.80, 1.00)[crane_level],
                "yard_ratio": (0.60, 0.80, 1.00)[yard_level],
                "battery_power_ratio": (-1.0, 0.0, 1.0)[battery_level],
            }
            if flexible:
                readiness = (0.25, 0.60, 1.00)[regulatory_level]
                flex = (0.35, 0.70, 1.00)[flex_level]
                controls.update(
                    inspection_readiness_ratio=readiness,
                    recovery_priority_ratio=readiness,
                    agv_charging_ratio=flex,
                    reefer_service_ratio=(0.75, 0.90, 1.00)[flex_level],
                    building_flexible_load_ratio=flex,
                    demand_response_ratio=(1.0, 0.5, 0.0)[flex_level],
                )
            elif self.environment_id == "PortEnergyDispatchEnv-v4":
                controls.update(
                    inspection_readiness_ratio=(0.0, 0.5, 1.0)[levels[4]],
                    recovery_priority_ratio=(0.0, 0.5, 1.0)[levels[5]],
                )
            return controls
        action_count = (
            16
            if self.environment_id == "PortEnergyHybridResidualEnv-v6"
            else 10
            if self.environment_id == "PortEnergyDispatchEnv-v5"
            else 6
            if self.environment_id == "PortEnergyDispatchEnv-v4"
            else 4
        )
        vector = np.asarray(action, dtype=np.float32).reshape(action_count)
        vector = np.clip(vector, -1.0, 1.0)
        controls = {
            "shore_power_ratio": float((vector[0] + 1.0) / 2.0),
            # Ratios are fractions of the available equipment fleet. Values
            # above 1.0 would imply operation beyond rated capacity and are
            # deliberately excluded.
            "crane_ratio": float(0.60 + (vector[1] + 1.0) * 0.20),
            "yard_ratio": float(0.60 + (vector[2] + 1.0) * 0.20),
            "battery_power_ratio": float(vector[3]),
        }
        if self.environment_id in REGULATORY_ENVIRONMENTS:
            controls.update(
                inspection_readiness_ratio=float((vector[4] + 1.0) / 2.0),
                recovery_priority_ratio=float((vector[5] + 1.0) / 2.0),
            )
        if self.environment_id == "PortEnergyDispatchEnv-v5":
            controls.update(
                agv_charging_ratio=float((vector[6] + 1.0) / 2.0),
                reefer_service_ratio=float(
                    self._parameter("reefer_minimum_service_ratio")
                    + (vector[7] + 1.0)
                    / 2.0
                    * (1.0 - self._parameter("reefer_minimum_service_ratio"))
                ),
                building_flexible_load_ratio=float(
                    self._parameter("building_minimum_flexible_load_ratio")
                    + (vector[8] + 1.0)
                    / 2.0
                    * (1.0 - self._parameter("building_minimum_flexible_load_ratio"))
                ),
                demand_response_ratio=float((vector[9] + 1.0) / 2.0),
            )
        return controls

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
        original_maritime_hold = self._maritime_hold_teu
        original_customs_hold = self._customs_hold_teu
        original_recovery = self._released_recovery_teu
        try:
            self._hour = original_hour + int(hour_offset)
            self._queue_teu = original_queue if queue_teu is None else float(queue_teu)
            self._battery_soc = original_soc if battery_soc is None else float(battery_soc)
            return self._calculate_transition(controls)
        finally:
            self._hour = original_hour
            self._queue_teu = original_queue
            self._battery_soc = original_soc
            self._maritime_hold_teu = original_maritime_hold
            self._customs_hold_teu = original_customs_hold
            self._released_recovery_teu = original_recovery

    def summary(self) -> dict[str, Any]:
        return {
            **deepcopy(self._totals),
            "steps": self._hour,
            "period": self._episode_start_period,
            "ending_battery_soc": self._battery_soc,
            "ending_queue_teu": self._queue_teu,
            "ending_maritime_hold_teu": self._maritime_hold_teu,
            "ending_customs_hold_teu": self._customs_hold_teu,
            "ending_released_recovery_teu": self._released_recovery_teu,
            "ending_reefer_thermal_debt": self._reefer_thermal_debt,
            "ending_maintenance_debt": self._maintenance_debt,
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
        if name in HYBRID_ENVIRONMENT_PARAMETERS:
            return float(HYBRID_ENVIRONMENT_PARAMETERS[name])
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
        if self.environment_id in DEPLOYMENT_ENVIRONMENTS:
            availability *= float(
                np.clip(
                    self._row_value("shore_power_compatible_ratio"),
                    0.0,
                    1.0,
                )
            )
        demand = self._row_value("vessels_at_berth") * per_vessel
        if self.environment_id in FLEXIBLE_ENVIRONMENTS:
            reservation = self._row_value("shore_power_reserved_kw", capacity)
            demand = min(demand, reservation)
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
        if self.environment_id in OPERATIONAL_ENVIRONMENTS:
            values.extend(
                self._row_value(name) / self._operational_normalizers.get(name, 1.0)
                for name in OPERATIONAL_OBSERVATION_KEYS
            )
        if self.environment_id in DEPLOYMENT_ENVIRONMENTS:
            values.extend(
                self._row_value(name) / self._operational_normalizers.get(name, 1.0)
                for name in DEPLOYMENT_OBSERVATION_KEYS
            )
        if self.environment_id in REGULATORY_ENVIRONMENTS:
            values.extend(
                self._row_value(name) / self._operational_normalizers.get(name, 1.0)
                for name in REGULATORY_DATA_KEYS
            )
            values.extend(
                (
                    self._maritime_hold_teu / 5_000.0,
                    self._customs_hold_teu / 5_000.0,
                    self._released_recovery_teu / 5_000.0,
                    self._last_inspection_readiness_ratio,
                    self._last_recovery_priority_ratio,
                )
            )
        if self.environment_id in FLEXIBLE_ENVIRONMENTS:
            values.extend(
                self._row_value(name) / self._operational_normalizers.get(name, 1.0)
                for name in FLEXIBLE_OPERATIONS_DATA_KEYS
            )
            values.extend(
                (
                    self._reefer_thermal_debt
                    / max(0.01, self._parameter("reefer_thermal_debt_limit")),
                    self._last_agv_charging_ratio,
                    self._last_reefer_service_ratio,
                    self._last_building_flexible_load_ratio,
                    self._last_demand_response_ratio,
                )
            )
        if self.environment_id == "PortEnergyHybridResidualEnv-v6":
            from app.rl.hybrid_control import FastFeasibleControlPolicy

            values.extend(
                self._row_value(name) / self._operational_normalizers.get(name, 1.0)
                for name in HYBRID_OPERATIONS_DATA_KEYS
            )
            values.extend(
                (
                    self._maintenance_debt,
                    *(
                        self._last_hybrid_priorities[key]
                        for key in (
                            "jit_arrival_priority",
                            "green_berth_priority",
                            "crane_task_priority",
                            "yard_slotting_priority",
                            "truck_gate_priority",
                            "maintenance_priority",
                        )
                    ),
                )
            )
            reference = FastFeasibleControlPolicy().predict(self)
            values.extend(
                (
                    reference["shore_power_ratio"],
                    (reference["crane_ratio"] - 0.60) / 0.40,
                    (reference["yard_ratio"] - 0.60) / 0.40,
                    (reference["battery_power_ratio"] + 1.0) / 2.0,
                    reference["inspection_readiness_ratio"],
                    reference["recovery_priority_ratio"],
                    reference["agv_charging_ratio"],
                    (reference["reefer_service_ratio"] - 0.75) / 0.25,
                    (reference["building_flexible_load_ratio"] - 0.35) / 0.65,
                    reference["demand_response_ratio"],
                )
            )
        observation = np.array(values, dtype=np.float32)
        return np.clip(observation, 0.0, 1.5)

    def _calculate_transition(self, controls: dict[str, float]) -> dict[str, Any]:
        row = self._row()
        base_demand_teu = self._demand_teu()
        regulatory = self.environment_id in REGULATORY_ENVIRONMENTS
        flexible = self.environment_id in FLEXIBLE_ENVIRONMENTS
        hybrid = self.environment_id == "PortEnergyHybridResidualEnv-v6"
        hybrid_priorities = {
            key: float(np.clip(controls.get(key, 0.5), 0.0, 1.0))
            for key in (
                "jit_arrival_priority",
                "green_berth_priority",
                "crane_task_priority",
                "yard_slotting_priority",
                "truck_gate_priority",
                "maintenance_priority",
            )
        }
        maintenance_due = self._row_value("maintenance_due_ratio") if hybrid else 0.0
        maintenance_resource = (
            self._row_value("maintenance_resource_available_ratio") if hybrid else 0.0
        )
        maintenance_performed_ratio = (
            hybrid_priorities["maintenance_priority"] * maintenance_resource
            if hybrid
            else 0.0
        )
        maintenance_debt = (
            float(
                np.clip(
                    self._maintenance_debt
                    + 0.12 * maintenance_due
                    - 0.18 * maintenance_performed_ratio,
                    0.0,
                    1.5,
                )
            )
            if hybrid
            else 0.0
        )
        hybrid_solver_projection_l1 = float(
            controls.get("hybrid_solver_projection_l1", 0.0)
        )
        hybrid_solver_constraint_violations = int(
            controls.get("hybrid_solver_constraint_violations", 0.0) > 0.0
        )
        inspection_readiness_ratio = float(
            np.clip(controls.get("inspection_readiness_ratio", 0.5), 0.0, 1.0)
        )
        recovery_priority_ratio = float(
            np.clip(controls.get("recovery_priority_ratio", 0.5), 0.0, 1.0)
        )
        maritime_inspection_arrivals_teu = 0.0
        customs_inspection_arrivals_teu = 0.0
        maritime_released_teu = 0.0
        customs_released_teu = 0.0
        maritime_hold_queue_teu = 0.0
        customs_hold_queue_teu = 0.0
        released_recovery_available_teu = 0.0
        if regulatory:
            maritime_ratio = float(np.clip(self._row_value("maritime_inspection_ratio"), 0, 1))
            customs_ratio = float(np.clip(self._row_value("customs_inspection_ratio"), 0, 1))
            combined_ratio = maritime_ratio + customs_ratio
            if combined_ratio > 0.85:
                maritime_ratio *= 0.85 / combined_ratio
                customs_ratio *= 0.85 / combined_ratio
            maritime_inspection_arrivals_teu = base_demand_teu * maritime_ratio
            customs_inspection_arrivals_teu = base_demand_teu * customs_ratio
            maritime_hold_before_release = (
                self._maritime_hold_teu + maritime_inspection_arrivals_teu
            )
            customs_hold_before_release = self._customs_hold_teu + customs_inspection_arrivals_teu
            maritime_released_teu = maritime_hold_before_release * float(
                np.clip(self._row_value("maritime_release_ratio"), 0, 1)
            )
            customs_released_teu = customs_hold_before_release * float(
                np.clip(self._row_value("customs_release_ratio"), 0, 1)
            )
            maritime_hold_queue_teu = max(
                0.0, maritime_hold_before_release - maritime_released_teu
            )
            customs_hold_queue_teu = max(
                0.0, customs_hold_before_release - customs_released_teu
            )
            released_recovery_available_teu = (
                self._released_recovery_teu
                + maritime_released_teu
                + customs_released_teu
            )
        regular_demand_teu = (
            base_demand_teu
            - maritime_inspection_arrivals_teu
            - customs_inspection_arrivals_teu
            + self._queue_teu
        )
        demand_teu = regular_demand_teu + released_recovery_available_teu
        crane_availability = (
            float(
                np.clip(
                    self._row_value("crane_available_ratio", 1.0),
                    0.0,
                    1.0,
                )
            )
            if self.environment_id in DEPLOYMENT_ENVIRONMENTS
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
            if self.environment_id in DEPLOYMENT_ENVIRONMENTS
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
            if self.environment_id in DEPLOYMENT_ENVIRONMENTS
            else 1.0
        )
        crane_availability *= berth_availability
        yard_availability *= berth_availability
        if flexible:
            health = float(np.clip(self._row_value("equipment_health_ratio"), 0.0, 1.0))
            maintenance = float(
                np.clip(self._row_value("maintenance_window_active"), 0.0, 1.0)
            )
            crane_availability *= health * (1.0 - 0.20 * maintenance)
            yard_availability *= health * (1.0 - 0.15 * maintenance)
        if hybrid:
            # Maintenance temporarily consumes capacity; the solver priorities
            # recover avoidable idle/rehandle losses without exceeding the
            # terminal-approved availability envelope.
            crane_availability *= 1.0 - 0.08 * maintenance_performed_ratio
            yard_availability *= 1.0 - 0.06 * maintenance_performed_ratio
            crane_availability *= 0.92 + 0.08 * hybrid_priorities["crane_task_priority"]
            yard_availability *= 0.92 + 0.08 * hybrid_priorities["yard_slotting_priority"]
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
        joint_capacity = min(crane_capacity, yard_capacity)
        inspection_resource_available_ratio = (
            float(np.clip(self._row_value("inspection_resource_available_ratio"), 0, 1))
            if regulatory
            else 0.0
        )
        readiness_capacity_teu = (
            self._parameter("released_staging_capacity_teu_per_hour")
            * inspection_resource_available_ratio
            * (0.20 + 0.80 * inspection_readiness_ratio)
            if regulatory
            else 0.0
        )
        recovery_capacity_teu = (
            joint_capacity
            * self._parameter("recovery_capacity_ratio")
            * recovery_priority_ratio
            if regulatory
            else 0.0
        )
        processed_recovery_teu = min(
            released_recovery_available_teu,
            readiness_capacity_teu,
            recovery_capacity_teu,
            joint_capacity,
        )
        processed_regular_teu = min(
            regular_demand_teu, max(0.0, joint_capacity - processed_recovery_teu)
        )
        processed_teu = processed_regular_teu + processed_recovery_teu
        queue_teu = max(0.0, regular_demand_teu - processed_regular_teu)
        released_recovery_queue_teu = max(
            0.0, released_recovery_available_teu - processed_recovery_teu
        )
        operational_delay_minutes = queue_teu / max(1.0, joint_capacity) * 60.0
        regulatory_delay_minutes = (
            (
                maritime_hold_queue_teu
                + customs_hold_queue_teu
                + released_recovery_queue_teu
            )
            / max(1.0, base_demand_teu)
            * 60.0
            if regulatory
            else 0.0
        )
        delay_minutes = operational_delay_minutes + regulatory_delay_minutes
        jit_deviation_hours = (
            self._row_value("arrival_uncertainty_hours")
            * (1.0 - hybrid_priorities["jit_arrival_priority"])
            if hybrid
            else 0.0
        )
        berth_conflict_hours = (
            self._row_value("berth_conflict_ratio")
            * (1.0 - hybrid_priorities["green_berth_priority"])
            if hybrid
            else 0.0
        )
        crane_task_late_teu = (
            self._row_value("crane_task_backlog_teu")
            * (1.0 - hybrid_priorities["crane_task_priority"])
            if hybrid
            else 0.0
        )
        yard_rehandles_teu = (
            base_demand_teu
            * self._row_value("yard_rehandle_ratio")
            * (1.0 - 0.50 * hybrid_priorities["yard_slotting_priority"])
            if hybrid
            else 0.0
        )
        truck_queue_teu_hours = (
            self._row_value("truck_gate_queue_teu")
            * (1.0 - 0.55 * hybrid_priorities["truck_gate_priority"])
            if hybrid
            else 0.0
        )
        if hybrid:
            delay_minutes += (
                berth_conflict_hours * 60.0
                + crane_task_late_teu / max(1.0, crane_capacity) * 60.0
                + truck_queue_teu_hours
                / max(1.0, self._row_value("truck_gate_capacity_teu_per_hour"))
                * 60.0
            )

        shore_demand_kw = self._shore_power_opportunity_kw()
        if hybrid:
            shore_demand_kw *= 0.85 + 0.15 * hybrid_priorities["green_berth_priority"]
        shore_power_kwh = shore_demand_kw * controls["shore_power_ratio"]
        regulatory_auxiliary_energy_kwh = (
            (maritime_hold_queue_teu + customs_hold_queue_teu)
            * self._parameter("inspection_auxiliary_kwh_per_teu_hour")
            if regulatory
            else 0.0
        )
        auxiliary_energy_kwh = (
            shore_demand_kw - shore_power_kwh + regulatory_auxiliary_energy_kwh
        )
        auxiliary_fuel_liters = auxiliary_energy_kwh / max(
            0.001, self._parameter("fuel_kwh_per_liter")
        )
        anchorage_auxiliary_fuel_liters = (
            self._row_value("anchorage_auxiliary_fuel_l_per_hour")
            * (1.0 - 0.35 * hybrid_priorities["jit_arrival_priority"])
            if hybrid
            else 0.0
        )
        auxiliary_fuel_liters += anchorage_auxiliary_fuel_liters
        auxiliary_energy_kwh += anchorage_auxiliary_fuel_liters * self._parameter(
            "fuel_kwh_per_liter"
        )
        base_load_kw = self._parameter("base_load_kw") + processed_teu * self._parameter(
            "load_kw_per_teu"
        )
        crane_load_kw = self._parameter("crane_load_kw") * controls["crane_ratio"]
        yard_load_kw = self._parameter("yard_load_kw") * controls["yard_ratio"]
        regulatory_event_active = regulatory and bool(
            maritime_inspection_arrivals_teu
            + customs_inspection_arrivals_teu
            + released_recovery_available_teu
        )
        inspection_readiness_energy_kwh = (
            self._parameter("inspection_readiness_load_kw") * inspection_readiness_ratio
            if regulatory_event_active
            else 0.0
        )
        recovery_energy_kwh = (
            self._parameter("regulatory_recovery_load_kw")
            * processed_recovery_teu
            / max(1.0, readiness_capacity_teu)
            if processed_recovery_teu > 0
            else 0.0
        )
        agv_charge_demand_kwh = (
            min(
                self._row_value("agv_charge_demand_kwh"),
                self._parameter("agv_charger_capacity_kw")
                * float(np.clip(self._row_value("charger_available_ratio"), 0.0, 1.0))
                * float(np.clip(self._row_value("agv_fleet_available_ratio"), 0.0, 1.0)),
            )
            if flexible
            else 0.0
        )
        agv_required_kwh = (
            min(
                agv_charge_demand_kwh,
                self._row_value("agv_departure_requirement_kwh"),
            )
            if flexible
            else 0.0
        )
        requested_agv_kwh = (
            agv_charge_demand_kwh
            * float(np.clip(controls.get("agv_charging_ratio", 1.0), 0.0, 1.0))
            if flexible
            else 0.0
        )
        # Departure energy is a hard service obligation. RL may move optional
        # charging but cannot intentionally undercharge vehicles that are due.
        agv_charged_kwh = max(agv_required_kwh, requested_agv_kwh)
        agv_missed_required_kwh = max(0.0, agv_required_kwh - agv_charged_kwh)

        reefer_baseline_load_kw = (
            self._row_value("reefer_baseline_load_kw") if flexible else 0.0
        )
        minimum_reefer_service = (
            self._parameter("reefer_minimum_service_ratio") if flexible else 1.0
        )
        requested_reefer_service = float(
            np.clip(
                controls.get("reefer_service_ratio", 1.0),
                minimum_reefer_service,
                1.0,
            )
        )
        # A low temperature margin or accumulated thermal debt forces full
        # service; this is an action shield, not a reward trade-off.
        reefer_force_full_service = bool(
            flexible
            and (
                self._row_value("reefer_thermal_margin_c") <= 0.75
                or self._reefer_thermal_debt
                >= 0.75 * self._parameter("reefer_thermal_debt_limit")
            )
        )
        reefer_service_ratio = 1.0 if reefer_force_full_service else requested_reefer_service
        reefer_energy_kwh = reefer_baseline_load_kw * reefer_service_ratio
        reefer_thermal_debt = (
            max(
                0.0,
                self._reefer_thermal_debt
                + max(0.0, 1.0 - reefer_service_ratio) * 0.50
                - max(0.0, reefer_service_ratio - 0.90)
                * self._parameter("reefer_thermal_recovery_rate"),
            )
            if flexible
            else 0.0
        )

        building_critical_load_kw = (
            self._row_value("building_critical_load_kw") if flexible else 0.0
        )
        building_flexible_load_kw = (
            self._row_value("building_flexible_load_kw") if flexible else 0.0
        )
        building_flexible_ratio = float(
            np.clip(
                controls.get("building_flexible_load_ratio", 1.0),
                self._parameter("building_minimum_flexible_load_ratio") if flexible else 1.0,
                1.0,
            )
        )
        building_energy_kwh = (
            building_critical_load_kw
            + building_flexible_load_kw * building_flexible_ratio
        )
        full_flexible_energy_kwh = (
            agv_charge_demand_kwh + reefer_baseline_load_kw + building_flexible_load_kw
        )
        scheduled_flexible_energy_kwh = (
            agv_charged_kwh
            + reefer_energy_kwh
            + building_flexible_load_kw * building_flexible_ratio
        )
        demand_response_active = bool(
            flexible and self._row_value("demand_response_active") >= 0.5
        )
        demand_response_ratio = float(
            np.clip(controls.get("demand_response_ratio", 0.0), 0.0, 1.0)
        )
        demand_response_target_kwh = (
            self._row_value("demand_response_target_kw") * demand_response_ratio
            if demand_response_active
            else 0.0
        )
        natural_flexible_reduction_kwh = max(
            0.0, full_flexible_energy_kwh - scheduled_flexible_energy_kwh
        )
        remaining_response_kwh = max(
            0.0, demand_response_target_kwh - natural_flexible_reduction_kwh
        )
        # Demand response first trims non-critical building demand, then AGV
        # charging above the departure obligation. Refrigerated-container and
        # building-critical loads are never response resources.
        building_response_headroom = max(
            0.0,
            building_flexible_load_kw
            * (
                building_flexible_ratio
                - self._parameter("building_minimum_flexible_load_ratio")
            ),
        )
        building_response_kwh = min(remaining_response_kwh, building_response_headroom)
        building_energy_kwh -= building_response_kwh
        remaining_response_kwh -= building_response_kwh
        agv_response_headroom = max(0.0, agv_charged_kwh - agv_required_kwh)
        agv_response_kwh = min(remaining_response_kwh, agv_response_headroom)
        agv_charged_kwh -= agv_response_kwh
        demand_response_delivered_kwh = min(
            demand_response_target_kwh,
            natural_flexible_reduction_kwh + building_response_kwh + agv_response_kwh,
        )
        demand_response_non_delivery_kwh = max(
            0.0, demand_response_target_kwh - demand_response_delivered_kwh
        )
        flexible_load_projection_kwh = (
            abs(requested_agv_kwh - agv_charged_kwh)
            + abs(requested_reefer_service - reefer_service_ratio)
            * reefer_baseline_load_kw
            + building_response_kwh
            if flexible
            else 0.0
        )
        equipment_health_ratio = (
            float(np.clip(self._row_value("equipment_health_ratio"), 0.0, 1.0))
            if flexible
            else 1.0
        )
        equipment_health_projection = int(
            flexible
            and max(controls["crane_ratio"], controls["yard_ratio"])
            > max(0.60, equipment_health_ratio)
        )
        gross_load_kw = (
            base_load_kw
            + crane_load_kw
            + yard_load_kw
            + shore_power_kwh
            + inspection_readiness_energy_kwh
            + recovery_energy_kwh
            + agv_charged_kwh
            + reefer_energy_kwh
            + building_energy_kwh
        )
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
            if self.environment_id in DEPLOYMENT_ENVIRONMENTS
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
            + (
                self._parameter("inspection_readiness_load_kw")
                + self._parameter("regulatory_recovery_load_kw")
                if regulatory
                else 0.0
            )
            + (
                self._parameter("agv_charger_capacity_kw")
                + self._row_value("reefer_baseline_load_kw")
                + self._row_value("building_critical_load_kw")
                + self._row_value("building_flexible_load_kw")
                if flexible
                else 0.0
            )
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
        # Grid capacity outranks the terminal-SOC preference. If the immutable
        # critical/service load would otherwise exceed the import limit, force
        # the minimum available discharge and record the projection. The policy
        # must restore SOC later; it may never trade an immediate grid breach
        # for a softer terminal objective.
        emergency_grid_discharge_kwh = min(
            max(0.0, gross_load_kw - grid_capacity_kw), available_discharge
        )
        if not flexible and emergency_grid_discharge_kwh > battery_discharge_kwh:
            battery_discharge_kwh = emergency_grid_discharge_kwh
            battery_charge_kwh = 0.0
            next_battery_soc = float(
                np.clip(
                    self._battery_soc
                    - battery_discharge_kwh
                    / (discharge_efficiency * battery_capacity),
                    min_soc,
                    max_soc,
                )
            )
        remaining_grid_excess_kwh = max(
            0.0,
            gross_load_kw + battery_charge_kwh - battery_discharge_kwh - grid_capacity_kw,
        )
        grid_projection_kwh = 0.0
        if flexible and remaining_grid_excess_kwh > 0.0:
            minimum_building_energy = (
                building_critical_load_kw
                + building_flexible_load_kw
                * self._parameter("building_minimum_flexible_load_ratio")
            )
            building_grid_reduction = min(
                remaining_grid_excess_kwh,
                max(0.0, building_energy_kwh - minimum_building_energy),
            )
            building_energy_kwh -= building_grid_reduction
            gross_load_kw -= building_grid_reduction
            remaining_grid_excess_kwh -= building_grid_reduction

            agv_grid_reduction = min(
                remaining_grid_excess_kwh, max(0.0, agv_charged_kwh - agv_required_kwh)
            )
            agv_charged_kwh -= agv_grid_reduction
            gross_load_kw -= agv_grid_reduction
            remaining_grid_excess_kwh -= agv_grid_reduction

            minimum_reefer_energy = reefer_baseline_load_kw * minimum_reefer_service
            reefer_grid_reduction = min(
                remaining_grid_excess_kwh,
                0.0
                if reefer_force_full_service
                else max(0.0, reefer_energy_kwh - minimum_reefer_energy),
            )
            reefer_energy_kwh -= reefer_grid_reduction
            gross_load_kw -= reefer_grid_reduction
            remaining_grid_excess_kwh -= reefer_grid_reduction
            if reefer_baseline_load_kw > 0:
                reefer_service_ratio = reefer_energy_kwh / reefer_baseline_load_kw
                reefer_thermal_debt = max(
                    reefer_thermal_debt,
                    self._reefer_thermal_debt
                    + max(0.0, 1.0 - reefer_service_ratio) * 0.50,
                )

            # Shore power is lower priority than the immutable import limit.
            # Curtailment is explicitly transferred back to auxiliary fuel so
            # neither energy nor carbon disappears from the ledger.
            shore_grid_reduction = min(remaining_grid_excess_kwh, shore_power_kwh)
            shore_power_kwh -= shore_grid_reduction
            auxiliary_energy_kwh += shore_grid_reduction
            auxiliary_fuel_liters += shore_grid_reduction / max(
                0.001, self._parameter("fuel_kwh_per_liter")
            )
            gross_load_kw -= shore_grid_reduction
            remaining_grid_excess_kwh -= shore_grid_reduction
            grid_projection_kwh = (
                building_grid_reduction
                + agv_grid_reduction
                + reefer_grid_reduction
                + shore_grid_reduction
            )
            flexible_load_projection_kwh += grid_projection_kwh
            if building_flexible_load_kw > 0:
                building_flexible_ratio = float(
                    np.clip(
                        (building_energy_kwh - building_critical_load_kw)
                        / building_flexible_load_kw,
                        self._parameter("building_minimum_flexible_load_ratio"),
                        1.0,
                    )
                )
            if demand_response_active:
                response_credit = min(
                    max(0.0, demand_response_target_kwh - demand_response_delivered_kwh),
                    building_grid_reduction + agv_grid_reduction,
                )
                demand_response_delivered_kwh += response_credit
                demand_response_non_delivery_kwh = max(
                    0.0, demand_response_target_kwh - demand_response_delivered_kwh
                )
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
        reefer_thermal_violation = int(
            flexible
            and reefer_thermal_debt > self._parameter("reefer_thermal_debt_limit")
        )
        agv_departure_violation = int(flexible and agv_missed_required_kwh > 1e-6)
        maintenance_safety_violation = int(
            hybrid and maintenance_due >= 0.95 and maintenance_debt > 1.0
        )
        safety_violations = (
            int(
                peak_violation
                or terminal_soc_violation
                or reefer_thermal_violation
                or agv_departure_violation
                or hybrid_solver_constraint_violations
                or maintenance_safety_violation
            )
            if hybrid
            else int(
                peak_violation
                or delay_violation
                or terminal_soc_violation
                or reefer_thermal_violation
                or agv_departure_violation
            )
        )

        renewable_power_kw = (
            self._row_value("renewable_power_available_kw")
            if self.environment_id in DEPLOYMENT_ENVIRONMENTS
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
        demand_response_non_delivery_cost_cny = (
            demand_response_non_delivery_kwh
            * self._parameter("demand_response_non_delivery_cny_per_kwh")
        )
        agv_missed_energy_cost_cny = (
            agv_missed_required_kwh * self._parameter("agv_missed_energy_cny_per_kwh")
        )
        reefer_safety_cost_cny = (
            max(0.0, reefer_thermal_debt - 0.5)
            * self._parameter("reefer_safety_cny_per_degree_hour")
        )
        maintenance_overdue_hours = (
            max(0.0, maintenance_debt - 0.75) if hybrid else 0.0
        )
        hybrid_operations_cost_cny = (
            jit_deviation_hours * self._parameter("jit_deviation_cost_cny_per_hour")
            + berth_conflict_hours
            * self._parameter("berth_conflict_cost_cny_per_hour")
            + crane_task_late_teu
            * self._parameter("crane_task_lateness_cny_per_teu")
            + yard_rehandles_teu * self._parameter("yard_rehandle_cost_cny_per_teu")
            + truck_queue_teu_hours
            * self._parameter("truck_queue_cost_cny_per_teu_hour")
            + maintenance_overdue_hours
            * self._parameter("maintenance_overdue_cost_cny_per_hour")
            if hybrid
            else 0.0
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
            + demand_response_non_delivery_cost_cny
            + agv_missed_energy_cost_cny
            + reefer_safety_cost_cny
            + hybrid_operations_cost_cny
        )
        terms = {
            "carbon": -carbon_kg / 6_000.0,
            "shore_power": shore_power_kwh / max(1.0, shore_demand_kw),
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
        if flexible:
            terms.update(
                agv_service=(
                    agv_charged_kwh / max(1.0, agv_charge_demand_kwh)
                    if agv_charge_demand_kwh > 0
                    else 1.0
                ),
                reefer_safety=-reefer_thermal_debt
                / max(0.01, self._parameter("reefer_thermal_debt_limit")),
                demand_response=(
                    demand_response_delivered_kwh
                    / max(1.0, demand_response_target_kwh)
                    if demand_response_target_kwh > 0
                    else 1.0
                ),
                equipment_health=-(
                    controls["crane_ratio"] * self._row_value("crane_fault_risk")
                    + controls["yard_ratio"] * self._row_value("yard_fault_risk")
                )
                / 2.0,
            )
        if hybrid:
            anchor_baseline = self._row_value("anchorage_auxiliary_fuel_l_per_hour")
            terms.update(
                jit_service=-0.5
                * (
                    jit_deviation_hours
                    / max(1.0, self._row_value("arrival_uncertainty_hours"))
                    + anchorage_auxiliary_fuel_liters / max(1.0, anchor_baseline)
                ),
                green_berth=-berth_conflict_hours,
                crane_schedule=-crane_task_late_teu
                / max(1.0, self._row_value("crane_task_backlog_teu")),
                yard_slotting=-yard_rehandles_teu / max(1.0, base_demand_teu),
                truck_flow=-truck_queue_teu_hours
                / max(1.0, self._row_value("truck_gate_queue_teu")),
                maintenance_risk=-0.5
                * (
                    maintenance_debt
                    + self._row_value("failure_risk_forecast")
                    * (1.0 - maintenance_performed_ratio)
                ),
            )
        throughput_bonus = 0.65 * processed_teu / max(1.0, demand_teu)
        regulatory_service_bonus = (
            0.20
            * processed_recovery_teu
            / max(1.0, released_recovery_available_teu)
            if regulatory
            else 0.0
        )
        reward = throughput_bonus + regulatory_service_bonus + sum(
            self.reward_weights.get(key, 0.0) * value for key, value in terms.items()
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
            "shore_power_ratio": float(shore_power_kwh / max(1.0, shore_demand_kw)),
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
            "demand_response_non_delivery_cost_cny": float(
                demand_response_non_delivery_cost_cny
            ),
            "agv_missed_energy_cost_cny": float(agv_missed_energy_cost_cny),
            "reefer_safety_cost_cny": float(reefer_safety_cost_cny),
            "hybrid_operations_cost_cny": float(hybrid_operations_cost_cny),
            "crane_activation_ratio_sum": float(controls["crane_ratio"]),
            "yard_activation_ratio_sum": float(controls["yard_ratio"]),
            "maritime_inspection_arrivals_teu": float(maritime_inspection_arrivals_teu),
            "customs_inspection_arrivals_teu": float(customs_inspection_arrivals_teu),
            "maritime_released_teu": float(maritime_released_teu),
            "customs_released_teu": float(customs_released_teu),
            "maritime_hold_queue_teu": float(maritime_hold_queue_teu),
            "customs_hold_queue_teu": float(customs_hold_queue_teu),
            "released_recovery_queue_teu": float(released_recovery_queue_teu),
            "processed_recovery_teu": float(processed_recovery_teu),
            "regulatory_delay_minutes": float(regulatory_delay_minutes),
            "regulatory_auxiliary_energy_kwh": float(regulatory_auxiliary_energy_kwh),
            "inspection_readiness_energy_kwh": float(inspection_readiness_energy_kwh),
            "recovery_energy_kwh": float(recovery_energy_kwh),
            "inspection_readiness_ratio_sum": inspection_readiness_ratio if regulatory else 0.0,
            "recovery_priority_ratio_sum": recovery_priority_ratio if regulatory else 0.0,
            "agv_charge_demand_kwh": float(agv_charge_demand_kwh),
            "agv_charged_kwh": float(agv_charged_kwh),
            "agv_missed_required_kwh": float(agv_missed_required_kwh),
            "reefer_energy_kwh": float(reefer_energy_kwh),
            "reefer_thermal_debt": float(reefer_thermal_debt),
            "reefer_thermal_violation_steps": float(reefer_thermal_violation),
            "building_energy_kwh": float(building_energy_kwh),
            "demand_response_target_kwh": float(demand_response_target_kwh),
            "demand_response_delivered_kwh": float(demand_response_delivered_kwh),
            "demand_response_non_delivery_kwh": float(
                demand_response_non_delivery_kwh
            ),
            "flexible_load_projection_kwh": float(flexible_load_projection_kwh),
            "equipment_health_projection_steps": float(equipment_health_projection),
            "hybrid_solver_projection_l1": hybrid_solver_projection_l1,
            "hybrid_solver_constraint_violations": float(
                hybrid_solver_constraint_violations
            ),
            "jit_deviation_hours": float(jit_deviation_hours),
            "anchorage_auxiliary_fuel_liters": float(
                anchorage_auxiliary_fuel_liters
            ),
            "berth_conflict_hours": float(berth_conflict_hours),
            "crane_task_late_teu": float(crane_task_late_teu),
            "yard_rehandles_teu": float(yard_rehandles_teu),
            "truck_queue_teu_hours": float(truck_queue_teu_hours),
            "maintenance_overdue_hours": float(maintenance_overdue_hours),
            "maintenance_performed_ratio": float(maintenance_performed_ratio),
            "maintenance_debt": float(maintenance_debt),
            "agv_charging_ratio": float(controls.get("agv_charging_ratio", 1.0)),
            "reefer_service_ratio": float(reefer_service_ratio),
            "building_flexible_load_ratio": float(building_flexible_ratio),
            "demand_response_ratio": float(demand_response_ratio),
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
            if self.environment_id
            in {
                "PortEnergyDispatchEnv-v2",
                "PortEnergyDispatchEnv-v4",
                "PortEnergyDispatchEnv-v5",
                "PortEnergyHybridResidualEnv-v6",
            }
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
            if self.environment_id
            in {
                "PortEnergyDispatchEnv-v2",
                "PortEnergyDispatchEnv-v4",
                "PortEnergyDispatchEnv-v5",
                "PortEnergyHybridResidualEnv-v6",
            }
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
            "maritime_hold_queue_teu": round(
                float(transition["maritime_hold_queue_teu"]), 3
            ),
            "customs_hold_queue_teu": round(
                float(transition["customs_hold_queue_teu"]), 3
            ),
            "released_recovery_queue_teu": round(
                float(transition["released_recovery_queue_teu"]), 3
            ),
            "processed_recovery_teu": round(float(transition["processed_recovery_teu"]), 3),
            "regulatory_delay_minutes": round(
                float(transition["regulatory_delay_minutes"]), 3
            ),
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
                f"queue={float(transition['queue_teu']):.1f}TEU, "
                f"regulatory_hold="
                f"{float(transition['maritime_hold_queue_teu']) + float(transition['customs_hold_queue_teu']):.1f}TEU"
            ),
        }

    def _normalize_weights(self, weights: dict[str, float]) -> dict[str, float]:
        allowed = (
            set(DEFAULT_HYBRID_REWARD_WEIGHTS)
            if self.environment_id == "PortEnergyHybridResidualEnv-v6"
            else set(DEFAULT_FLEX_REWARD_WEIGHTS)
            if self.environment_id == "PortEnergyDispatchEnv-v5"
            else set(DEFAULT_REWARD_WEIGHTS)
        )
        unknown = set(weights) - allowed
        if unknown:
            raise ValueError(f"Unknown reward weights: {', '.join(sorted(unknown))}")
        selected = {key: max(0.0, float(value)) for key, value in weights.items()}
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
        if env.environment_id in FLEXIBLE_ENVIRONMENTS:
            flexible_controls = self._flexible_controls(env)
            actions = [{**controls, **flexible_controls} for controls in actions]
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
        selected = min(
            beam,
            key=lambda item: item[0] + self.terminal_soc_weight * abs(item[2] - target_soc),
        )[3]
        if env.environment_id in REGULATORY_ENVIRONMENTS:
            selected = {
                **selected,
                "inspection_readiness_ratio": 0.5,
                "recovery_priority_ratio": 0.5,
            }
        if env.environment_id == "PortEnergyHybridResidualEnv-v6":
            from app.rl.hybrid_control import HybridOperationsSolver

            requested = {
                "jit_arrival_priority": env._row_value("jit_window_feasible_ratio"),
                "green_berth_priority": 1.0
                - env._row_value("berth_conflict_ratio"),
                "crane_task_priority": env._row_value(
                    "crane_precedence_pressure_ratio"
                ),
                "yard_slotting_priority": 1.0
                - env._row_value("yard_rehandle_ratio"),
                "truck_gate_priority": env._row_value(
                    "truck_appointment_pressure_ratio"
                ),
                "maintenance_priority": env._row_value("maintenance_due_ratio"),
            }
            projected = HybridOperationsSolver().project(env, requested)
            selected = {
                **selected,
                **projected.realized,
                "hybrid_solver_projection_l1": projected.projection_l1,
                "hybrid_solver_constraint_violations": float(
                    projected.hard_constraint_violations
                ),
            }
        return selected

    @staticmethod
    def _flexible_controls(env: PortEnergyDispatchEnv) -> dict[str, float]:
        price = float(env._row()["electricity_price_per_kwh"])
        carbon = float(env._row()["grid_carbon_kg_per_kwh"])
        charge_demand = env._row_value("agv_charge_demand_kwh")
        departure_ratio = env._row_value("agv_departure_requirement_kwh") / max(
            1.0, charge_demand
        )
        constrained = price >= 2.0 or carbon >= 0.45
        thermal_margin = env._row_value("reefer_thermal_margin_c")
        response_active = env._row_value("demand_response_active") >= 0.5
        return {
            "agv_charging_ratio": 1.0
            if departure_ratio >= 0.70 or not constrained
            else max(0.40, departure_ratio),
            "reefer_service_ratio": 1.0
            if thermal_margin <= 1.0
            else 0.80
            if constrained
            else 1.0,
            "building_flexible_load_ratio": 0.35
            if response_active
            else 0.55
            if constrained
            else 1.0,
            "demand_response_ratio": 1.0 if response_active else 0.0,
        }

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
        controls = dict(self.controls)
        if env.environment_id in REGULATORY_ENVIRONMENTS:
            controls.update(
                inspection_readiness_ratio=0.35,
                recovery_priority_ratio=0.35,
            )
        if env.environment_id in FLEXIBLE_ENVIRONMENTS:
            controls.update(
                agv_charging_ratio=1.0,
                reefer_service_ratio=1.0,
                building_flexible_load_ratio=1.0,
                demand_response_ratio=0.0,
            )
        if env.environment_id == "PortEnergyHybridResidualEnv-v6":
            from app.rl.hybrid_control import HybridOperationsSolver

            projected = HybridOperationsSolver().project(
                env,
                {
                    "jit_arrival_priority": 0.5,
                    "green_berth_priority": 0.5,
                    "crane_task_priority": 0.5,
                    "yard_slotting_priority": 0.5,
                    "truck_gate_priority": 0.5,
                    "maintenance_priority": 0.5,
                },
            )
            controls.update(
                projected.realized,
                hybrid_solver_projection_l1=projected.projection_l1,
                hybrid_solver_constraint_violations=float(
                    projected.hard_constraint_violations
                ),
            )
        return controls


class RegulatoryResiliencePolicy:
    """Auditable non-learning comparator for inspection-release recovery.

    Authority inspection and release signals remain exogenous. The policy only
    allocates terminal readiness, cargo-recovery effort, equipment and storage.
    """

    def predict(self, env: PortEnergyDispatchEnv) -> dict[str, float]:
        release_pressure = float(
            np.clip(
                env._row_value("maritime_release_ratio")
                + env._row_value("customs_release_ratio"),
                0.0,
                1.0,
            )
        )
        hold_pressure = float(
            np.clip(
                (env._maritime_hold_teu + env._customs_hold_teu) / 2_000.0,
                0.0,
                1.0,
            )
        )
        recovery_pressure = float(
            np.clip(env._released_recovery_teu / 1_500.0, 0.0, 1.0)
        )
        readiness = float(np.clip(0.30 + 0.45 * hold_pressure + 0.25 * release_pressure, 0, 1))
        recovery = float(np.clip(0.25 + 0.65 * recovery_pressure + 0.10 * release_pressure, 0, 1))
        resource_ratio = float(np.clip(0.72 + 0.25 * max(recovery, hold_pressure), 0.60, 1.0))
        price = float(env._row()["electricity_price_per_kwh"])
        carbon = float(env._row()["grid_carbon_kg_per_kwh"])
        battery = 0.45 if (price > 2.0 or carbon > 0.45) else -0.20 if price < 1.2 else 0.0
        return {
            "shore_power_ratio": 1.0,
            "crane_ratio": resource_ratio,
            "yard_ratio": resource_ratio,
            "battery_power_ratio": battery,
            "inspection_readiness_ratio": readiness,
            "recovery_priority_ratio": recovery,
        }


def encode_continuous_controls(controls: dict[str, float]) -> np.ndarray:
    values = [
            controls["shore_power_ratio"] * 2.0 - 1.0,
            (controls["crane_ratio"] - 0.60) / 0.20 - 1.0,
            (controls["yard_ratio"] - 0.60) / 0.20 - 1.0,
            controls.get("battery_power_ratio", 0.0),
    ]
    if "inspection_readiness_ratio" in controls or "recovery_priority_ratio" in controls:
        values.extend(
            [
                controls.get("inspection_readiness_ratio", 0.5) * 2.0 - 1.0,
                controls.get("recovery_priority_ratio", 0.5) * 2.0 - 1.0,
            ]
        )
    if "agv_charging_ratio" in controls or "reefer_service_ratio" in controls:
        reefer_minimum = 0.75
        building_minimum = 0.35
        values.extend(
            [
                controls.get("agv_charging_ratio", 1.0) * 2.0 - 1.0,
                (controls.get("reefer_service_ratio", 1.0) - reefer_minimum)
                / (1.0 - reefer_minimum)
                * 2.0
                - 1.0,
                (controls.get("building_flexible_load_ratio", 1.0) - building_minimum)
                / (1.0 - building_minimum)
                * 2.0
                - 1.0,
                controls.get("demand_response_ratio", 0.0) * 2.0 - 1.0,
            ]
        )
    return np.array(values, dtype=np.float32)
