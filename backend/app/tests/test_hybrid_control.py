from __future__ import annotations

import numpy as np
import pandas as pd

from app.rl.hybrid_control import (
    HYBRID_ACTION_KEYS,
    HYBRID_PRIORITY_KEYS,
    FastFeasibleControlPolicy,
    HybridOperationsSolver,
    decode_hybrid_action,
)
from app.rl.hybrid_evidence import summarize_hybrid_evidence
from app.rl.hybrid_benchmark import _episode, admission


class DummyHybridEnv:
    def __init__(self) -> None:
        self._battery_soc = 0.58
        self._queue_teu = 900.0
        self._maritime_hold_teu = 250.0
        self._customs_hold_teu = 150.0
        self._released_recovery_teu = 400.0
        self.rows = [
            pd.Series(
                {
                    "electricity_price_per_kwh": 2.2,
                    "grid_carbon_kg_per_kwh": 0.48,
                }
            ),
            pd.Series(
                {
                    "electricity_price_per_kwh": 1.4,
                    "grid_carbon_kg_per_kwh": 0.36,
                }
            ),
        ]
        self.values = {
            "equipment_health_ratio": 0.92,
            "agv_charge_demand_kwh": 1_000.0,
            "agv_departure_requirement_kwh": 750.0,
            "reefer_thermal_margin_c": 1.4,
            "demand_response_active": 1.0,
            "jit_window_feasible_ratio": 0.70,
            "pilot_tug_readiness_ratio": 0.60,
            "green_berth_candidate_ratio": 0.90,
            "berth_conflict_ratio": 0.20,
            "crane_available_ratio": 0.80,
            "crane_precedence_pressure_ratio": 0.70,
            "yard_available_ratio": 0.90,
            "yard_slot_capacity_ratio": 0.75,
            "truck_gate_capacity_teu_per_hour": 800.0,
            "truck_gate_queue_teu": 400.0,
            "maintenance_resource_available_ratio": 0.65,
            "maintenance_due_ratio": 0.90,
        }

    def _parameter(self, name: str) -> float:
        values = {"battery_initial_soc": 0.50}
        return values[name]

    def _row(self) -> pd.Series:
        return self.rows[0]

    def _row_at(self, hour_offset: int) -> pd.Series:
        return self.rows[min(1, hour_offset)]

    def _row_value(self, name: str, default: float = 0.0) -> float:
        return float(self.values.get(name, default))


def test_fast_controller_is_causal_and_service_aware() -> None:
    controls = FastFeasibleControlPolicy().predict(DummyHybridEnv())
    assert controls["shore_power_ratio"] == 1.0
    assert controls["battery_power_ratio"] > 0.0
    assert controls["agv_charging_ratio"] == 1.0
    assert controls["demand_response_ratio"] == 1.0


def test_hybrid_solver_projects_every_priority_to_feasible_cap() -> None:
    result = HybridOperationsSolver().project(
        DummyHybridEnv(), {key: 1.0 for key in HYBRID_PRIORITY_KEYS}
    )
    assert result.hard_constraint_violations == 0
    assert result.projection_l1 > 0.0
    assert result.realized["jit_arrival_priority"] == 0.60
    assert result.realized["maintenance_priority"] == 0.65
    assert all(0.0 <= value <= 1.0 for value in result.realized.values())


def test_zero_residual_uses_controller_and_solver_not_raw_actuation() -> None:
    env = DummyHybridEnv()
    action = np.zeros(len(HYBRID_ACTION_KEYS), dtype=np.float32)
    controls, result = decode_hybrid_action(env, action)
    reference = FastFeasibleControlPolicy().predict(env)
    for key, value in reference.items():
        assert controls[key] == value
    assert controls["jit_arrival_priority"] == 0.50
    assert result.hard_constraint_violations == 0


def test_hybrid_admission_requires_both_residual_and_strategy_contribution() -> None:
    comparison = {
        "safety_violations": 0.0,
        "solver_constraint_violations": 0.0,
        "carbon_kg_reduction_pct": 1.0,
        "cost_reduction_pct": 1.0,
        "throughput_change_pct": 0.0,
        "delay_minutes_reduction_pct": 1.0,
        "peak_kw_reduction_pct": 1.0,
        "shore_power_change_pct": 0.0,
        "reward_change": 0.1,
        "agv_missed_required_kwh": 0.0,
        "reefer_thermal_violation_steps": 0.0,
        "demand_response_delivery_pct": 100.0,
        "demand_response_commitment_pct": 100.0,
        "jit_deviation_hours_reduction_pct": 1.0,
        "anchorage_auxiliary_fuel_liters_reduction_pct": 1.0,
        "berth_conflict_hours_reduction_pct": 1.0,
        "crane_task_late_teu_reduction_pct": 1.0,
        "yard_rehandles_teu_reduction_pct": 1.0,
        "truck_queue_teu_hours_reduction_pct": 1.0,
        "maintenance_overdue_hours_reduction_pct": 0.0,
        "carbon_kg_reduction_ci95": {"ci95_low_pct": 0.1},
        "cost_reduction_ci95": {"ci95_low_pct": 0.1},
        "rl_residual_contribution_pct": 2.0,
        "rl_strategy_contribution_pct": 0.5,
    }
    blocked = admission(comparison)
    assert blocked["status"] == "blocked"
    assert blocked["checks"]["material_residual_rl_contribution"] is True
    assert blocked["checks"]["material_strategy_rl_contribution"] is False

    comparison["rl_strategy_contribution_pct"] = 2.0
    assert admission(comparison)["status"] == "admitted_offline"


def test_neutral_policy_does_not_claim_solver_projection_as_rl_contribution() -> None:
    class NeutralPolicy:
        def predict(self, observation, deterministic: bool = True):
            del observation, deterministic
            return np.zeros(len(HYBRID_ACTION_KEYS), dtype=np.float32), None

    summary = _episode("rl", None, "ppo", np.int64(0), 7, model=NeutralPolicy())
    assert summary["rl_residual_contribution_pct"] == 0.0
    assert summary["rl_strategy_request_deviation_pct"] == 0.0
    assert summary["rl_strategy_contribution_pct"] == 0.0


def test_hybrid_evidence_only_promotes_consistent_domains_as_challengers() -> None:
    def seed(crane: float, truck: float, yard: float) -> dict:
        comparison = {
            "safety_violations": 0.0,
            "solver_constraint_violations": 0.0,
            "crane_task_late_teu_reduction_pct": crane,
            "truck_queue_teu_hours_reduction_pct": truck,
            "yard_rehandles_teu_reduction_pct": yard,
        }
        return {
            "versus_mpc_or": comparison,
            "admission": {"failed_checks": ["carbon_non_regression"]},
        }

    report = {
        "champion_status": "no_rl_policy_admitted",
        "baseline_mpc_or": {
            "mean": {
                "safety_violations": 0.25,
                "hybrid_solver_constraint_violations": 0.0,
            }
        },
        "seed_results": [seed(50.0, 5.0, -1.0), seed(51.0, 6.0, 2.0), seed(52.0, 7.0, 3.0)],
    }
    summary = summarize_hybrid_evidence(report)
    assert summary["global_policy_admitted"] is False
    assert summary["control_baseline_safe"] is False
    assert summary["safe_across_final_seeds"] is True
    assert summary["offline_domain_challengers"] == [
        "crane_task_schedule",
        "truck_appointments",
    ]
    assert summary["global_failed_checks"] == ["carbon_non_regression"]
    assert summary["decision"].startswith("no_global_policy_admitted")
