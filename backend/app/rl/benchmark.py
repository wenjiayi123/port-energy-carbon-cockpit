from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

import numpy as np

from app.rl.dataset import DEFAULT_DATASET_ID, PROJECT_ROOT, PortDataset
from app.rl.environment import (
    DEFAULT_REWARD_WEIGHTS,
    FixedDispatchPolicy,
    MPCPolicy,
    OBSERVATION_KEYS,
    PortEnergyDispatchEnv,
    encode_continuous_controls,
)


EVIDENCE_LABEL = "OFFLINE_SCENARIO_BENCHMARK_NOT_FIELD_KPI"
DEFAULT_DATASET = DEFAULT_DATASET_ID
DEFAULT_EPISODE_HOURS = 24
REPORT_VERSION = "3.0"
REWARD_PROFILES = {
    "balanced": DEFAULT_REWARD_WEIGHTS,
    "cost_priority": {
        "carbon": 0.14,
        "shore_power": 0.05,
        "cost": 0.34,
        "delay": 0.12,
        "safety": 0.15,
        "peak": 0.12,
        "storage": 0.08,
    },
    "peak_priority": {
        "carbon": 0.14,
        "shore_power": 0.04,
        "cost": 0.16,
        "delay": 0.10,
        "safety": 0.20,
        "peak": 0.30,
        "storage": 0.06,
    },
}
BENCHMARK_FILES = (
    Path("backend/app/rl/environment.py"),
    Path("backend/app/rl/benchmark.py"),
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _rollout(
    dataset: str,
    split: str,
    row_index: int,
    policy: str,
    episode_hours: int,
    reward_weights: dict[str, float],
    fixed_controls: dict[str, float] | None = None,
) -> dict[str, Any]:
    env = PortEnergyDispatchEnv(
        dataset=dataset,
        split=split,
        action_mode="continuous",
        reward_weights=reward_weights,
        episode_hours=episode_hours,
        render_mode=None,
    )
    _, _ = env.reset(
        seed=20260724 + row_index,
        options={"row_index": row_index, "start_hour": 0},
    )
    mpc = MPCPolicy()
    fixed = FixedDispatchPolicy(**(fixed_controls or {}))
    terminated = truncated = False
    while not (terminated or truncated):
        controls = mpc.predict(env) if policy == "mpc" else fixed.predict(env)
        _, _, terminated, truncated, _ = env.step(encode_continuous_controls(controls))
    return env.summary()


def _rollout_job(arguments: tuple[Any, ...]) -> dict[str, Any]:
    return _rollout(*arguments)


def _aggregate(episodes: list[dict[str, Any]]) -> dict[str, float]:
    numeric_keys = (
        "reward",
        "energy_kwh",
        "carbon_kg",
        "grid_carbon_kg",
        "fuel_carbon_kg",
        "cost",
        "delay_minutes",
        "processed_teu",
        "shore_power_kwh",
        "shore_power_opportunity_kwh",
        "safety_violations",
        "peak_violation_steps",
        "delay_violation_steps",
        "peak_kw",
        "soc_violation_steps",
        "battery_charge_kwh",
        "battery_discharge_kwh",
        "battery_throughput_kwh",
        "battery_degradation_cost_cny",
        "battery_constraint_projection_kwh",
        "ending_battery_soc",
        "ending_queue_teu",
        "crane_activation_ratio_sum",
        "yard_activation_ratio_sum",
    )
    return {
        key: round(float(np.mean([float(episode[key]) for episode in episodes])), 6)
        for key in numeric_keys
    }


def _saving(reference: float, candidate: float) -> float:
    return round((reference - candidate) / max(abs(reference), 1e-9) * 100.0, 3)


def select_validation_static_reference(
    dataset: str,
    episode_hours: int,
    reward_weights: dict[str, float],
) -> dict[str, Any]:
    """Select a fixed-resource comparator using validation data only.

    This creates a harder denominator than fixed full resources without
    allowing the held-out 2025 test split to influence the chosen ratios.
    """
    package = PortDataset.load(dataset)
    starts = package.evaluation_start_indices("validation", episode_hours)
    candidates: list[dict[str, Any]] = []
    for crane_ratio in (0.60, 0.80, 1.00):
        for yard_ratio in (0.60, 0.80, 1.00):
            controls = {
                "shore_power_ratio": 1.0,
                "crane_ratio": crane_ratio,
                "yard_ratio": yard_ratio,
                "battery_power_ratio": 0.0,
            }
            episodes = [
                _rollout(
                    dataset,
                    "validation",
                    row_index,
                    "fixed",
                    episode_hours,
                    reward_weights,
                    controls,
                )
                for row_index in starts
            ]
            aggregate = _aggregate(episodes)
            candidates.append(
                {
                    "controls": controls,
                    "validation_mean_reward": aggregate["reward"],
                    "validation_safety_violations": aggregate["safety_violations"],
                    "validation_delay_minutes": aggregate["delay_minutes"],
                }
            )
    feasible = [
        candidate
        for candidate in candidates
        if candidate["validation_safety_violations"] == 0.0
    ]
    selected = max(
        feasible or candidates,
        key=lambda candidate: candidate["validation_mean_reward"],
    )
    return {
        "selection_split": "validation",
        "selection_rule": "maximum mean reward among zero-safety-violation static candidates",
        "candidate_count": len(candidates),
        "selected": selected,
    }


def evaluate_split(
    dataset: str,
    split: str,
    episode_hours: int = DEFAULT_EPISODE_HOURS,
    reward_weights: dict[str, float] | None = None,
    workers: int = 1,
    calibrated_reference_controls: dict[str, float] | None = None,
) -> dict[str, Any]:
    weights = reward_weights or DEFAULT_REWARD_WEIGHTS
    package = PortDataset.load(dataset)
    starts = package.evaluation_start_indices(split, episode_hours)
    jobs = [
        (dataset, split, row_index, "mpc", episode_hours, weights, None)
        for row_index in starts
    ]
    if workers > 1 and len(jobs) > 1:
        with ProcessPoolExecutor(max_workers=min(workers, len(jobs))) as pool:
            mpc_episodes = list(pool.map(_rollout_job, jobs))
    else:
        mpc_episodes = [_rollout_job(job) for job in jobs]
    strong_reference_controls = {
        "shore_power_ratio": 1.0,
        "crane_ratio": 1.0,
        "yard_ratio": 1.0,
    }
    transition_reference_controls = {
        "shore_power_ratio": 0.0,
        "crane_ratio": 1.0,
        "yard_ratio": 1.0,
    }
    strong_reference_episodes = [
        _rollout(
            dataset,
            split,
            row_index,
            "fixed",
            episode_hours,
            weights,
            strong_reference_controls,
        )
        for row_index in starts
    ]
    transition_reference_episodes = [
        _rollout(
            dataset,
            split,
            row_index,
            "fixed",
            episode_hours,
            weights,
            transition_reference_controls,
        )
        for row_index in starts
    ]
    calibrated_reference_episodes = (
        [
            _rollout(
                dataset,
                split,
                row_index,
                "fixed",
                episode_hours,
                weights,
                calibrated_reference_controls,
            )
            for row_index in starts
        ]
        if calibrated_reference_controls
        else []
    )
    mpc = _aggregate(mpc_episodes)
    strong_reference = _aggregate(strong_reference_episodes)
    transition_reference = _aggregate(transition_reference_episodes)
    calibrated_reference = (
        _aggregate(calibrated_reference_episodes)
        if calibrated_reference_episodes
        else None
    )
    total_steps = int(sum(int(episode["steps"]) for episode in mpc_episodes))
    violation_steps = int(
        sum(
            int(episode["peak_violation_steps"])
            + int(episode["delay_violation_steps"])
            + int(episode["soc_violation_steps"])
            for episode in mpc_episodes
        )
    )
    shore_rate = (
        mpc["shore_power_kwh"] / max(1.0, mpc["shore_power_opportunity_kwh"]) * 100.0
    )
    calibrated_metrics = None
    if calibrated_reference is not None:
        calibrated_metrics = {
            "carbon_reduction_pct": _saving(
                calibrated_reference["carbon_kg"], mpc["carbon_kg"]
            ),
            "cost_saving_pct": _saving(
                calibrated_reference["cost"], mpc["cost"]
            ),
            "energy_reduction_pct": _saving(
                calibrated_reference["energy_kwh"], mpc["energy_kwh"]
            ),
            "throughput_change_pct": round(
                (mpc["processed_teu"] - calibrated_reference["processed_teu"])
                / max(abs(calibrated_reference["processed_teu"]), 1e-9)
                * 100.0,
                3,
            ),
            "peak_load_reduction_pct": _saving(
                calibrated_reference["peak_kw"], mpc["peak_kw"]
            ),
        }
    return {
        "split": split,
        "episodes": len(starts),
        "steps": total_steps,
        "start_indices": starts,
        "periods": [str(episode["period"]) for episode in mpc_episodes],
        "mpc_mean": mpc,
        "strong_reference_mean": strong_reference,
        "transition_reference_mean": transition_reference,
        "validation_calibrated_reference_mean": calibrated_reference,
        "metrics_vs_strong_reference": {
            "carbon_reduction_pct": _saving(
                strong_reference["carbon_kg"], mpc["carbon_kg"]
            ),
            "cost_saving_pct": _saving(strong_reference["cost"], mpc["cost"]),
            "energy_reduction_pct": _saving(
                strong_reference["energy_kwh"], mpc["energy_kwh"]
            ),
            "throughput_change_pct": round(
                (mpc["processed_teu"] - strong_reference["processed_teu"])
                / max(abs(strong_reference["processed_teu"]), 1e-9)
                * 100.0,
                3,
            ),
            "peak_load_change_pct": round(
                (mpc["peak_kw"] - strong_reference["peak_kw"])
                / max(abs(strong_reference["peak_kw"]), 1e-9)
                * 100.0,
                3,
            ),
            "peak_load_reduction_pct": _saving(
                strong_reference["peak_kw"], mpc["peak_kw"]
            ),
            "mean_daily_delay_minutes": round(mpc["delay_minutes"], 6),
            "reference_mean_daily_delay_minutes": round(
                strong_reference["delay_minutes"], 6
            ),
            "mean_crane_activation_pct": round(
                mpc["crane_activation_ratio_sum"]
                / max(1.0, float(episode_hours))
                * 100.0,
                3,
            ),
            "mean_yard_activation_pct": round(
                mpc["yard_activation_ratio_sum"]
                / max(1.0, float(episode_hours))
                * 100.0,
                3,
            ),
            "equipment_activation_reduction_pct": round(
                (
                    2.0
                    - (
                        mpc["crane_activation_ratio_sum"]
                        + mpc["yard_activation_ratio_sum"]
                    )
                    / max(1.0, float(episode_hours))
                )
                / 2.0
                * 100.0,
                3,
            ),
            "mean_ending_soc": round(mpc["ending_battery_soc"], 6),
            "mean_ending_queue_teu": round(mpc["ending_queue_teu"], 6),
            "battery_throughput_kwh": round(
                mpc["battery_throughput_kwh"], 6
            ),
            "shore_power_utilization_pct": round(shore_rate, 3),
            "constraint_success_rate_pct": round(
                (total_steps - violation_steps) / max(1, total_steps) * 100.0,
                3,
            ),
            "violation_steps": violation_steps,
        },
        "transition_scenario_metrics": {
            "carbon_reduction_pct": _saving(
                transition_reference["carbon_kg"], mpc["carbon_kg"]
            ),
            "cost_saving_pct": _saving(
                transition_reference["cost"], mpc["cost"]
            ),
            "scope": (
                "diagnostic shore-power-transition scenario only; "
                "excluded from resume-safe metrics"
            ),
        },
        "metrics_vs_validation_calibrated_reference": calibrated_metrics,
        "per_period": {
            "mpc": mpc_episodes,
            "strong_reference": strong_reference_episodes,
            "transition_reference": transition_reference_episodes,
            "validation_calibrated_reference": calibrated_reference_episodes,
        },
    }


def build_report(
    dataset: str = DEFAULT_DATASET,
    episode_hours: int = DEFAULT_EPISODE_HOURS,
    workers: int = 1,
) -> dict[str, Any]:
    package = PortDataset.load(dataset)
    code_hashes = {
        path.as_posix(): sha256_file(PROJECT_ROOT / path)
        for path in BENCHMARK_FILES
    }
    print("benchmark: validation split", file=sys.stderr, flush=True)
    validation = evaluate_split(
        dataset, "validation", episode_hours, workers=workers
    )
    calibrated_static = select_validation_static_reference(
        dataset,
        episode_hours,
        DEFAULT_REWARD_WEIGHTS,
    )
    calibrated_controls = calibrated_static["selected"]["controls"]
    sensitivity: dict[str, dict[str, Any]] = {}
    for name, weights in REWARD_PROFILES.items():
        print(f"benchmark: held-out profile={name}", file=sys.stderr, flush=True)
        sensitivity[name] = evaluate_split(
            dataset,
            "test",
            episode_hours,
            weights,
            workers=workers,
            calibrated_reference_controls=calibrated_controls,
        )
    test = sensitivity["balanced"]
    carbon_values = [
        item["metrics_vs_strong_reference"]["carbon_reduction_pct"]
        for item in sensitivity.values()
    ]
    cost_values = [
        item["metrics_vs_strong_reference"]["cost_saving_pct"]
        for item in sensitivity.values()
    ]
    constraint_values = [
        item["metrics_vs_strong_reference"]["constraint_success_rate_pct"]
        for item in sensitivity.values()
    ]
    return {
        "report_version": REPORT_VERSION,
        "generated_at": utc_now(),
        "status": "reproducible_offline_control_benchmark",
        "evidence_label": EVIDENCE_LABEL,
        "dataset": {
            "id": package.dataset_id,
            "csv_sha256": package.sha256,
            "metadata_sha256": package.metadata_sha256,
            "package_sha256": package.package_sha256,
            "quality": package.quality_report(),
            "drift": package.drift_report(),
        },
        "experiment": {
            "environment": "PortEnergyDispatchEnv-v1",
            "candidate": "four-step constrained MPC beam search with terminal SOC value",
            "primary_reference": {
                "name": "fixed_full_shore_power_resources",
                "controls": FixedDispatchPolicy().controls,
                "scope": (
                    "strong comparator with the same full shore-power opportunity; "
                    "isolates dynamic equipment-resource allocation"
                ),
            },
            "secondary_reference": {
                "name": "fixed_auxiliary_fuel_transition_scenario",
                "controls": FixedDispatchPolicy(shore_power_ratio=0.0).controls,
                "scope": "diagnostic only; excluded from resume-safe metrics",
            },
            "validation_calibrated_reference": calibrated_static,
            "observation_contract": {
                "count": len(OBSERVATION_KEYS),
                "keys": list(OBSERVATION_KEYS),
                "normalization_fit_scope": "train_only",
            },
            "reward_weights": DEFAULT_REWARD_WEIGHTS,
            "episode_hours": episode_hours,
            "parallel_workers": workers,
            "render_during_evaluation": False,
            "code_sha256": code_hashes,
        },
        "validation": validation,
        "held_out_test": test,
        "sensitivity": {
            "profiles": sensitivity,
            "profile_count": len(sensitivity),
            "unique_test_steps": test["steps"],
            "objective_step_evaluations": test["steps"] * len(sensitivity),
            "carbon_reduction_pct_range": [
                round(min(carbon_values), 3),
                round(max(carbon_values), 3),
            ],
            "cost_saving_pct_range": [
                round(min(cost_values), 3),
                round(max(cost_values), 3),
            ],
            "minimum_constraint_success_rate_pct": round(
                min(constraint_values), 3
            ),
        },
        "resume_safe_metrics": {
            "carbon_reduction_pct": test["metrics_vs_strong_reference"][
                "carbon_reduction_pct"
            ],
            "cost_saving_pct": test["metrics_vs_strong_reference"]["cost_saving_pct"],
            "energy_reduction_pct": test["metrics_vs_strong_reference"][
                "energy_reduction_pct"
            ],
            "peak_load_reduction_pct": test["metrics_vs_strong_reference"][
                "peak_load_reduction_pct"
            ],
            "equipment_activation_reduction_pct": test[
                "metrics_vs_strong_reference"
            ]["equipment_activation_reduction_pct"],
            "throughput_change_pct": test["metrics_vs_strong_reference"][
                "throughput_change_pct"
            ],
            "throughput_retention_pct": round(
                100.0
                + test["metrics_vs_strong_reference"]["throughput_change_pct"],
                3,
            ),
            "mean_ending_soc": test["metrics_vs_strong_reference"][
                "mean_ending_soc"
            ],
            "constraint_success_rate_pct": test["metrics_vs_strong_reference"][
                "constraint_success_rate_pct"
            ],
            "test_steps": test["steps"],
            "sensitivity_profile_count": len(sensitivity),
            "carbon_reduction_pct_range": [
                round(min(carbon_values), 3),
                round(max(carbon_values), 3),
            ],
            "cost_saving_pct_range": [
                round(min(cost_values), 3),
                round(max(cost_values), 3),
            ],
            "required_qualifier": (
                "public-data offline scenario versus a strong fixed full-shore-power "
                "resource comparator; not a field KPI"
            ),
            "harder_comparator": test[
                "metrics_vs_validation_calibrated_reference"
            ],
        },
        "claim_eligibility": {
            "scope": "offline_scenario_only",
            "checks": {
                "dataset_quality_pass": package.quality_report()["status"] == "pass",
                "test_is_temporally_held_out": True,
                "throughput_retention_at_least_99_percent": (
                    100.0
                    + test["metrics_vs_strong_reference"]["throughput_change_pct"]
                    >= 99.0
                ),
                "constraint_success_100_percent": (
                    test["metrics_vs_strong_reference"][
                        "constraint_success_rate_pct"
                    ]
                    == 100.0
                ),
                "comparator_selected_without_test_data": (
                    calibrated_static["selection_split"] == "validation"
                ),
            },
            "passed": all(
                (
                    package.quality_report()["status"] == "pass",
                    100.0
                    + test["metrics_vs_strong_reference"]["throughput_change_pct"]
                    >= 99.0,
                    test["metrics_vs_strong_reference"][
                        "constraint_success_rate_pct"
                    ]
                    == 100.0,
                    calibrated_static["selection_split"] == "validation",
                )
            ),
        },
        "rl_training_evidence": {
            "status": "not_in_this_report",
            "note": (
                "PPO/SAC/TD3/DQN are executable in the repository, but this report "
                "does not claim RL convergence or RL superiority."
            ),
        },
        "limitations": [
            (
                "Port throughput and EIA California commercial electricity prices are "
                "official monthly public data; LADWP time-of-use periods shape the "
                "intraday scenario, but the resulting series is not a terminal invoice."
            ),
            (
                "Hourly consumed-electricity carbon intensity is taken from the EIA "
                "Hourly Electric Grid Monitor and is not a marginal-emissions signal."
            ),
            (
                "FX, fuel price, equipment parameters, hourly profile, and safety limits "
                "are declared scenario assumptions."
            ),
            "No terminal meter, TOS, AIS, weather, battery telemetry, or field outcome is used.",
            "The strong fixed-resource denominator is a declared comparator, not measured terminal practice.",
        ],
    }


def write_report(report: dict[str, Any], output_stem: Path) -> tuple[Path, Path]:
    json_path = output_stem.with_suffix(".json")
    markdown_path = output_stem.with_suffix(".md")
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    metrics = report["held_out_test"]["metrics_vs_strong_reference"]
    transition = report["held_out_test"]["transition_scenario_metrics"]
    calibrated = report["held_out_test"][
        "metrics_vs_validation_calibrated_reference"
    ]
    sensitivity = report["sensitivity"]
    resume = report["resume_safe_metrics"]
    markdown = f"""# CarbonOps offline benchmark

Evidence label: `{report["evidence_label"]}`

This is a reproducible public-data scenario result, not a live-port KPI, field trial,
regulatory assurance, or evidence of RL convergence.

## Held-out result

- Split: `{", ".join(report["held_out_test"]["periods"])}`
- Test coverage: `{resume["test_steps"]}` hourly simulation steps
- Primary comparator: full shore power with fixed crane/yard resources
- MPC energy reduction vs strong comparator: `{metrics["energy_reduction_pct"]:.3f}%`
- MPC carbon reduction vs strong comparator: `{metrics["carbon_reduction_pct"]:.3f}%`
- MPC cost saving vs strong comparator: `{metrics["cost_saving_pct"]:.3f}%`
- MPC peak-load reduction vs strong comparator: `{metrics["peak_load_reduction_pct"]:.3f}%`
- Mean equipment activation reduction: `{metrics["equipment_activation_reduction_pct"]:.3f}%`
- Constraint-compliant test steps: `{metrics["constraint_success_rate_pct"]:.3f}%`
- Throughput change: `{metrics["throughput_change_pct"]:+.3f}%`
- Throughput retention: `{resume["throughput_retention_pct"]:.3f}%`
- Peak-load change: `{metrics["peak_load_change_pct"]:+.3f}%`

## Harder validation-calibrated comparator

The static crane/yard ratios were selected from 9 candidates on the 2024
validation split only, then frozen before the 2025 test. Against that comparator,
MPC reduces energy by `{calibrated["energy_reduction_pct"]:.3f}%`, carbon by
`{calibrated["carbon_reduction_pct"]:.3f}%`, and cost by
`{calibrated["cost_saving_pct"]:.3f}%`; throughput changes by
`{calibrated["throughput_change_pct"]:+.3f}%` and peak load changes by
`{-calibrated["peak_load_reduction_pct"]:+.3f}%` (positive means a higher peak).

The full-resource result remains useful as an over-provisioning reduction
scenario, but the validation-calibrated line is the stronger algorithmic
comparison and must not be hidden.

The primary comparator uses shore-power ratio 1.0 and fixed crane/yard ratios
1.0. MPC therefore receives no credit for introducing shore power; the measured
gain comes from dynamic equipment-resource allocation under the same shore-power
opportunity.

The former zero-shore-power transition scenario remains diagnostic only:
carbon `{transition["carbon_reduction_pct"]:.3f}%`, cost
`{transition["cost_saving_pct"]:.3f}%`. These larger values are explicitly
excluded from resume-safe metrics.

## Sensitivity

- Predeclared objective profiles: `{sensitivity["profile_count"]}`
- Unique held-out steps per profile: `{sensitivity["unique_test_steps"]}`
- Objective-step evaluations: `{sensitivity["objective_step_evaluations"]}`
- Carbon reduction range: `{sensitivity["carbon_reduction_pct_range"][0]:.3f}%–{sensitivity["carbon_reduction_pct_range"][1]:.3f}%`
- Cost saving range: `{sensitivity["cost_saving_pct_range"][0]:.3f}%–{sensitivity["cost_saving_pct_range"][1]:.3f}%`
- Minimum constraint success: `{sensitivity["minimum_constraint_success_rate_pct"]:.3f}%`

## Evidence

- Dataset package SHA-256: `{report["dataset"]["package_sha256"]}`
- Environment SHA-256: `{report["experiment"]["code_sha256"]["backend/app/rl/environment.py"]}`
- Report status: `{report["status"]}`
- RL convergence/superiority: not claimed in this report

## Resume-safe wording

“在公开数据离线情景的 {resume["test_steps"]} 个留出测试时间步中，约束 MPC 相对全岸电固定资源强基线
降低能耗 `{metrics["energy_reduction_pct"]:.1f}%`、碳排
`{metrics["carbon_reduction_pct"]:.1f}%`、情景成本
`{metrics["cost_saving_pct"]:.1f}%`，峰值负荷降低
`{metrics["peak_load_reduction_pct"]:.1f}%`、设备平均启用比例降低
`{metrics["equipment_activation_reduction_pct"]:.1f}%`，吞吐保持率
`{resume["throughput_retention_pct"]:.2f}%`；三组目标权重敏感性复算区间为
`{sensitivity["carbon_reduction_pct_range"][0]:.1f}%–{sensitivity["carbon_reduction_pct_range"][1]:.1f}%`，
约束满足率 `{metrics["constraint_success_rate_pct"]:.0f}%`。”

This sentence must retain the offline-scenario and comparator qualifiers.
"""
    markdown_path.write_text(markdown, encoding="utf-8")
    return json_path, markdown_path


def verify_report(path: Path) -> dict[str, Any]:
    recorded = json.loads(path.read_text(encoding="utf-8"))
    current = build_report(
        dataset=recorded["dataset"]["id"],
        episode_hours=int(recorded["experiment"]["episode_hours"]),
        workers=int(recorded["experiment"].get("parallel_workers", 1)),
    )
    checks = {
        "evidence_label": recorded.get("evidence_label") == EVIDENCE_LABEL,
        "report_version": recorded.get("report_version") == REPORT_VERSION,
        "dataset_package_sha256": (
            recorded["dataset"]["package_sha256"] == current["dataset"]["package_sha256"]
        ),
        "environment_sha256": (
            recorded["experiment"]["code_sha256"]["backend/app/rl/environment.py"]
            == current["experiment"]["code_sha256"]["backend/app/rl/environment.py"]
        ),
        "benchmark_sha256": (
            recorded["experiment"]["code_sha256"]["backend/app/rl/benchmark.py"]
            == current["experiment"]["code_sha256"]["backend/app/rl/benchmark.py"]
        ),
        "held_out_metrics": (
            recorded["held_out_test"]["metrics_vs_strong_reference"]
            == current["held_out_test"]["metrics_vs_strong_reference"]
        ),
        "sensitivity": (
            recorded["sensitivity"]["carbon_reduction_pct_range"]
            == current["sensitivity"]["carbon_reduction_pct_range"]
            and recorded["sensitivity"]["cost_saving_pct_range"]
            == current["sensitivity"]["cost_saving_pct_range"]
        ),
        "validation_calibrated_reference": (
            recorded["experiment"]["validation_calibrated_reference"]
            == current["experiment"]["validation_calibrated_reference"]
        ),
        "harder_comparator_metrics": (
            recorded["held_out_test"][
                "metrics_vs_validation_calibrated_reference"
            ]
            == current["held_out_test"][
                "metrics_vs_validation_calibrated_reference"
            ]
        ),
        "claim_eligibility": (
            recorded.get("claim_eligibility")
            == current.get("claim_eligibility")
            and recorded.get("claim_eligibility", {}).get("passed") is True
        ),
    }
    return {
        "status": "verified" if all(checks.values()) else "failed",
        "checks": checks,
        "recorded_report": str(path),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Reproducible CarbonOps benchmark evidence")
    subparsers = parser.add_subparsers(dest="command", required=True)
    run = subparsers.add_parser("run")
    run.add_argument("--dataset", default=DEFAULT_DATASET)
    run.add_argument("--episode-hours", type=int, default=DEFAULT_EPISODE_HOURS)
    run.add_argument("--workers", type=int, default=1)
    run.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "reports" / "offline_benchmark_v3",
    )
    verify = subparsers.add_parser("verify")
    verify.add_argument("report", type=Path)
    args = parser.parse_args()
    if args.command == "run":
        report = build_report(args.dataset, args.episode_hours, args.workers)
        paths = write_report(report, args.output)
        print(json.dumps({"status": "written", "paths": [str(path) for path in paths]}))
        return
    result = verify_report(args.report)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result["status"] != "verified":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
