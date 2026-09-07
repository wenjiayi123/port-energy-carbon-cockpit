"""Additive, portable policy-search RL with an explicit service contract.

The v6 physics and its published artifacts are deliberately unchanged. CEM
optimizes episode returns from actual sequential simulator transitions; this is
not behavior cloning, a neural SB3 policy, or evidence of physical dispatch.
"""
from __future__ import annotations

from typing import Any

import numpy as np

from app.rl.environment import MPCPolicy
from app.rl.hybrid_control import HYBRID_PRIORITY_KEYS, HybridOperationsSolver
from app.rl.robust import CausalForecastPortEnv


DATASET_ID = "port_la_2020_2024_hybrid_rl_hourly"
FEATURES = (
    "bias", "price", "carbon", "demand", "queue", "recovery_queue",
    "battery_soc", "hour_sin", "hour_cos", "remaining_horizon", "health",
)
OUTPUTS = ("crane", "yard", "inspection", "recovery", "battery")
SHAPE = (len(OUTPUTS), len(FEATURES))
BOUNDARY = {
    "simulation_mode": True, "live_data_verified": False,
    "dispatch_allowed": False, "production_authority": False,
}


class CachedCausalEnv(CausalForecastPortEnv):
    """Memoize row lookup only; retain the original causal forecast/physics.

    Each cache belongs to one immutable split. Never reuse it after editing frame.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._row_cache: dict[int, Any] = {}
        super().__init__(*args, **kwargs)

    def _row_at(self, hour_offset: int):
        hour = self._hour
        if self.temporal_mode == "sequential_rows":
            if self._preview_origin_hour is not None:
                hour = self._preview_origin_hour
            elif int(hour_offset) <= 0:
                hour += int(hour_offset)
            index = min(len(self.frame) - 1, self._row_index + hour)
        else:
            index = self._row_index
        if index not in self._row_cache:
            self._row_cache[index] = self.frame.iloc[index]
        return self._row_cache[index]


class DispatchEnvV7(CachedCausalEnv):
    """Correct roundoff classification without changing limits or energy flows."""

    def _calculate_transition(self, controls: dict[str, float]) -> dict[str, Any]:
        result = super()._calculate_transition(controls)
        capacity = self._parameter("grid_capacity_kw") * float(np.clip(
            self._row_value("grid_available_ratio", 1.0), 0.0, 1.0,
        ))
        tolerance = 32.0 * np.spacing(max(1.0, capacity))
        excess = result["peak_violation_kw"]
        if 0.0 < excess <= tolerance:
            result["numerical_peak_roundoff_kw"] = excess
            result["peak_violation_steps"] = 0.0
            remaining_violation = bool(
                result["soc_violation_steps"]
                or result["reefer_thermal_violation_steps"]
                or result["agv_missed_required_kwh"] > 1e-6
                or result["hybrid_solver_constraint_violations"]
                or (self._row_value("maintenance_due_ratio") >= 0.95
                    and result["maintenance_debt"] > 1.0)
            )
            if result["safety_violations"] and not remaining_violation:
                result["safety_violations"] = 0.0
                result["reward_terms"]["safety"] = 0.0
                result["reward"] += 4.0 * self.reward_weights.get("safety", 0.0)
        return result


def features(env: CausalForecastPortEnv) -> np.ndarray:
    row = env._row()
    # Prices/carbon are current observations. Clock and remaining horizon are
    # known at issue time; no future measurements or test normalizers are used.
    hour = int(str(row["timestamp_utc"])[11:13])
    return np.array([
        1.0, float(row["electricity_price_per_kwh"]) / 2.0 - 1.0,
        float(row["grid_carbon_kg_per_kwh"]) / 0.4 - 1.0,
        env._demand_teu() / env._parameter("crane_capacity_teu_per_hour"),
        env._queue_teu / 2500.0, env._released_recovery_teu / 1500.0,
        (env._battery_soc - env._parameter("battery_initial_soc")) * 4.0,
        np.sin(hour * np.pi / 12.0), np.cos(hour * np.pi / 12.0),
        (env.episode_hours - env._hour) / env.episode_hours,
        env._row_value("equipment_health_ratio", 1.0),
    ], dtype=np.float64).clip(-3.0, 3.0)


def service_reference(env: CausalForecastPortEnv) -> dict[str, float]:
    """Explicit non-learning comparator, also the fallback for invalid input."""
    priorities = {key: 1.0 for key in HYBRID_PRIORITY_KEYS}
    # Maintenance incurs real capacity cost; service follows due work/debt.
    resource = env._row_value("maintenance_resource_available_ratio")
    priorities["maintenance_priority"] = min(
        1.0, (env._row_value("maintenance_due_ratio") * 2.0 / 3.0
              + env._maintenance_debt) / max(resource, 1e-6)
    )
    projected = HybridOperationsSolver().project(env, priorities)
    return {
        "shore_power_ratio": 1.0,
        "crane_ratio": 1.0, "yard_ratio": 1.0,
        "battery_power_ratio": 0.0,
        "inspection_readiness_ratio": 1.0, "recovery_priority_ratio": 1.0,
        **MPCPolicy._flexible_controls(env), **projected.realized,
        "hybrid_solver_projection_l1": projected.projection_l1,
        "hybrid_solver_constraint_violations": float(projected.hard_constraint_violations),
    }


class DispatchPolicyV7:
    def __init__(self, weights: np.ndarray | None = None) -> None:
        self.weights = np.zeros(SHAPE) if weights is None else np.asarray(weights, dtype=float)
        if self.weights.shape != SHAPE or not np.isfinite(self.weights).all():
            raise ValueError("Invalid v7 policy coefficients")
        self.last_receipt: dict[str, Any] = {}

    def predict(self, env: CausalForecastPortEnv) -> dict[str, float]:
        reference = service_reference(env)
        x = features(env)
        if not np.isfinite(x).all():
            self.last_receipt = {"fallback": True, "reason": "nonfinite_features"}
            return reference
        signal = np.tanh(self.weights @ x)
        requested = {
            **reference,
            "crane_ratio": float(np.clip(1.0 + 0.4 * signal[0], 0.6, 1.0)),
            "yard_ratio": float(np.clip(1.0 + 0.4 * signal[1], 0.6, 1.0)),
            "inspection_readiness_ratio": float(np.clip(1.0 + signal[2], 0.0, 1.0)),
            "recovery_priority_ratio": float(np.clip(1.0 + signal[3], 0.0, 1.0)),
            "battery_power_ratio": float(signal[4]),
        }
        # A candidate cannot reduce same-state throughput or increase service
        # queues to manufacture energy savings. This certificate uses only the
        # current calibrated transition; it is not a field safety interlock.
        baseline = env.preview_transition(reference)
        candidate = env.preview_transition(requested)
        service_ok = (
            candidate["processed_teu"] >= baseline["processed_teu"] - 1e-8
            and candidate["delay_minutes"] <= baseline["delay_minutes"] + 1e-8
            and candidate["safety_violations"] <= baseline["safety_violations"]
            and candidate["shore_power_kwh"] >= baseline["shore_power_kwh"] - 1e-8
        )
        if not service_ok:
            # Preserve learned storage when a resource request alone is invalid.
            battery_only = {**reference, "battery_power_ratio": requested["battery_power_ratio"]}
            projected = env.preview_transition(battery_only)
            battery_safe = (
                projected["safety_violations"] <= baseline["safety_violations"]
                and projected["shore_power_kwh"] >= baseline["shore_power_kwh"] - 1e-8
            )
            requested = battery_only if battery_safe else reference
        self.last_receipt = {
            "fallback": not service_ok,
            "reason": "service_projection" if not service_ok else "accepted",
            "requested_signal": signal.tolist(),
            "learned_control_delta": float(sum(abs(requested[k] - reference[k]) for k in (
                "crane_ratio", "yard_ratio", "inspection_readiness_ratio",
                "recovery_priority_ratio", "battery_power_ratio",
            ))),
        }
        return requested


def episode(env: CausalForecastPortEnv, policy: Any, start: int) -> dict[str, Any]:
    env.reset(seed=20260907 + start, options={"row_index": start})
    projections = 0
    contribution = 0.0
    for _ in range(env.episode_hours):
        action = policy.predict(env)
        env.step(action)
        receipt = getattr(policy, "last_receipt", {})
        projections += int(receipt.get("fallback", False))
        contribution += float(receipt.get("learned_control_delta", 0.0))
    result = env.summary()
    # Settle any terminal inventory difference at a deliberately conservative
    # replacement price. Raw cost remains visible next to this adjustment.
    inventory_kwh = (env._parameter("battery_initial_soc") - env._battery_soc) * (
        env._parameter("battery_capacity_kwh")
    )
    result["terminal_energy_debt_kwh"] = max(0.0, inventory_kwh)
    result["settled_cost"] = result["cost"] + max(0.0, inventory_kwh) * 4.0
    return {
        **result, "start_index": int(start),
        "service_projection_steps": projections,
        "learned_control_delta_sum": contribution,
    }


def objective(result: dict[str, Any]) -> float:
    # CNY-equivalent engineering objective. Safety is lexicographically dominant;
    # thermal debt at the horizon is priced to prevent unbilled service borrowing.
    return -(
        result["settled_cost"] + 0.5 * result["carbon_kg"]
        + 100_000_000.0 * result["safety_violations"]
        + 1000.0 * result["demand_response_non_delivery_kwh"]
    ) / 100_000.0
