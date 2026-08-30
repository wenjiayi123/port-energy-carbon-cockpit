from __future__ import annotations

from typing import Any

from app.rl.business_scope import business_scope_contract
from app.rl.hybrid_control import HYBRID_ACTION_KEYS, HYBRID_PRIORITY_KEYS


V6_DATASET_ID = "port_la_2020_2024_hybrid_rl_hourly"
V6_ENVIRONMENT_ID = "PortEnergyHybridResidualEnv-v6"

RESIDUAL_CONTROL_DOMAINS = {
    "shore_power_dispatch",
    "battery_dispatch",
    "agv_charging",
    "reefer_flex",
    "building_flex",
    "demand_response",
}
RL_TOS_ENVELOPE_DOMAINS = {
    "crane_resource_envelope",
    "yard_resource_envelope",
    "inspection_readiness",
    "release_recovery",
}
RL_GUIDED_OR_DOMAINS = {
    "vessel_jit_arrival",
    "berth_assignment",
    "crane_task_schedule",
    "yard_slotting",
    "truck_appointments",
}


def hybrid_business_scope_contract() -> dict[str, Any]:
    base = business_scope_contract()
    domains: list[dict[str, str]] = []
    for item in base["domains"]:
        current = dict(item)
        domain = current["domain"]
        if domain in RESIDUAL_CONTROL_DOMAINS:
            current.update(
                decision_owner="residual_rl_plus_controller_and_hard_projection",
                implementation="v6 bounded residual action + deterministic controller",
                status="implemented_offline_v6",
            )
        elif domain in RL_TOS_ENVELOPE_DOMAINS:
            current.update(
                decision_owner="rl_strategy_plus_tos_capability_envelope",
                implementation="v6 bounded residual action + TOS envelope projection",
                status="implemented_offline_v6",
            )
        elif domain in RL_GUIDED_OR_DOMAINS:
            current.update(
                decision_owner="rl_priority_plus_constraint_optimizer",
                implementation=(
                    "v6 strategic priority + aggregate offline projection; "
                    "signed site records enter the named advisory planner"
                ),
                status="implemented_offline_v6",
            )
        domains.append(current)
    domains.append(
        {
            "domain": "predictive_maintenance_timing",
            "label_zh": "预测性检修时机",
            "decision_owner": "rl_risk_budget_plus_reliability_optimizer",
            "implementation": "v6 maintenance priority + statutory due-date projection",
            "status": "implemented_offline_v6",
            "production_input": "逐设备健康、故障概率、法定期限、备件、人员和锁定挂牌回执",
        }
    )
    strategy_domains = (
        RESIDUAL_CONTROL_DOMAINS
        | RL_TOS_ENVELOPE_DOMAINS
        | RL_GUIDED_OR_DOMAINS
        | {"predictive_maintenance_timing"}
    )
    pure_control_domains = {"electrical_power_flow"}
    return {
        "schema_version": "port-energy-hybrid-business-scope.v1",
        "dataset_id": V6_DATASET_ID,
        "environment_id": V6_ENVIRONMENT_ID,
        "domain_count": len(domains),
        "policy_output_count": len(HYBRID_ACTION_KEYS),
        "strategic_priority_count": len(HYBRID_PRIORITY_KEYS),
        "decision_counts": {
            "rl_or_hybrid_strategy": len(strategy_domains),
            "pure_control_or_physics": len(pure_control_domains),
            "deterministic_governance_authority_or_safety": len(domains)
            - len(strategy_domains)
            - len(pure_control_domains),
        },
        "algorithmic_decision_share": {
            "rl_or_hybrid_strategy": len(strategy_domains),
            "pure_control_or_physics": len(pure_control_domains),
            "rl_or_hybrid_pct": round(
                len(strategy_domains)
                / max(1, len(strategy_domains) + len(pure_control_domains))
                * 100.0,
                3,
            ),
        },
        "domains": domains,
        "rl_or_hybrid_domains": sorted(strategy_domains),
        "pure_control_domains": sorted(pure_control_domains),
        "non_negotiable_constraints": [
            *base["hard_constraints"],
            "vessel_berth_compatibility",
            "crane_task_precedence",
            "yard_slot_capacity",
            "truck_gate_capacity",
            "statutory_maintenance_due_date",
        ],
        "claim_boundary": base["claim_boundary"],
    }
