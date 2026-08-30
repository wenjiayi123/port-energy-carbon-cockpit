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
from app.rl.environment import (
    FixedDispatchPolicy,
    MPCPolicy,
    PortEnergyDispatchEnv,
    encode_continuous_controls,
)
from app.rl.robust import paired_bootstrap_interval
from app.rl.training import TrainingService


EVIDENCE_LABEL = "PUBLIC_ANCHOR_OPERATIONAL_FLEX_BENCHMARK_NOT_FIELD_KPI"
DATASET_ID = "port_la_2020_2024_operational_flex_hourly"
DEFAULT_TUNING_REPORT = PROJECT_ROOT / "reports/rl_tuning_operational_flex_v5_10k.json"
DEFAULT_OUTPUT = PROJECT_ROOT / "reports/operational_flex_business_value_v5.json"
EVALUATION_WORKERS = 4
V5_CONTROL_RANGES = {
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


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def portable(path: Path) -> str:
    try:
        return path.resolve().relative_to(PROJECT_ROOT.resolve()).as_posix()
    except ValueError:
        return str(path)


def _aggregate(episodes: list[dict[str, Any]]) -> dict[str, float]:
    keys = (
        "reward",
        "energy_kwh",
        "carbon_kg",
        "cost",
        "delay_minutes",
        "processed_teu",
        "shore_power_kwh",
        "peak_kw",
        "safety_violations",
        "peak_violation_steps",
        "delay_violation_steps",
        "soc_violation_steps",
        "agv_charge_demand_kwh",
        "agv_charged_kwh",
        "agv_missed_required_kwh",
        "reefer_thermal_violation_steps",
        "demand_response_target_kwh",
        "demand_response_delivered_kwh",
        "demand_response_non_delivery_kwh",
        "flexible_load_projection_kwh",
    )
    result = {
        key: round(float(np.mean([float(item[key]) for item in episodes])), 6)
        for key in keys
    }
    result["agv_service_pct"] = round(
        result["agv_charged_kwh"] / max(1.0, result["agv_charge_demand_kwh"]) * 100,
        4,
    )
    result["demand_response_delivery_pct"] = round(
        result["demand_response_delivered_kwh"]
        / max(1.0, result["demand_response_target_kwh"])
        * 100,
        4,
    )
    return result


def _saving(reference: float, candidate: float) -> float:
    return round((reference - candidate) / max(abs(reference), 1e-9) * 100.0, 4)


def _gain(reference: float, candidate: float) -> float:
    return round((candidate - reference) / max(abs(reference), 1e-9) * 100.0, 4)


def _nearest_discrete_action(
    env: PortEnergyDispatchEnv,
    controls: dict[str, float],
) -> int:
    keys = tuple(controls)
    target = np.asarray([controls[key] for key in keys], dtype=float)
    best_action = 0
    best_distance = float("inf")
    for action in range(int(env.action_space.n)):
        decoded = env.decode_action(action)
        vector = np.asarray([decoded.get(key, controls[key]) for key in keys], dtype=float)
        distance = float(np.square(vector - target).sum())
        if distance < best_distance:
            best_action = action
            best_distance = distance
    return best_action


def normalized_action_deviation(
    executed: dict[str, float],
    baseline: dict[str, float],
) -> float:
    """Return mean absolute deviation across all ten v5 control ranges."""
    deltas = []
    for key, (low, high) in V5_CONTROL_RANGES.items():
        width = high - low
        deltas.append(abs(float(executed[key]) - float(baseline[key])) / width)
    return float(np.mean(deltas))


def _dominance_accepts(
    candidate: dict[str, Any],
    baseline: dict[str, Any],
) -> bool:
    return bool(
        candidate["safety_violations"] <= baseline["safety_violations"]
        and candidate["peak_violation_kw"] <= 1e-9
        and candidate["agv_missed_required_kwh"] <= 1e-9
        and candidate["reefer_thermal_violation_steps"] <= 0
        and candidate["processed_teu"] + 1e-6 >= baseline["processed_teu"]
        and candidate["delay_minutes"] <= baseline["delay_minutes"] + 1e-6
        and candidate["carbon_kg"] <= baseline["carbon_kg"] * 1.001
        and candidate["cost"] <= baseline["cost"] * 1.001
        and candidate["demand_response_target_kwh"] + 1e-6
        >= baseline["demand_response_target_kwh"] * 0.98
        and candidate["demand_response_delivered_kwh"] + 1e-6
        >= candidate["demand_response_target_kwh"] * 0.98
        and candidate["reward"] >= baseline["reward"]
    )


def rollout(
    *,
    algorithm: str,
    row_index: int,
    model: Any | None = None,
    projected: bool = False,
) -> dict[str, Any]:
    action_mode = "discrete" if algorithm == "dqn" else "continuous"
    env = PortEnergyDispatchEnv(
        dataset=DATASET_ID,
        split="test",
        action_mode=action_mode,
        episode_hours=24,
        render_mode=None,
    )
    observation, _ = env.reset(seed=20260830 + row_index, options={"row_index": row_index})
    mpc = MPCPolicy()
    fixed = FixedDispatchPolicy()
    accepted = 0
    proposed = 0
    contribution_delta = 0.0
    while True:
        if algorithm == "mpc":
            action: Any = encode_continuous_controls(mpc.predict(env))
        elif algorithm == "fixed":
            action = encode_continuous_controls(fixed.predict(env))
        else:
            action, _ = model.predict(observation, deterministic=True)
            if projected:
                proposed += 1
                candidate_controls = env.decode_action(action)
                baseline_controls = mpc.predict(env)
                baseline = env.preview_transition(baseline_controls)
                accepted_action: Any | None = None
                # Preserve the learned direction while reducing its magnitude
                # until the one-step business/safety dominance checks pass.
                # This is an auditable action projection, not reward shaping.
                for share in (1.0, 0.75, 0.50, 0.25, 0.10, 0.05, 0.02):
                    blended_controls = {
                        key: float(baseline_controls[key])
                        + share
                        * (
                            float(candidate_controls[key])
                            - float(baseline_controls[key])
                        )
                        for key in baseline_controls
                    }
                    if algorithm == "dqn":
                        projected_action: Any = _nearest_discrete_action(
                            env, blended_controls
                        )
                        executed_controls = env.decode_action(projected_action)
                    else:
                        projected_action = encode_continuous_controls(blended_controls)
                        executed_controls = blended_controls
                    candidate = env.preview_transition(executed_controls)
                    if _dominance_accepts(candidate, baseline):
                        accepted_action = projected_action
                        break
                if accepted_action is not None:
                    action = accepted_action
                    accepted += 1
                    contribution_delta += normalized_action_deviation(
                        executed_controls,
                        baseline_controls,
                    )
                else:
                    action = (
                        _nearest_discrete_action(env, baseline_controls)
                        if algorithm == "dqn"
                        else encode_continuous_controls(baseline_controls)
                    )
        observation, _, terminated, truncated, _ = env.step(action)
        if terminated or truncated:
            break
    return {
        **env.summary(),
        "projected": projected,
        "rl_actions_proposed": proposed,
        "rl_actions_accepted": accepted,
        "rl_action_normalized_deviation": contribution_delta,
    }


def _rollout_worker(payload: tuple[str, int]) -> dict[str, Any]:
    algorithm, row_index = payload
    return rollout(algorithm=algorithm, row_index=row_index)


_WORKER_MODEL_CACHE: dict[tuple[str, str], Any] = {}


def _artifact_rollout_worker(
    payload: tuple[str, str, int, bool],
) -> dict[str, Any]:
    algorithm, artifact_path, row_index, projected = payload
    cache_key = (algorithm, artifact_path)
    model = _WORKER_MODEL_CACHE.get(cache_key)
    if model is None:
        model = TrainingService()._load_model(algorithm, artifact_path)
        _WORKER_MODEL_CACHE[cache_key] = model
    return rollout(
        algorithm=algorithm,
        row_index=row_index,
        model=model,
        projected=projected,
    )


def _summarize_episodes(episodes: list[dict[str, Any]]) -> dict[str, Any]:
    aggregate = _aggregate(episodes)
    proposed = sum(int(item["rl_actions_proposed"]) for item in episodes)
    accepted = sum(int(item["rl_actions_accepted"]) for item in episodes)
    contribution_delta = sum(
        float(item["rl_action_normalized_deviation"]) for item in episodes
    )
    return {
        "mean": aggregate,
        "episodes": episodes,
        "episode_count": len(episodes),
        "test_steps": sum(int(item["steps"]) for item in episodes),
        "rl_actions_proposed": proposed,
        "rl_actions_accepted": accepted,
        "rl_action_acceptance_pct": round(accepted / max(1, proposed) * 100.0, 4),
        "rl_action_contribution_pct": round(
            contribution_delta / max(1, proposed) * 100.0,
            4,
        ),
        "rl_action_contribution_metric": (
            "mean_absolute_executed_deviation_from_mpc_across_10_normalized_controls"
        ),
    }


def evaluate_artifact_seeds(
    algorithm: str,
    artifact_paths: list[str],
    starts: list[int],
    *,
    projected: bool,
) -> list[dict[str, Any]]:
    payloads = [
        (algorithm, artifact_path, row_index, projected)
        for artifact_path in artifact_paths
        for row_index in starts
    ]
    with ProcessPoolExecutor(max_workers=EVALUATION_WORKERS) as executor:
        episodes = list(executor.map(_artifact_rollout_worker, payloads))
    window_count = len(starts)
    return [
        _summarize_episodes(episodes[offset : offset + window_count])
        for offset in range(0, len(episodes), window_count)
    ]


def evaluate_policy(
    algorithm: str,
    model: Any | None,
    starts: list[int],
    *,
    projected: bool = False,
    parallel_windows: bool = False,
) -> dict[str, Any]:
    if parallel_windows:
        if model is not None or projected:
            raise ValueError("parallel window evaluation is reserved for model-free baselines")
        with ProcessPoolExecutor(max_workers=EVALUATION_WORKERS) as executor:
            episodes = list(executor.map(_rollout_worker, [(algorithm, row) for row in starts]))
    else:
        episodes = [
            rollout(
                algorithm=algorithm,
                row_index=row_index,
                model=model,
                projected=projected,
            )
            for row_index in starts
        ]
    return _summarize_episodes(episodes)


def _comparison(candidate: dict[str, Any], baseline: dict[str, Any]) -> dict[str, Any]:
    current = candidate["mean"]
    reference = baseline["mean"]
    return {
        "carbon_reduction_pct": _saving(reference["carbon_kg"], current["carbon_kg"]),
        "cost_reduction_pct": _saving(reference["cost"], current["cost"]),
        "energy_reduction_pct": _saving(reference["energy_kwh"], current["energy_kwh"]),
        "delay_reduction_pct": _saving(reference["delay_minutes"], current["delay_minutes"]),
        "peak_reduction_pct": _saving(reference["peak_kw"], current["peak_kw"]),
        "throughput_change_pct": _gain(reference["processed_teu"], current["processed_teu"]),
        "shore_power_change_pct": _gain(reference["shore_power_kwh"], current["shore_power_kwh"]),
        "reward_change": round(current["reward"] - reference["reward"], 6),
        "safety_violations": current["safety_violations"],
        "agv_service_pct": current["agv_service_pct"],
        "agv_missed_required_kwh": current["agv_missed_required_kwh"],
        "reefer_thermal_violation_steps": current["reefer_thermal_violation_steps"],
        "demand_response_delivery_pct": current["demand_response_delivery_pct"],
        "demand_response_commitment_pct": round(
            current["demand_response_target_kwh"]
            / max(1.0, reference["demand_response_target_kwh"])
            * 100.0,
            4,
        ),
        "carbon_reduction_ci95": paired_bootstrap_interval(
            [float(item["carbon_kg"]) for item in candidate["episodes"]],
            [float(item["carbon_kg"]) for item in baseline["episodes"]],
            seed=20260830,
        ),
        "cost_reduction_ci95": paired_bootstrap_interval(
            [float(item["cost"]) for item in candidate["episodes"]],
            [float(item["cost"]) for item in baseline["episodes"]],
            seed=20260831,
        ),
    }


def _admission(comparison: dict[str, Any], contribution_pct: float | None) -> dict[str, Any]:
    checks = {
        "zero_safety_violations": comparison["safety_violations"] == 0,
        "carbon_non_regression": comparison["carbon_reduction_pct"] >= 0,
        "cost_non_regression": comparison["cost_reduction_pct"] >= 0,
        "throughput_non_regression": comparison["throughput_change_pct"] >= -0.1,
        "delay_non_regression": comparison["delay_reduction_pct"] >= 0,
        "peak_non_regression": comparison["peak_reduction_pct"] >= 0,
        "shore_power_non_regression": comparison["shore_power_change_pct"] >= -0.1,
        "reward_improvement": comparison["reward_change"] > 0,
        "agv_departure_obligation": comparison["agv_missed_required_kwh"] == 0,
        "reefer_thermal_safety": comparison["reefer_thermal_violation_steps"] == 0,
        "demand_response_delivery": comparison["demand_response_delivery_pct"] >= 98.0,
        "demand_response_commitment": comparison["demand_response_commitment_pct"]
        >= 98.0,
        "carbon_ci95_non_regression": comparison["carbon_reduction_ci95"]["ci95_low_pct"] >= 0,
        "cost_ci95_non_regression": comparison["cost_reduction_ci95"]["ci95_low_pct"] >= 0,
    }
    if contribution_pct is not None:
        checks["material_rl_contribution"] = contribution_pct >= 1.0
    return {
        "status": "admitted_offline" if all(checks.values()) else "blocked",
        "checks": checks,
        "failed_checks": [name for name, passed in checks.items() if not passed],
        "production_eligible": False,
    }


def run(tuning_report: Path, output: Path) -> dict[str, Any]:
    tuning = json.loads(tuning_report.read_text(encoding="utf-8"))
    if tuning["dataset_id"] != DATASET_ID or tuning["environment_id"] != "PortEnergyDispatchEnv-v5":
        raise ValueError("tuning report does not target the registered v5 dataset")
    dataset = PortDataset.load(DATASET_ID)
    starts = dataset.evaluation_start_indices("test", 24)

    print(
        json.dumps(
            {
                "status": "phase_started",
                "phase": "model_free_baselines",
                "test_windows": len(starts),
                "workers": EVALUATION_WORKERS,
            }
        ),
        flush=True,
    )
    baseline_mpc = evaluate_policy("mpc", None, starts, parallel_windows=True)
    baseline_fixed = evaluate_policy("fixed", None, starts, parallel_windows=True)
    algorithm_results: list[dict[str, Any]] = []
    for item in tuning["algorithms"]:
        print(
            json.dumps(
                {
                    "status": "phase_started",
                    "phase": "raw_seed_evaluation",
                    "algorithm": item["algorithm"],
                    "workers": EVALUATION_WORKERS,
                }
            ),
            flush=True,
        )
        seed_results = []
        final_seed_results = item["final_seed_results"]
        for seed_item in final_seed_results:
            artifact = PROJECT_ROOT / seed_item["artifact_path"]
            if sha256_file(artifact) != seed_item["artifact_sha256"]:
                raise ValueError(f"artifact hash mismatch: {artifact}")
        raw_results = evaluate_artifact_seeds(
            item["algorithm"],
            [str(PROJECT_ROOT / seed_item["artifact_path"]) for seed_item in final_seed_results],
            starts,
            projected=False,
        )
        for seed_item, raw in zip(final_seed_results, raw_results, strict=True):
            artifact = PROJECT_ROOT / seed_item["artifact_path"]
            comparison = _comparison(raw, baseline_mpc)
            seed_results.append(
                {
                    "seed": seed_item["seed"],
                    "artifact_path": portable(artifact),
                    "artifact_sha256": seed_item["artifact_sha256"],
                    "raw": {key: value for key, value in raw.items() if key != "episodes"},
                    "versus_mpc": comparison,
                    "admission": _admission(comparison, None),
                }
            )
        validation_returns = [
            float(seed_item["training"]["validation"]["mean"]["reward"])
            for seed_item in item["final_seed_results"]
        ]
        validation_safety = [
            float(seed_item["training"]["validation"]["mean"]["safety_violations"])
            for seed_item in item["final_seed_results"]
        ]
        algorithm_results.append(
            {
                "algorithm": item["algorithm"],
                "validation_mean_return": round(float(np.mean(validation_returns)), 6),
                "validation_mean_safety_violations": round(float(np.mean(validation_safety)), 6),
                "seed_results": seed_results,
            }
        )

    validation_eligible = [
        item for item in algorithm_results if item["validation_mean_safety_violations"] == 0
    ]
    selected = max(
        validation_eligible or algorithm_results,
        key=lambda item: item["validation_mean_return"],
    )
    tuning_item = next(
        item for item in tuning["algorithms"] if item["algorithm"] == selected["algorithm"]
    )
    projected_seed_results = []
    selected_seed_results = tuning_item["final_seed_results"]
    print(
        json.dumps(
            {
                "status": "phase_started",
                "phase": "dominance_projection",
                "algorithm": selected["algorithm"],
                "contribution_metric": (
                    "mean_absolute_executed_deviation_from_mpc_across_10_normalized_controls"
                ),
                "workers": EVALUATION_WORKERS,
            }
        ),
        flush=True,
    )
    projected_results = evaluate_artifact_seeds(
        selected["algorithm"],
        [
            str(PROJECT_ROOT / seed_item["artifact_path"])
            for seed_item in selected_seed_results
        ],
        starts,
        projected=True,
    )
    for seed_item, projected in zip(
        selected_seed_results, projected_results, strict=True
    ):
        artifact = PROJECT_ROOT / seed_item["artifact_path"]
        comparison = _comparison(projected, baseline_mpc)
        projected_seed_results.append(
            {
                "seed": seed_item["seed"],
                "artifact_path": portable(artifact),
                "artifact_sha256": seed_item["artifact_sha256"],
                "projected": {key: value for key, value in projected.items() if key != "episodes"},
                "versus_mpc": comparison,
                "admission": _admission(
                    comparison, projected["rl_action_contribution_pct"]
                ),
            }
        )

    selected_raw = selected["seed_results"]
    projected_all_seed_admitted = bool(
        len(projected_seed_results) == 3
        and all(
            item["admission"]["status"] == "admitted_offline"
            for item in projected_seed_results
        )
    )
    raw_all_seed_admitted = bool(
        len(selected_raw) == 3
        and all(
            item["admission"]["status"] == "admitted_offline"
            for item in selected_raw
        )
    )
    champion_method = (
        "dominance_projected_rl"
        if projected_all_seed_admitted
        else "raw_rl"
        if raw_all_seed_admitted
        else None
    )
    champion_seed_results = (
        projected_seed_results
        if projected_all_seed_admitted
        else selected_raw
        if raw_all_seed_admitted
        else []
    )
    champion_metrics = (
        {
            key: round(
                float(np.mean([item["versus_mpc"][key] for item in champion_seed_results])),
                6,
            )
            for key in (
                "carbon_reduction_pct",
                "cost_reduction_pct",
                "energy_reduction_pct",
                "delay_reduction_pct",
                "peak_reduction_pct",
                "throughput_change_pct",
                "shore_power_change_pct",
                "reward_change",
                "agv_service_pct",
                "demand_response_delivery_pct",
                "demand_response_commitment_pct",
            )
        }
        if champion_seed_results
        else None
    )
    champion = (
        {
            "algorithm": selected["algorithm"],
            "method": champion_method,
            "selection_basis": "validation mean return with zero mean safety violations",
            "all_seed_admission_required": True,
            "seeds": [item["seed"] for item in champion_seed_results],
            "artifacts": [
                {
                    "seed": item["seed"],
                    "artifact_path": item["artifact_path"],
                    "artifact_sha256": item["artifact_sha256"],
                }
                for item in champion_seed_results
            ],
            "mean_business_value_vs_mpc": champion_metrics,
            "production_eligible": False,
        }
        if champion_seed_results
        else None
    )
    report = {
        "schema_version": "operational-flex-business-value.v1",
        "generated_at": utc_now(),
        "evidence_label": EVIDENCE_LABEL,
        "dataset": dataset.describe(),
        "protocol": {
            "fit_split": "train",
            "hyperparameter_and_algorithm_selection_split": "validation",
            "final_report_split": "test",
            "test_window_count": len(starts),
            "test_start_indices": starts,
            "steps_per_fit": tuning["total_steps_per_fit"],
            "final_seeds": [17, 37, 59],
            "render_during_fit_or_selection": False,
            "evaluation_workers": EVALUATION_WORKERS,
            "rl_contribution_metric": (
                "mean absolute executed deviation from MPC across ten normalized controls"
            ),
        },
        "baselines": {
            "mpc": {key: value for key, value in baseline_mpc.items() if key != "episodes"},
            "fixed_full_service": {
                key: value for key, value in baseline_fixed.items() if key != "episodes"
            },
        },
        "validation_selected_algorithm": selected["algorithm"],
        "algorithm_results": algorithm_results,
        "dominance_projected_selected_algorithm": projected_seed_results,
        "champion": champion,
        "champion_status": "admitted_offline" if champion else "no_rl_policy_admitted",
        "production_boundary": {
            "simulation_mode": True,
            "public_anchor_plus_modeled_supplement": True,
            "live_data_verified": False,
            "dispatch_allowed": False,
            "production_authority": False,
        },
        "tuning_report": portable(tuning_report),
        "tuning_report_sha256": sha256_file(tuning_report),
        "code_sha256": {
            path: sha256_file(PROJECT_ROOT / path)
            for path in (
                "backend/app/rl/environment.py",
                "backend/app/rl/operational_flex_benchmark.py",
                "backend/app/rl/training.py",
                "scripts/build_operational_flex_dataset.py",
            )
        },
    }
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def verify(report_path: Path) -> dict[str, Any]:
    report = json.loads(report_path.read_text(encoding="utf-8"))
    dataset = PortDataset.load(DATASET_ID)
    tuning_path = PROJECT_ROOT / str(report.get("tuning_report") or "")
    algorithm_results = report.get("algorithm_results") or []
    projected_results = report.get("dominance_projected_selected_algorithm") or []
    all_artifacts = [
        seed_result
        for algorithm_result in algorithm_results
        for seed_result in algorithm_result.get("seed_results") or []
    ] + list(projected_results)
    artifact_checks = [
        (
            (PROJECT_ROOT / item["artifact_path"]).is_file()
            and sha256_file(PROJECT_ROOT / item["artifact_path"])
            == item["artifact_sha256"]
        )
        for item in all_artifacts
    ]
    code_hashes = report.get("code_sha256") or {}
    code_checks = [
        (PROJECT_ROOT / path).is_file()
        and sha256_file(PROJECT_ROOT / path) == expected
        for path, expected in code_hashes.items()
    ]
    champion = report.get("champion")
    champion_consistent = (
        report.get("champion_status") == "no_rl_policy_admitted" and champion is None
    ) or (
        report.get("champion_status") == "admitted_offline"
        and isinstance(champion, dict)
        and len(champion.get("seeds") or []) == 3
        and champion.get("production_eligible") is False
    )
    checks = {
        "schema": report.get("schema_version") == "operational-flex-business-value.v1",
        "evidence_label": report.get("evidence_label") == EVIDENCE_LABEL,
        "dataset_id": report.get("dataset", {}).get("id") == DATASET_ID,
        "dataset_package_sha256": report.get("dataset", {}).get("package_sha256")
        == dataset.package_sha256,
        "tuning_report_exists": tuning_path.is_file(),
        "tuning_report_sha256": tuning_path.is_file()
        and sha256_file(tuning_path) == report.get("tuning_report_sha256"),
        "all_artifacts_sha256": bool(artifact_checks) and all(artifact_checks),
        "all_code_sha256": bool(code_checks) and all(code_checks),
        "protocol_splits": report.get("protocol", {}).get("fit_split") == "train"
        and report.get("protocol", {}).get("hyperparameter_and_algorithm_selection_split")
        == "validation"
        and report.get("protocol", {}).get("final_report_split") == "test",
        "three_final_seeds": report.get("protocol", {}).get("final_seeds") == [17, 37, 59],
        "champion_consistent": champion_consistent,
        "production_authority_disabled": report.get("production_boundary")
        == {
            "simulation_mode": True,
            "public_anchor_plus_modeled_supplement": True,
            "live_data_verified": False,
            "dispatch_allowed": False,
            "production_authority": False,
        },
    }
    return {
        "ok": all(checks.values()),
        "report": portable(report_path),
        "report_sha256": sha256_file(report_path),
        "checks": checks,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Evaluate v5 operational-flex business value")
    parser.add_argument("--tuning-report", type=Path, default=DEFAULT_TUNING_REPORT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--verify-report", type=Path)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.verify_report:
        result = verify(args.verify_report)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if not result["ok"]:
            raise SystemExit(1)
        return
    report = run(args.tuning_report, args.output)
    print(
        json.dumps(
            {
                "status": "written",
                "output": portable(args.output),
                "champion_status": report["champion_status"],
                "validation_selected_algorithm": report["validation_selected_algorithm"],
            }
        )
    )


if __name__ == "__main__":
    main()
