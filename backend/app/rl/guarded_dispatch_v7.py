"""Causal MPC retains authority unless a learned proposal earns admission."""
from __future__ import annotations

from typing import Any

from app.rl.dispatch_policy_v7 import DispatchPolicyV7
from app.rl.environment import MPCPolicy
from app.rl.hybrid_control import RESOURCE_CONTROL_KEYS


class GuardedDispatchPolicyV7:
    def __init__(self, weights=None, controller=None):
        self.learner = DispatchPolicyV7(weights)
        self.controller = controller or MPCPolicy()
        self.last_receipt: dict[str, Any] = {}

    @staticmethod
    def accepts(candidate, reference):
        minimize = (
            "cost", "carbon_kg", "load_kw", "delay_minutes", "safety_violations",
            "jit_deviation_hours", "anchorage_auxiliary_fuel_liters",
            "berth_conflict_hours", "crane_task_late_teu", "yard_rehandles_teu",
            "truck_queue_teu_hours", "maintenance_overdue_hours",
            "demand_response_non_delivery_kwh", "reefer_thermal_debt", "maintenance_debt",
            "queue_teu", "released_recovery_queue_teu",
        )
        maximize = ("processed_teu", "shore_power_kwh", "demand_response_target_kwh", "battery_soc")
        return (
            candidate["safety_violations"] == 0
            and all(candidate[k] <= reference[k] + 1e-8 for k in minimize)
            and all(candidate[k] >= reference[k] - 1e-8 for k in maximize)
            and candidate["cost"] < reference["cost"] - 1e-6
        )

    def predict(self, env):
        reference = self.controller.predict(env)
        before = env.preview_transition(reference)
        proposal = self.learner.predict(env)
        # Both complete proposals and resource-only proposals use the same
        # business certificate. This finite solver is also applied to ablations.
        local = {**reference, **{k: proposal[k] for k in RESOURCE_CONTROL_KEYS}}
        accepted = []
        for controls in (proposal, local):
            result = env.preview_transition(controls)
            if self.accepts(result, before):
                accepted.append((result["cost"], controls))
        chosen = min(accepted, key=lambda item: item[0])[1] if accepted else reference
        self.last_receipt = {
            "fallback": not bool(accepted),
            "reason": "learned_proposal_certified" if accepted else "causal_mpc_fallback",
            "learned_control_delta": sum(abs(chosen[k] - reference[k]) for k in RESOURCE_CONTROL_KEYS),
            "accepted_proposals": len(accepted),
        }
        return chosen
