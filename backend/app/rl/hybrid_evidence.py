from __future__ import annotations

from typing import Any


DIRECT_DOMAIN_METRICS = {
    "vessel_jit_arrival": "jit_deviation_hours_reduction_pct",
    "berth_assignment": "berth_conflict_hours_reduction_pct",
    "crane_task_schedule": "crane_task_late_teu_reduction_pct",
    "yard_slotting": "yard_rehandles_teu_reduction_pct",
    "truck_appointments": "truck_queue_teu_hours_reduction_pct",
    "predictive_maintenance_timing": "maintenance_overdue_hours_reduction_pct",
}

SYSTEM_VALUE_METRICS = {
    "carbon": "carbon_kg_reduction_pct",
    "cost": "cost_reduction_pct",
    "throughput": "throughput_change_pct",
    "delay": "delay_minutes_reduction_pct",
    "peak": "peak_kw_reduction_pct",
    "shore_power": "shore_power_change_pct",
}


def _metric_summary(
    seed_results: list[dict[str, Any]], metric_key: str
) -> dict[str, Any]:
    values = [
        float(item.get("versus_mpc_or", {}).get(metric_key, 0.0))
        for item in seed_results
    ]
    return {
        "metric": metric_key,
        "values": values,
        "minimum": min(values) if values else None,
        "maximum": max(values) if values else None,
        "all_non_regression": bool(values) and all(value >= 0.0 for value in values),
        "all_strict_improvement": bool(values) and all(value > 0.0 for value in values),
    }


def summarize_hybrid_evidence(report: dict[str, Any]) -> dict[str, Any]:
    seed_results = list(report.get("seed_results") or [])
    direct_domains = {
        domain: _metric_summary(seed_results, metric)
        for domain, metric in DIRECT_DOMAIN_METRICS.items()
    }
    system_values = {
        name: _metric_summary(seed_results, metric)
        for name, metric in SYSTEM_VALUE_METRICS.items()
    }
    safe_across_seeds = bool(seed_results) and all(
        float(item.get("versus_mpc_or", {}).get("safety_violations", 1.0)) == 0.0
        and float(
            item.get("versus_mpc_or", {}).get(
                "solver_constraint_violations", 1.0
            )
        )
        == 0.0
        for item in seed_results
    )
    challenger_domains = [
        domain
        for domain, evidence in direct_domains.items()
        if evidence["all_strict_improvement"] and safe_across_seeds
    ]
    failed_checks = sorted(
        {
            check
            for item in seed_results
            for check in item.get("admission", {}).get("failed_checks", [])
        }
    )
    baseline_mean = report.get("baseline_mpc_or", {}).get("mean", {})
    control_baseline_safe = (
        float(baseline_mean.get("safety_violations", 1.0)) == 0.0
        and float(baseline_mean.get("hybrid_solver_constraint_violations", 1.0))
        == 0.0
    )
    rl_admitted = report.get("champion_status") == "admitted_offline"
    return {
        "schema_version": "hybrid-rl-evidence-summary.v1",
        "global_champion_status": report.get("champion_status"),
        "global_policy_admitted": rl_admitted,
        "control_baseline_safe": control_baseline_safe,
        "seed_count": len(seed_results),
        "safe_across_final_seeds": safe_across_seeds,
        "direct_domain_evidence": direct_domains,
        "system_value_evidence": system_values,
        "offline_domain_challengers": challenger_domains,
        "offline_domain_challenger_count": len(challenger_domains),
        "global_failed_checks": failed_checks,
        "decision": "admit_global_offline_rl_champion"
        if rl_admitted
        else (
            "retain_global_mpc_or_champion_and_keep_consistent_rl_domains_as_offline_challengers"
            if control_baseline_safe
            else "no_global_policy_admitted_keep_mpc_or_as_benchmark_and_rl_domains_as_offline_challengers"
        ),
        "production_eligible": False,
        "claim_boundary": (
            "Consistent domain gains are not causal ablations and do not authorize "
            "production dispatch; named site shadow trials remain required."
        ),
    }
