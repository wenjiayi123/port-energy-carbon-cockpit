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
from app.rl.environment import MPCPolicy
from app.rl.hybrid_control import (
    CONTROL_BOUNDS,
    HYBRID_PRIORITY_KEYS,
    RESOURCE_CONTROL_KEYS,
    FastFeasibleControlPolicy,
    HybridOperationsSolver,
)
from app.rl.robust import CausalForecastPortEnv, paired_bootstrap_interval
from app.rl.training import TrainingService


DATASET_ID = "port_la_2020_2024_hybrid_rl_hourly"
DEFAULT_TUNING_REPORT = PROJECT_ROOT / "reports/rl_tuning_hybrid_v6_50k.json"
DEFAULT_OUTPUT = PROJECT_ROOT / "reports/hybrid_rl_business_value_v6.json"
WORKERS = 4
MINIMIZE_METRICS = (
    "carbon_kg",
    "cost",
    "delay_minutes",
    "peak_kw",
    "jit_deviation_hours",
    "anchorage_auxiliary_fuel_liters",
    "berth_conflict_hours",
    "crane_task_late_teu",
    "yard_rehandles_teu",
    "truck_queue_teu_hours",
    "maintenance_overdue_hours",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _episode(
    mode: str,
    artifact_path: str | None,
    algorithm: str | None,
    row_index: int,
    seed: int,
    model: Any | None = None,
    env: CausalForecastPortEnv | None = None,
) -> dict[str, Any]:
    if env is None:
        env = CausalForecastPortEnv(
            dataset=DATASET_ID,
            split="test",
            action_mode="continuous",
            episode_hours=24,
            render_mode=None,
        )
    observation, _ = env.reset(
        seed=int(seed) + int(row_index),
        options={"row_index": int(row_index), "start_hour": 0},
    )
    if mode == "rl" and model is None:
        model = TrainingService()._load_model(str(algorithm), str(artifact_path))
    mpc = MPCPolicy()
    controller = FastFeasibleControlPolicy()
    solver = HybridOperationsSolver()
    terminated = truncated = False
    residual_deviations: list[float] = []
    strategy_request_deviations: list[float] = []
    strategy_deviations: list[float] = []
    while not (terminated or truncated):
        reference = controller.predict(env)
        if mode == "mpc_or":
            action: Any = mpc.predict(env)
        elif mode == "rl":
            action, _ = model.predict(observation, deterministic=True)
            action_vector = np.asarray(action, dtype=np.float32).reshape(-1)
            requested_priorities = {
                key: float((action_vector[index] + 1.0) / 2.0)
                for index, key in enumerate(
                    HYBRID_PRIORITY_KEYS, start=len(RESOURCE_CONTROL_KEYS)
                )
            }
            neutral_priorities = solver.project(
                env, {key: 0.5 for key in HYBRID_PRIORITY_KEYS}
            ).realized
        else:
            raise ValueError(f"Unsupported mode: {mode}")
        observation, _, terminated, truncated, info = env.step(action)
        if mode == "rl":
            controls = info["controls"]
            normalized_resource_delta = [
                abs(float(controls[key]) - float(reference[key]))
                / max(1e-9, CONTROL_BOUNDS[key][1] - CONTROL_BOUNDS[key][0])
                for key in RESOURCE_CONTROL_KEYS
            ]
            residual_deviations.append(float(np.mean(normalized_resource_delta)))
            strategy_request_deviations.append(
                float(
                    np.mean(
                        [
                            abs(float(requested_priorities[key]) - 0.5)
                            for key in HYBRID_PRIORITY_KEYS
                        ]
                    )
                )
            )
            strategy_deviations.append(
                float(
                    np.mean(
                        [
                            abs(float(controls[key]) - float(neutral_priorities[key]))
                            for key in HYBRID_PRIORITY_KEYS
                        ]
                    )
                )
            )
    summary = env.summary()
    summary["rl_residual_contribution_pct"] = round(
        float(np.mean(residual_deviations)) * 100.0 if residual_deviations else 0.0,
        6,
    )
    summary["rl_strategy_contribution_pct"] = round(
        float(np.mean(strategy_deviations)) * 100.0 if strategy_deviations else 0.0,
        6,
    )
    summary["rl_strategy_request_deviation_pct"] = round(
        float(np.mean(strategy_request_deviations)) * 100.0
        if strategy_request_deviations
        else 0.0,
        6,
    )
    return summary


def _evaluate_chunk(
    payload: tuple[str, str | None, str | None, list[int], int]
) -> list[dict[str, Any]]:
    mode, artifact_path, algorithm, starts, seed = payload
    model = (
        TrainingService()._load_model(str(algorithm), str(artifact_path))
        if mode == "rl"
        else None
    )
    env = CausalForecastPortEnv(
        dataset=DATASET_ID,
        split="test",
        action_mode="continuous",
        episode_hours=24,
        render_mode=None,
    )
    return [
        _episode(
            mode,
            artifact_path,
            algorithm,
            row_index,
            seed,
            model=model,
            env=env,
        )
        for row_index in starts
    ]


def evaluate(
    mode: str,
    artifact_path: str | None,
    algorithm: str | None,
    starts: list[int],
    seed: int,
) -> dict[str, Any]:
    chunks = [
        [int(value) for value in chunk]
        for chunk in np.array_split(starts, min(WORKERS, len(starts)))
    ]
    with ProcessPoolExecutor(max_workers=len(chunks)) as executor:
        nested = list(
            executor.map(
                _evaluate_chunk,
                [
                    (mode, artifact_path, algorithm, chunk, seed)
                    for chunk in chunks
                    if chunk
                ],
            )
        )
    episodes = [item for chunk in nested for item in chunk]
    numeric_keys = [
        key
        for key, value in episodes[0].items()
        if isinstance(value, (int, float)) and not key.startswith("ending_")
    ]
    mean = {
        key: round(float(np.mean([float(item[key]) for item in episodes])), 6)
        for key in numeric_keys
    }
    demand_response_target = mean["demand_response_target_kwh"]
    mean["demand_response_delivery_pct"] = round(
        mean["demand_response_delivered_kwh"]
        / max(1.0, demand_response_target)
        * 100.0,
        4,
    )
    return {"mean": mean, "episodes": episodes, "window_count": len(episodes)}


def _saving(reference: float, candidate: float) -> float:
    return round((reference - candidate) / max(abs(reference), 1e-9) * 100.0, 4)


def _comparison(candidate: dict[str, Any], baseline: dict[str, Any]) -> dict[str, Any]:
    current = candidate["mean"]
    reference = baseline["mean"]
    result: dict[str, Any] = {
        f"{key}_reduction_pct": _saving(reference[key], current[key])
        for key in MINIMIZE_METRICS
    }
    result.update(
        throughput_change_pct=round(
            (current["processed_teu"] - reference["processed_teu"])
            / max(abs(reference["processed_teu"]), 1e-9)
            * 100.0,
            4,
        ),
        shore_power_change_pct=round(
            (current["shore_power_kwh"] - reference["shore_power_kwh"])
            / max(abs(reference["shore_power_kwh"]), 1e-9)
            * 100.0,
            4,
        ),
        reward_change=round(current["reward"] - reference["reward"], 6),
        safety_violations=current["safety_violations"],
        solver_constraint_violations=current["hybrid_solver_constraint_violations"],
        agv_missed_required_kwh=current["agv_missed_required_kwh"],
        reefer_thermal_violation_steps=current["reefer_thermal_violation_steps"],
        demand_response_delivery_pct=current["demand_response_delivery_pct"],
        demand_response_commitment_pct=round(
            current["demand_response_target_kwh"]
            / max(1.0, reference["demand_response_target_kwh"])
            * 100.0,
            4,
        ),
        rl_residual_contribution_pct=current["rl_residual_contribution_pct"],
        rl_strategy_contribution_pct=current["rl_strategy_contribution_pct"],
        rl_strategy_request_deviation_pct=current[
            "rl_strategy_request_deviation_pct"
        ],
    )
    for key in ("carbon_kg", "cost"):
        result[f"{key}_reduction_ci95"] = paired_bootstrap_interval(
            [float(item[key]) for item in candidate["episodes"]],
            [float(item[key]) for item in baseline["episodes"]],
            seed=20260830,
        )
    return result


def admission(comparison: dict[str, Any]) -> dict[str, Any]:
    checks = {
        "zero_safety_violations": comparison["safety_violations"] == 0.0,
        "zero_solver_constraint_violations": comparison[
            "solver_constraint_violations"
        ]
        == 0.0,
        "carbon_non_regression": comparison["carbon_kg_reduction_pct"] >= 0.0,
        "cost_non_regression": comparison["cost_reduction_pct"] >= 0.0,
        "throughput_non_regression": comparison["throughput_change_pct"] >= -0.1,
        "delay_non_regression": comparison["delay_minutes_reduction_pct"] >= 0.0,
        "peak_non_regression": comparison["peak_kw_reduction_pct"] >= 0.0,
        "shore_power_non_regression": comparison["shore_power_change_pct"] >= 0.0,
        "reward_improvement": comparison["reward_change"] > 0.0,
        "agv_departure_obligation": comparison["agv_missed_required_kwh"] == 0.0,
        "reefer_thermal_safety": comparison["reefer_thermal_violation_steps"] == 0.0,
        "demand_response_delivery": comparison["demand_response_delivery_pct"] >= 98.0,
        "demand_response_commitment": comparison["demand_response_commitment_pct"]
        >= 98.0,
        "jit_non_regression": comparison["jit_deviation_hours_reduction_pct"] >= 0.0,
        "anchorage_fuel_non_regression": comparison[
            "anchorage_auxiliary_fuel_liters_reduction_pct"
        ]
        >= 0.0,
        "berth_conflict_non_regression": comparison[
            "berth_conflict_hours_reduction_pct"
        ]
        >= 0.0,
        "crane_schedule_non_regression": comparison[
            "crane_task_late_teu_reduction_pct"
        ]
        >= 0.0,
        "yard_slotting_non_regression": comparison["yard_rehandles_teu_reduction_pct"]
        >= 0.0,
        "truck_flow_non_regression": comparison["truck_queue_teu_hours_reduction_pct"]
        >= 0.0,
        "maintenance_non_regression": comparison[
            "maintenance_overdue_hours_reduction_pct"
        ]
        >= 0.0,
        "carbon_ci95_non_regression": comparison["carbon_kg_reduction_ci95"][
            "ci95_low_pct"
        ]
        >= 0.0,
        "cost_ci95_non_regression": comparison["cost_reduction_ci95"]["ci95_low_pct"]
        >= 0.0,
        "material_residual_rl_contribution": comparison[
            "rl_residual_contribution_pct"
        ]
        >= 1.0,
        "material_strategy_rl_contribution": comparison[
            "rl_strategy_contribution_pct"
        ]
        >= 1.0,
    }
    failed = [key for key, passed in checks.items() if not passed]
    return {
        "status": "admitted_offline" if not failed else "blocked",
        "checks": checks,
        "failed_checks": failed,
        "production_eligible": False,
    }


def run(tuning_report_path: Path, output: Path) -> dict[str, Any]:
    tuning = json.loads(tuning_report_path.read_text(encoding="utf-8"))
    if tuning.get("schema_version") != "hybrid-rl-tuning.v1":
        raise ValueError("Expected a hybrid-rl-tuning.v1 report")
    dataset = PortDataset.load(DATASET_ID)
    starts = dataset.evaluation_start_indices("test", 24)
    print(
        json.dumps(
            {
                "status": "phase_started",
                "phase": "strong_mpc_or_baseline",
                "test_windows": len(starts),
            }
        ),
        flush=True,
    )
    baseline = evaluate("mpc_or", None, None, starts, 20260830)
    seed_results = []
    for item in tuning["final_seed_results"]:
        print(
            json.dumps(
                {
                    "status": "phase_started",
                    "phase": "hybrid_rl_seed_evaluation",
                    "algorithm": item["algorithm"],
                    "seed": item["seed"],
                }
            ),
            flush=True,
        )
        artifact = PROJECT_ROOT / item["artifact_path"]
        candidate = evaluate(
            "rl",
            str(artifact),
            item["algorithm"],
            starts,
            int(item["seed"]),
        )
        comparison = _comparison(candidate, baseline)
        seed_results.append(
            {
                "seed": item["seed"],
                "algorithm": item["algorithm"],
                "artifact_path": item["artifact_path"],
                "artifact_sha256": item["artifact_sha256"],
                "metrics": candidate["mean"],
                "versus_mpc_or": comparison,
                "admission": admission(comparison),
            }
        )
    admitted = [item for item in seed_results if item["admission"]["status"] == "admitted_offline"]
    champion = (
        max(admitted, key=lambda item: float(item["versus_mpc_or"]["reward_change"]))
        if len(admitted) == len(seed_results) and admitted
        else None
    )
    report = {
        "schema_version": "hybrid-rl-business-value.v1",
        "generated_at": utc_now(),
        "evidence_label": "OFFLINE_PUBLIC_ANCHOR_ENGINEERING_SCENARIO_NOT_FIELD_KPI",
        "dataset": dataset.describe(),
        "tuning_report": str(tuning_report_path.relative_to(PROJECT_ROOT)),
        "tuning_report_sha256": sha256_file(tuning_report_path),
        "protocol": {
            "fit_split": "train",
            "selection_split": "validation",
            "final_report_split": "test",
            "test_window_count": len(starts),
            "test_start_indices": starts,
            "baseline": "four-step causal MPC plus deterministic aggregate constraint projection",
            "champion_requires_every_final_seed_to_pass": True,
        },
        "baseline_mpc_or": {key: value for key, value in baseline.items() if key != "episodes"},
        "seed_results": seed_results,
        "champion_status": "admitted_offline" if champion else "no_rl_policy_admitted",
        "champion": champion,
        "production_eligible": False,
        "code_sha256": {
            path: sha256_file(PROJECT_ROOT / path)
            for path in (
                "backend/app/rl/environment.py",
                "backend/app/rl/hybrid_control.py",
                "backend/app/rl/hybrid_benchmark.py",
                "scripts/build_hybrid_rl_dataset.py",
            )
        },
        "production_boundary": {
            "simulation_mode": True,
            "live_data_verified": False,
            "dispatch_allowed": False,
            "production_authority": False,
        },
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def verify_report(path: Path) -> dict[str, Any]:
    report = json.loads(path.read_text(encoding="utf-8"))
    tuning_path = PROJECT_ROOT / str(report.get("tuning_report", ""))
    tuning = (
        json.loads(tuning_path.read_text(encoding="utf-8"))
        if tuning_path.is_file()
        else {}
    )
    expected_benchmark_code = {
        "backend/app/rl/environment.py",
        "backend/app/rl/hybrid_control.py",
        "backend/app/rl/hybrid_benchmark.py",
        "scripts/build_hybrid_rl_dataset.py",
    }
    expected_tuning_code = {
        "backend/app/rl/environment.py",
        "backend/app/rl/hybrid_control.py",
        "backend/app/rl/training.py",
        "backend/app/rl/tuning.py",
        "backend/app/rl/hybrid_tuning.py",
        "scripts/build_hybrid_rl_dataset.py",
    }
    tuning_artifacts = [
        *tuning.get("search_results", []),
        *tuning.get("final_seed_results", []),
    ]
    seed_results = report.get("seed_results", [])
    admitted = [
        item for item in seed_results if item.get("admission", {}).get("status") == "admitted_offline"
    ]
    champion_consistent = (
        report.get("champion_status") == "admitted_offline"
        and report.get("champion") is not None
        and len(admitted) == 3
    ) or (
        report.get("champion_status") == "no_rl_policy_admitted"
        and report.get("champion") is None
        and len(admitted) < 3
    )
    checks = {
        "schema": report.get("schema_version") == "hybrid-rl-business-value.v1",
        "dataset_hash": PortDataset.load(DATASET_ID).package_sha256
        == report.get("dataset", {}).get("package_sha256"),
        "tuning_hash": sha256_file(PROJECT_ROOT / report["tuning_report"])
        == report.get("tuning_report_sha256"),
        "code_hashes": set(report.get("code_sha256", {})) == expected_benchmark_code
        and all(
            sha256_file(PROJECT_ROOT / name) == expected
            for name, expected in report.get("code_sha256", {}).items()
        ),
        "three_final_seeds": len(seed_results) == 3
        and {int(item["seed"]) for item in seed_results} == {17, 37, 59},
        "artifacts": len(seed_results) == 3
        and all(
            sha256_file(PROJECT_ROOT / item["artifact_path"]) == item["artifact_sha256"]
            for item in seed_results
        ),
        "champion_consistent": champion_consistent,
        "tuning_schema": tuning.get("schema_version") == "hybrid-rl-tuning.v1",
        "tuning_code_hashes": set(tuning.get("code_sha256", {})) == expected_tuning_code
        and all(
            sha256_file(PROJECT_ROOT / name) == expected
            for name, expected in tuning.get("code_sha256", {}).items()
        ),
        "tuning_artifacts": len(tuning_artifacts) == 9
        and all(
            sha256_file(PROJECT_ROOT / item["artifact_path"])
            == item["artifact_sha256"]
            for item in tuning_artifacts
        ),
        "production_disabled": report.get("production_boundary")
        == {
            "simulation_mode": True,
            "live_data_verified": False,
            "dispatch_allowed": False,
            "production_authority": False,
        },
    }
    return {"ok": all(checks.values()), "checks": checks}


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Evaluate v6 hybrid RL business value")
    result.add_argument("--tuning-report", type=Path, default=DEFAULT_TUNING_REPORT)
    result.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    result.add_argument("--verify-report", type=Path)
    return result


def main() -> None:
    args = parser().parse_args()
    if args.verify_report:
        result = verify_report(args.verify_report)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        raise SystemExit(0 if result["ok"] else 1)
    report = run(args.tuning_report, args.output)
    print(
        json.dumps(
            {
                "status": "written",
                "output": str(args.output),
                "champion_status": report["champion_status"],
            }
        )
    )


if __name__ == "__main__":
    main()
