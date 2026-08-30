from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol

import numpy as np


class HybridEnvironmentView(Protocol):
    _battery_soc: float
    _customs_hold_teu: float
    _maritime_hold_teu: float
    _queue_teu: float
    _released_recovery_teu: float

    def _parameter(self, name: str) -> float: ...

    def _row(self) -> Any: ...

    def _row_at(self, hour_offset: int) -> Any: ...

    def _row_value(self, name: str, default: float = 0.0) -> float: ...


RESOURCE_CONTROL_KEYS = (
    "shore_power_ratio",
    "crane_ratio",
    "yard_ratio",
    "battery_power_ratio",
    "inspection_readiness_ratio",
    "recovery_priority_ratio",
    "agv_charging_ratio",
    "reefer_service_ratio",
    "building_flexible_load_ratio",
    "demand_response_ratio",
)
HYBRID_PRIORITY_KEYS = (
    "jit_arrival_priority",
    "green_berth_priority",
    "crane_task_priority",
    "yard_slotting_priority",
    "truck_gate_priority",
    "maintenance_priority",
)
HYBRID_ACTION_KEYS = RESOURCE_CONTROL_KEYS + HYBRID_PRIORITY_KEYS

CONTROL_BOUNDS = {
    "shore_power_ratio": (0.0, 1.0),
    "crane_ratio": (0.60, 1.0),
    "yard_ratio": (0.60, 1.0),
    "battery_power_ratio": (-1.0, 1.0),
    "inspection_readiness_ratio": (0.0, 1.0),
    "recovery_priority_ratio": (0.0, 1.0),
    "agv_charging_ratio": (0.0, 1.0),
    "reefer_service_ratio": (0.75, 1.0),
    "building_flexible_load_ratio": (0.35, 1.0),
    "demand_response_ratio": (0.0, 1.0),
}
RESIDUAL_TRUST_BOUNDS = {
    "shore_power_ratio": 0.08,
    "crane_ratio": 0.12,
    "yard_ratio": 0.12,
    "battery_power_ratio": 0.45,
    "inspection_readiness_ratio": 0.25,
    "recovery_priority_ratio": 0.25,
    "agv_charging_ratio": 0.25,
    "reefer_service_ratio": 0.10,
    "building_flexible_load_ratio": 0.20,
    "demand_response_ratio": 0.20,
}


class FastFeasibleControlPolicy:
    """Cheap causal controller used as the v6 residual-policy reference.

    It is intentionally auditable and does not access future test outcomes.
    The controller handles obvious service obligations; RL learns only bounded
    deviations and cross-hour/cross-domain trade-offs.
    """

    def predict(self, env: HybridEnvironmentView) -> dict[str, float]:
        row = env._row()
        price = float(row["electricity_price_per_kwh"])
        carbon = float(row["grid_carbon_kg_per_kwh"])
        future = [env._row_at(offset) for offset in (1, 2, 3)]
        future_price = float(
            np.mean([float(item["electricity_price_per_kwh"]) for item in future])
        )
        future_carbon = float(
            np.mean([float(item["grid_carbon_kg_per_kwh"]) for item in future])
        )
        queue_pressure = float(np.clip(env._queue_teu / 2_500.0, 0.0, 1.0))
        recovery_pressure = float(
            np.clip(env._released_recovery_teu / 1_500.0, 0.0, 1.0)
        )
        hold_pressure = float(
            np.clip((env._maritime_hold_teu + env._customs_hold_teu) / 2_000.0, 0.0, 1.0)
        )
        health = float(np.clip(env._row_value("equipment_health_ratio", 1.0), 0.0, 1.0))
        high_signal = price > future_price * 1.08 or carbon > future_carbon * 1.08
        low_signal = price < future_price * 0.92 and carbon < future_carbon * 1.02
        if high_signal and env._battery_soc > env._parameter("battery_initial_soc") - 0.08:
            battery = 0.45
        elif low_signal and env._battery_soc < env._parameter("battery_initial_soc") + 0.10:
            battery = -0.35
        else:
            battery = 0.0

        charge_demand = env._row_value("agv_charge_demand_kwh")
        departure_ratio = env._row_value("agv_departure_requirement_kwh") / max(
            1.0, charge_demand
        )
        thermal_margin = env._row_value("reefer_thermal_margin_c")
        response_active = env._row_value("demand_response_active") >= 0.5
        constrained = high_signal or response_active
        return {
            "shore_power_ratio": 1.0,
            "crane_ratio": float(np.clip(0.72 + 0.24 * queue_pressure, 0.60, health)),
            "yard_ratio": float(
                np.clip(0.72 + 0.20 * max(queue_pressure, recovery_pressure), 0.60, health)
            ),
            "battery_power_ratio": battery,
            "inspection_readiness_ratio": float(
                np.clip(0.30 + 0.55 * hold_pressure, 0.0, 1.0)
            ),
            "recovery_priority_ratio": float(
                np.clip(0.25 + 0.70 * recovery_pressure, 0.0, 1.0)
            ),
            "agv_charging_ratio": float(
                1.0 if departure_ratio >= 0.70 or not constrained else max(0.40, departure_ratio)
            ),
            "reefer_service_ratio": float(
                1.0 if thermal_margin <= 1.0 else 0.82 if constrained else 1.0
            ),
            "building_flexible_load_ratio": float(
                0.35 if response_active else 0.58 if constrained else 1.0
            ),
            "demand_response_ratio": 1.0 if response_active else 0.0,
        }


