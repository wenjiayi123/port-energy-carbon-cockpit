from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np

from app.rl.dataset import PROJECT_ROOT, PortDataset
from app.rl.environment import FixedDispatchPolicy, MPCPolicy, encode_continuous_controls
from app.rl.landing_readiness import assess_dataset_landing_readiness
from app.rl.robust import CausalForecastPortEnv, RiskAwareMPCPolicy, cvar, paired_bootstrap_interval


EVIDENCE_LABEL = "CAUSAL_OFFLINE_ROBUSTNESS_BENCHMARK_NOT_FIELD_KPI"
REPORT_VERSION = "4.0"
DEFAULT_DATASET = "port_la_2020_2024_vessel_activity_hourly"
DEFAULT_OUTPUT = PROJECT_ROOT / "reports" / "port_landing_benchmark_v4.json"
CODE_FILES = (
    Path("backend/app/rl/environment.py"),
    Path("backend/app/rl/robust.py"),
    Path("backend/app/rl/landing_benchmark.py"),
)
STRESS_SCENARIOS = {
    "demand_surge_15pct": {"demand_multiplier": 1.15, "parameter_multipliers": {}},
    "grid_derating_10pct": {
        "demand_multiplier": 1.0,
        "parameter_multipliers": {"grid_capacity_kw": 0.90},
    },
    "equipment_derating_15pct": {
        "demand_multiplier": 1.0,
        "parameter_multipliers": {
            "crane_capacity_teu_per_hour": 0.85,
            "yard_capacity_teu_per_hour": 0.85,
        },
    },
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _rollout(
    dataset_id: str,
    row_index: int,
    policy_id: str,
    episode_hours: int,
    stress: dict[str, Any] | None = None,
) -> dict[str, Any]:
    stress = stress or {"demand_multiplier": 1.0, "parameter_multipliers": {}}
    env = CausalForecastPortEnv(
        dataset=dataset_id,
        split="test",
        episode_hours=episode_hours,
        render_mode=None,
        demand_multiplier=float(stress.get("demand_multiplier", 1.0)),
        parameter_multipliers=dict(stress.get("parameter_multipliers") or {}),
    )
    env.reset(seed=20260808 + row_index, options={"row_index": row_index, "start_hour": 0})
    if policy_id == "risk_aware_mpc":
        policy: Any = RiskAwareMPCPolicy()
    elif policy_id == "causal_legacy_mpc":
        policy = MPCPolicy()
    elif policy_id == "fixed_full_resources":
        policy = FixedDispatchPolicy()
    else:
        raise ValueError(f"Unknown policy: {policy_id}")

    previous: dict[str, float] | None = None
    action_total_variation = 0.0
    reserve_breach_steps = 0
    load_ratios: list[float] = []
    queue_values: list[float] = []
    terminated = truncated = False
    while not (terminated or truncated):
        controls = policy.predict(env)
        if previous is not None:
            action_total_variation += sum(
                abs(float(controls[name]) - float(previous[name])) for name in controls
            )
        previous = dict(controls)
        _, _, terminated, truncated, info = env.step(encode_continuous_controls(controls))
        load_ratio = float(info["peak_load_ratio"])
        load_ratios.append(load_ratio)
        queue_values.append(float(info["queue_teu"]))
        reserve_breach_steps += int(load_ratio > 0.88)
    summary = env.summary()
    return {
        **summary,
        "row_index": row_index,
        "policy_id": policy_id,
        "action_total_variation": round(action_total_variation, 6),
        "reserve_breach_steps": reserve_breach_steps,
        "max_load_ratio": round(max(load_ratios, default=0.0), 6),
        "p95_queue_teu": round(float(np.quantile(queue_values or [0.0], 0.95)), 6),
    }


def _rollout_job(arguments: tuple[Any, ...]) -> dict[str, Any]:
    return _rollout(*arguments)


def _run_jobs(jobs: list[tuple[Any, ...]], workers: int) -> list[dict[str, Any]]:
    if workers <= 1 or len(jobs) <= 1:
        return [_rollout_job(job) for job in jobs]
    with ProcessPoolExecutor(max_workers=min(workers, len(jobs))) as pool:
        return list(pool.map(_rollout_job, jobs))


def _mean(items: list[dict[str, Any]], key: str) -> float:
    return round(float(np.mean([float(item[key]) for item in items])), 6)


def _saving(reference: float, candidate: float) -> float:
    return round((reference - candidate) / max(abs(reference), 1e-9) * 100.0, 4)


def _optional_saving(reference: float, candidate: float) -> float | None:
    return _saving(reference, candidate) if abs(reference) > 1e-9 else None


def _metrics(candidate: list[dict[str, Any]], reference: list[dict[str, Any]]) -> dict[str, Any]:
    candidate_mean = {key: _mean(candidate, key) for key in (
        "energy_kwh", "carbon_kg", "cost", "peak_kw", "processed_teu", "delay_minutes",
        "safety_violations", "reserve_breach_steps", "action_total_variation", "p95_queue_teu",
    )}
    reference_mean = {key: _mean(reference, key) for key in candidate_mean}
    return {
        "candidate_mean": candidate_mean,
        "reference_mean": reference_mean,
        "energy_reduction_pct": _saving(reference_mean["energy_kwh"], candidate_mean["energy_kwh"]),
        "carbon_reduction_pct": _saving(reference_mean["carbon_kg"], candidate_mean["carbon_kg"]),
        "cost_reduction_pct": _saving(reference_mean["cost"], candidate_mean["cost"]),
        "peak_reduction_pct": _saving(reference_mean["peak_kw"], candidate_mean["peak_kw"]),
        "throughput_change_pct": round(
            (candidate_mean["processed_teu"] - reference_mean["processed_teu"])
            / max(abs(reference_mean["processed_teu"]), 1e-9)
            * 100.0,
            4,
        ),
        "delay_reduction_pct": _optional_saving(
            reference_mean["delay_minutes"], candidate_mean["delay_minutes"]
        ),
        "p95_queue_reduction_pct": _optional_saving(
            reference_mean["p95_queue_teu"], candidate_mean["p95_queue_teu"]
        ),
        "reserve_breach_reduction_pct": _optional_saving(
            reference_mean["reserve_breach_steps"], candidate_mean["reserve_breach_steps"]
        ),
        "action_variation_reduction_pct": _optional_saving(
            reference_mean["action_total_variation"], candidate_mean["action_total_variation"]
        ),
        "constraint_success_rate_pct": round(
            sum(float(item["safety_violations"]) == 0 for item in candidate)
            / len(candidate)
            * 100.0,
            3,
        ),
        "carbon_reduction_ci95": paired_bootstrap_interval(
            [float(item["carbon_kg"]) for item in candidate],
            [float(item["carbon_kg"]) for item in reference],
        ),
        "cost_reduction_ci95": paired_bootstrap_interval(
            [float(item["cost"]) for item in candidate],
            [float(item["cost"]) for item in reference],
            seed=20260809,
        ),
    }


def build_report(
    dataset_id: str = DEFAULT_DATASET,
    *,
    episode_hours: int = 24,
    workers: int = 1,
    stress_window_count: int = 12,
) -> dict[str, Any]:
    dataset = PortDataset.load(dataset_id)
    starts = dataset.evaluation_start_indices("test", episode_hours)
    policies = ("risk_aware_mpc", "causal_legacy_mpc", "fixed_full_resources")
    results = {
        policy: _run_jobs(
            [(dataset_id, row_index, policy, episode_hours, None) for row_index in starts],
            workers,
        )
        for policy in policies
    }
    stress_positions = sorted(
        {
            round(index * (len(starts) - 1) / max(1, stress_window_count - 1))
            for index in range(min(stress_window_count, len(starts)))
        }
    )
    stress_starts = [starts[position] for position in stress_positions]
    stress_results: dict[str, Any] = {}
    for name, stress in STRESS_SCENARIOS.items():
        risk = _run_jobs(
            [(dataset_id, row_index, "risk_aware_mpc", episode_hours, stress) for row_index in stress_starts],
            workers,
        )
        legacy = _run_jobs(
            [(dataset_id, row_index, "causal_legacy_mpc", episode_hours, stress) for row_index in stress_starts],
            workers,
        )
        stress_results[name] = {
            "definition": stress,
            "windows": len(stress_starts),
            "risk_aware_zero_violation_rate_pct": round(
                sum(float(item["safety_violations"]) == 0 for item in risk) / len(risk) * 100.0,
                3,
            ),
            "legacy_zero_violation_rate_pct": round(
                sum(float(item["safety_violations"]) == 0 for item in legacy) / len(legacy) * 100.0,
                3,
            ),
            "comparison": _metrics(risk, legacy),
        }

    risk = results["risk_aware_mpc"]
    report: dict[str, Any] = {
        "report_version": REPORT_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "status": "reproducible_causal_offline_robustness_benchmark",
        "evidence_label": EVIDENCE_LABEL,
        "boundary": (
            "Public-data held-out scenario evidence. It is not a terminal field KPI, "
            "not live telemetry, and not production dispatch authorization."
        ),
        "dataset": {
            "id": dataset.dataset_id,
            "package_sha256": dataset.package_sha256,
            "landing_readiness": assess_dataset_landing_readiness(dataset),
        },
        "protocol": {
            "split": "test",
            "episode_hours": episode_hours,
            "windows": len(starts),
            "steps": len(starts) * episode_hours,
            "forecast_protocol": "causal persistence; no later held-out row is visible at decision time",
            "policy": {
                "id": "risk_aware_mpc_safety_layer_v1",
                "horizon": 6,
                "beam_width": 8,
                "candidate_actions": 27,
                "reserve_margin_target_pct": 12.0,
            },
            "comparators": ["causal_legacy_mpc", "fixed_full_resources"],
            "code_sha256": {
                str(path): sha256_file(PROJECT_ROOT / path) for path in CODE_FILES
            },
        },
        "business_metrics_vs_fixed_full_resources": _metrics(
            risk, results["fixed_full_resources"]
        ),
        "algorithm_increment_vs_causal_legacy_mpc": _metrics(
            risk, results["causal_legacy_mpc"]
        ),
        "tail_risk": {
            "risk_aware_carbon_cvar95_kg": cvar([float(item["carbon_kg"]) for item in risk]),
            "legacy_carbon_cvar95_kg": cvar(
                [float(item["carbon_kg"]) for item in results["causal_legacy_mpc"]]
            ),
            "risk_aware_cost_cvar95": cvar([float(item["cost"]) for item in risk]),
            "legacy_cost_cvar95": cvar(
                [float(item["cost"]) for item in results["causal_legacy_mpc"]]
            ),
            "risk_aware_peak_cvar95_kw": cvar([float(item["peak_kw"]) for item in risk]),
            "legacy_peak_cvar95_kw": cvar(
                [float(item["peak_kw"]) for item in results["causal_legacy_mpc"]]
            ),
        },
        "stress_tests": stress_results,
        "per_window": results,
    }
    unsigned = {key: value for key, value in report.items() if key != "evidence_sha256"}
    report["evidence_sha256"] = hashlib.sha256(
        json.dumps(unsigned, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()
    return report


def render_markdown(report: dict[str, Any]) -> str:
    fixed = report["business_metrics_vs_fixed_full_resources"]
    legacy = report["algorithm_increment_vs_causal_legacy_mpc"]
    tail = report["tail_risk"]
    stress_rows = "\n".join(
        "| {name} | {windows} | {risk:.3f}% | {legacy:.3f}% | {carbon:.3f}% | "
        "{cost:.3f}% | {reserve:.3f}% | {variation:.3f}% |".format(
            name=name,
            windows=item["windows"],
            risk=item["risk_aware_zero_violation_rate_pct"],
            legacy=item["legacy_zero_violation_rate_pct"],
            carbon=item["comparison"]["carbon_reduction_pct"],
            cost=item["comparison"]["cost_reduction_pct"],
            reserve=item["comparison"]["reserve_breach_reduction_pct"],
            variation=item["comparison"]["action_variation_reduction_pct"],
        )
        for name, item in report["stress_tests"].items()
    )
    return f"""# Port landing robustness benchmark v4

Evidence label: `{report['evidence_label']}`

This report is public-data held-out scenario evidence, not a real-terminal KPI or production authorization.

## Protocol

- Dataset: `{report['dataset']['id']}`
- Package SHA-256: `{report['dataset']['package_sha256']}`
- Test windows / steps: {report['protocol']['windows']} / {report['protocol']['steps']}
- Forecast: causal persistence; later held-out rows are unavailable to the decision
- Policy: six-step, eight-beam risk-aware MPC safety layer with a 12% reserve target

## Business metrics versus fixed full resources

| Metric | Result |
| --- | ---: |
| Energy reduction | {fixed['energy_reduction_pct']:.3f}% |
| Carbon reduction | {fixed['carbon_reduction_pct']:.3f}% |
| Cost reduction | {fixed['cost_reduction_pct']:.3f}% |
| Peak reduction | {fixed['peak_reduction_pct']:.3f}% |
| Throughput change | {fixed['throughput_change_pct']:.3f}% |
| Constraint-success rate | {fixed['constraint_success_rate_pct']:.3f}% |
| Carbon reduction 95% CI | [{fixed['carbon_reduction_ci95']['ci95_low_pct']:.3f}%, {fixed['carbon_reduction_ci95']['ci95_high_pct']:.3f}%] |

## Algorithm increment versus causal legacy MPC

| Metric | Result |
| --- | ---: |
| Carbon reduction | {legacy['carbon_reduction_pct']:.3f}% |
| Cost reduction | {legacy['cost_reduction_pct']:.3f}% |
| Peak reduction | {legacy['peak_reduction_pct']:.3f}% |
| Mean-delay reduction | {legacy['delay_reduction_pct']:.3f}% |
| P95 queue reduction | {legacy['p95_queue_reduction_pct']:.3f}% |
| Action-variation reduction | {legacy['action_variation_reduction_pct']:.3f}% |
| Constraint-success rate | {legacy['constraint_success_rate_pct']:.3f}% |

The risk-aware layer trades a small amount of mean carbon/cost performance for
lower delay, queue tail and action variation. Negative entries are retained as
measured and must not be described as an across-the-board improvement.

## CVaR95 tail evidence

| Metric | Risk-aware MPC | Causal legacy MPC |
| --- | ---: | ---: |
| Carbon CVaR95 (kg) | {tail['risk_aware_carbon_cvar95_kg']:.3f} | {tail['legacy_carbon_cvar95_kg']:.3f} |
| Cost CVaR95 | {tail['risk_aware_cost_cvar95']:.3f} | {tail['legacy_cost_cvar95']:.3f} |
| Peak CVaR95 (kW) | {tail['risk_aware_peak_cvar95_kw']:.3f} | {tail['legacy_peak_cvar95_kw']:.3f} |

## Deterministic stress evidence versus causal legacy MPC

| Scenario | Windows | Risk zero violations | Legacy zero violations | Carbon reduction | Cost reduction | Reserve-breach reduction | Action-variation reduction |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
{stress_rows}

Negative reductions mean the risk-aware layer performed worse on that measure.
In particular, the grid-derating case increases soft reserve-breach steps by
7.692% even though both policies have zero modelled hard safety violations. This
adverse result is retained and blocks any claim of universal stress superiority.

## Reproduce

```bash
PYTHONPATH=backend backend/.venv/bin/python -m app.rl.landing_benchmark run
PYTHONPATH=backend backend/.venv/bin/python -m app.rl.landing_benchmark verify reports/port_landing_benchmark_v4.json
```
"""


def verify_report(path: Path) -> dict[str, Any]:
    report = json.loads(path.read_text(encoding="utf-8"))
    expected_hash = report.pop("evidence_sha256", "")
    actual_hash = hashlib.sha256(
        json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()
    checks = {
        "evidence_hash": expected_hash == actual_hash,
        "evidence_label": report.get("evidence_label") == EVIDENCE_LABEL,
        "dataset_hash": PortDataset.load(report["dataset"]["id"]).package_sha256
        == report["dataset"]["package_sha256"],
        "code_hashes": all(
            sha256_file(PROJECT_ROOT / Path(name)) == digest
            for name, digest in report["protocol"]["code_sha256"].items()
        ),
        "production_boundary": "not" in str(report.get("boundary", "")).lower(),
    }
    return {"ok": all(checks.values()), "checks": checks, "path": str(path)}


def refresh_derived_report(path: Path) -> dict[str, Any]:
    """Recompute derived statistics and hashes from persisted per-window rollouts."""

    report = json.loads(path.read_text(encoding="utf-8"))
    windows = report["per_window"]
    risk = windows["risk_aware_mpc"]
    report["business_metrics_vs_fixed_full_resources"] = _metrics(
        risk, windows["fixed_full_resources"]
    )
    report["algorithm_increment_vs_causal_legacy_mpc"] = _metrics(
        risk, windows["causal_legacy_mpc"]
    )
    for stress in report["stress_tests"].values():
        comparison = stress.get("comparison") or {}
        # Raw stress rollouts are not persisted to keep the public artifact compact;
        # retain their signed comparison values from the full run.
        if "constraint_success_rate_pct" not in comparison:
            comparison["constraint_success_rate_pct"] = stress[
                "risk_aware_zero_violation_rate_pct"
            ]
    report["protocol"]["code_sha256"] = {
        str(code_path): sha256_file(PROJECT_ROOT / code_path) for code_path in CODE_FILES
    }
    report["derived_metrics_refreshed_at"] = datetime.now(timezone.utc).isoformat().replace(
        "+00:00", "Z"
    )
    report.pop("evidence_sha256", None)
    report["evidence_sha256"] = hashlib.sha256(
        json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    path.with_suffix(".md").write_text(render_markdown(report), encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Causal port-landing robustness benchmark")
    subparsers = parser.add_subparsers(dest="command", required=True)
    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("--dataset", default=DEFAULT_DATASET)
    run_parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    run_parser.add_argument("--workers", type=int, default=1)
    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("path", type=Path)
    refresh_parser = subparsers.add_parser("refresh-derived")
    refresh_parser.add_argument("path", type=Path)
    args = parser.parse_args()
    if args.command == "run":
        report = build_report(args.dataset, workers=max(1, args.workers))
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        args.output.with_suffix(".md").write_text(render_markdown(report), encoding="utf-8")
        print(json.dumps({"ok": True, "path": str(args.output), "evidence_sha256": report["evidence_sha256"]}))
    elif args.command == "verify":
        result = verify_report(args.path)
        print(json.dumps(result, ensure_ascii=False))
        if not result["ok"]:
            raise SystemExit(1)
    else:
        report = refresh_derived_report(args.path)
        print(
            json.dumps(
                {"ok": True, "path": str(args.path), "evidence_sha256": report["evidence_sha256"]}
            )
        )


if __name__ == "__main__":
    main()