def apply_bounded_residual(
    reference: Mapping[str, float], residual_action: np.ndarray
) -> dict[str, float]:
    vector = np.asarray(residual_action, dtype=np.float32).reshape(len(RESOURCE_CONTROL_KEYS))
    vector = np.clip(vector, -1.0, 1.0)
    controls: dict[str, float] = {}
    for index, key in enumerate(RESOURCE_CONTROL_KEYS):
        lower, upper = CONTROL_BOUNDS[key]
        value = float(reference[key]) + float(vector[index]) * RESIDUAL_TRUST_BOUNDS[key]
        controls[key] = float(np.clip(value, lower, upper))
    return controls


@dataclass(frozen=True)
class HybridSolverResult:
    requested: dict[str, float]
    realized: dict[str, float]
    projection_l1: float
    hard_constraint_violations: int


class HybridOperationsSolver:
    """Project strategic priorities into aggregate feasible solver outputs.

    The real-port implementation replaces this aggregate projection with
    constraint programming or mixed-integer optimization over named assets.
    """

    def project(
        self,
        env: HybridEnvironmentView,
        priorities: Mapping[str, float],
    ) -> HybridSolverResult:
        requested = {
            key: float(np.clip(priorities.get(key, 0.5), 0.0, 1.0))
            for key in HYBRID_PRIORITY_KEYS
        }
        jit_cap = min(
            env._row_value("jit_window_feasible_ratio"),
            env._row_value("pilot_tug_readiness_ratio"),
        )
        green_berth_cap = env._row_value("green_berth_candidate_ratio") * (
            1.0 - env._row_value("berth_conflict_ratio")
        )
        crane_cap = min(
            env._row_value("crane_available_ratio", 1.0),
            0.55 + 0.45 * env._row_value("crane_precedence_pressure_ratio"),
        )
        yard_cap = min(
            env._row_value("yard_available_ratio", 1.0),
            env._row_value("yard_slot_capacity_ratio"),
        )
        truck_capacity = env._row_value("truck_gate_capacity_teu_per_hour")
        truck_queue = env._row_value("truck_gate_queue_teu")
        truck_cap = min(
            1.0,
            truck_capacity / max(1.0, truck_capacity + truck_queue),
        )
        maintenance_cap = env._row_value("maintenance_resource_available_ratio")
        maintenance_floor = (
            min(maintenance_cap, env._row_value("maintenance_due_ratio"))
            if env._row_value("maintenance_due_ratio") >= 0.85
            else 0.0
        )
        caps = {
            "jit_arrival_priority": jit_cap,
            "green_berth_priority": green_berth_cap,
            "crane_task_priority": crane_cap,
            "yard_slotting_priority": yard_cap,
            "truck_gate_priority": truck_cap,
            "maintenance_priority": maintenance_cap,
        }
        realized = {
            key: float(np.clip(value, maintenance_floor if key == "maintenance_priority" else 0.0, caps[key]))
            for key, value in requested.items()
        }
        projection_l1 = float(
            sum(abs(realized[key] - requested[key]) for key in HYBRID_PRIORITY_KEYS)
        )
        return HybridSolverResult(
            requested=requested,
            realized=realized,
            projection_l1=projection_l1,
            hard_constraint_violations=0,
        )


def decode_hybrid_action(
    env: HybridEnvironmentView,
    action: np.ndarray,
    *,
    controller: FastFeasibleControlPolicy | None = None,
    solver: HybridOperationsSolver | None = None,
) -> tuple[dict[str, float], HybridSolverResult]:
    vector = np.asarray(action, dtype=np.float32).reshape(len(HYBRID_ACTION_KEYS))
    vector = np.clip(vector, -1.0, 1.0)
    reference = (controller or FastFeasibleControlPolicy()).predict(env)
    controls = apply_bounded_residual(reference, vector[: len(RESOURCE_CONTROL_KEYS)])
    priorities = {
        key: float((vector[index] + 1.0) / 2.0)
        for index, key in enumerate(
            HYBRID_PRIORITY_KEYS, start=len(RESOURCE_CONTROL_KEYS)
        )
    }
    result = (solver or HybridOperationsSolver()).project(env, priorities)
    return {**controls, **result.realized}, result
