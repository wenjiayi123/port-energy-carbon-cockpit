"""Reproducible three-seed CEM reinforcement-learning experiment.

Train only on 2020-2022. Select checkpoints only on 2023. Freeze all seeds
before opening the 2024 retrospective test; do not overwrite earlier attempts.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np

from app.rl.dataset import PROJECT_ROOT
from app.rl.dispatch_policy_v7 import (
    BOUNDARY, DATASET_ID, FEATURES, OUTPUTS, SHAPE, CachedCausalEnv,
    DispatchPolicyV7, episode, objective,
)
from app.rl.robust import paired_bootstrap_interval

SEEDS = (17, 37, 59)
ITERATIONS = 32
POPULATION = 16
ELITES = 4
TRAIN_WINDOWS_PER_ITERATION = 6


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def means(episodes: list[dict[str, Any]]) -> dict[str, float]:
    return {
        key: float(np.mean([r[key] for r in episodes]))
        for key, value in episodes[0].items()
        if isinstance(value, (int, float)) and key != "start_index"
    }


def compare(current: list[dict[str, Any]], baseline: list[dict[str, Any]]) -> dict[str, Any]:
    if [r["start_index"] for r in current] != [r["start_index"] for r in baseline]:
        raise ValueError("Paired evaluation windows do not match")
    a, b = means(current), means(baseline)
    minimize = (
        "cost", "settled_cost", "carbon_kg", "delay_minutes", "peak_kw",
        "jit_deviation_hours", "anchorage_auxiliary_fuel_liters", "berth_conflict_hours",
        "crane_task_late_teu", "yard_rehandles_teu", "truck_queue_teu_hours",
        "maintenance_overdue_hours", "demand_response_non_delivery_kwh",
    )
    changes = {f"{k}_reduction_pct": (b[k] - a[k]) / max(abs(b[k]), 1e-9) * 100
               for k in minimize}
    for key in ("processed_teu", "shore_power_kwh", "demand_response_target_kwh"):
        changes[f"{key}_change_pct"] = (a[key] - b[key]) / max(abs(b[key]), 1e-9) * 100
    checks = {f"{k}_non_regression": a[k] <= b[k] + 1e-6 for k in minimize}
    checks.update({f"{k}_non_regression": a[k] >= b[k] - 1e-6 for k in (
        "processed_teu", "shore_power_kwh", "demand_response_target_kwh",
    )})
    checks.update({f"zero_{k}": a[k] <= 1e-9 for k in (
        "safety_violations", "hybrid_solver_constraint_violations",
        "agv_missed_required_kwh", "reefer_thermal_violation_steps",
    )})
    ci = {k: paired_bootstrap_interval([r[k] for r in current], [r[k] for r in baseline],
                                     seed=20260907) for k in ("settled_cost", "carbon_kg")}
    checks.update({f"{k}_ci95_non_regression": v["ci95_low_pct"] >= 0.0
                   for k, v in ci.items()})
    checks["material_learned_saving"] = changes["settled_cost_reduction_pct"] >= 0.1
    return {"changes": changes, "ci95": ci, "checks": checks,
            "failed_checks": [k for k, value in checks.items() if not value]}


def _fit(args: tuple[int, str]) -> dict[str, Any]:
    seed, output = args
    root = Path(output) / f"seed-{seed}"
    root.mkdir()
    rng = np.random.default_rng(seed)
    train = CachedCausalEnv(dataset=DATASET_ID, split="train")
    validation = CachedCausalEnv(dataset=DATASET_ID, split="validation")
    validation_starts = validation.dataset.evaluation_start_indices("validation", 24)
    baseline = [episode(validation, DispatchPolicyV7(), i) for i in validation_starts]
    write_json(root / "validation_reference.json", baseline)
    mean = np.zeros(SHAPE)
    std = np.full(SHAPE, 0.4)
    incumbent = mean.copy()
    checkpoints: list[dict[str, Any]] = []
    trace: list[dict[str, Any]] = []
    actual_steps = 0
    for iteration in range(ITERATIONS + 1):
        if iteration:
            # Stratify time without looking at outcomes. Every candidate sees
            # identical windows in a generation (common random numbers).
            edges = np.linspace(0, len(train.frame) - 24, TRAIN_WINDOWS_PER_ITERATION + 1)
            starts = [int(rng.integers(int(lo), max(int(lo) + 1, int(hi))))
                      for lo, hi in zip(edges[:-1], edges[1:], strict=True)]
            population = rng.normal(mean, std, size=(POPULATION, *SHAPE))
            population[0], population[1] = mean, incumbent
            scores = []
            for weights in population:
                policy = DispatchPolicyV7(weights)
                outcomes = [episode(train, policy, i) for i in starts]
                scores.append(float(np.mean([objective(r) for r in outcomes])))
            actual_steps += POPULATION * len(starts) * 24
            elite_indices = np.argsort(scores)[-ELITES:]
            elite = population[elite_indices]
            incumbent = population[int(np.argmax(scores))].copy()
            mean = 0.3 * mean + 0.7 * elite.mean(axis=0)
            std = np.maximum(0.035, 0.3 * std + 0.7 * elite.std(axis=0))
            trace.append({"iteration": iteration, "actual_training_steps": actual_steps,
                          "start_indices": starts, "population_objectives": scores,
                          "search_std_mean": float(std.mean())})
        if iteration % 4 == 0:
            policy = DispatchPolicyV7(incumbent)
            outcomes = [episode(validation, policy, i) for i in validation_starts]
            comparison = compare(outcomes, baseline)
            checkpoint = {
                "iteration": iteration, "actual_training_steps": actual_steps,
                "objective": float(np.mean([objective(r) for r in outcomes])),
                "validation_mean": means(outcomes), "versus_service_reference": comparison,
                "weights": incumbent.tolist(),
            }
            checkpoints.append(checkpoint)
            write_json(root / f"checkpoint-{iteration:03d}.json", checkpoint)
            write_json(root / "training_trace.json", trace)
            print(json.dumps({"seed": seed, "iteration": iteration, "steps": actual_steps,
                              "cost_saving_pct": comparison["changes"]["settled_cost_reduction_pct"],
                              "failed": comparison["failed_checks"]}), flush=True)
    # Select with full business constraints first, then the validation objective.
    # A blocked checkpoint remains blocked; never relabel it as admitted.
    def rank(item: dict[str, Any]) -> tuple[bool, float]:
        return not item["versus_service_reference"]["failed_checks"], item["objective"]
    selected = max(checkpoints, key=rank)
    selected_payload = {
        "schema_version": "dispatch-cem-policy.v7", "algorithm": "cem_policy_search_rl",
        "seed": seed, "features": list(FEATURES), "outputs": list(OUTPUTS),
        "dataset_package_sha256": train.dataset.package_sha256,
        "selected_iteration": selected["iteration"], "weights": selected["weights"],
        "selection_split": "validation", "test_accessed": False,
        "production_boundary": BOUNDARY,
    }
    write_json(root / "policy.json", selected_payload)
    tail = [c["objective"] for c in checkpoints[-4:]]
    plateau = (max(tail) - min(tail)) / max(abs(float(np.mean(tail))), 1e-9) * 100
    result = {"seed": seed, "actual_training_steps": actual_steps,
              "selected": selected, "validation_tail_range_pct": plateau,
              "convergence_status": "validation_plateau" if plateau <= 0.25 else "not_plateaued",
              "policy_sha256": digest(root / "policy.json"),
              "policy_path": str((root / "policy.json").relative_to(PROJECT_ROOT)),
              "checkpoints": [{k: v for k, v in c.items() if k != "weights"} for c in checkpoints]}
    write_json(root / "training_result.json", result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = args.output.resolve()
    root.mkdir(parents=True, exist_ok=False)
    protocol = {
        "algorithm": "cross_entropy_method_episodic_policy_search",
        "fit_split": "train", "selection_split": "validation", "test_split": "test",
        "test_is_retrospective": True,
        "test_note": "2024 was used by v6; this is a regression test, not a new untouched year.",
        "seeds": SEEDS, "iterations": ITERATIONS, "population": POPULATION,
        "elites": ELITES, "train_windows_per_iteration": TRAIN_WINDOWS_PER_ITERATION,
        "convergence_gate": "last four validation objective range <= 0.25 percent",
        "admission_gate": "every seed passes business constraints and >= 0.1 percent learned saving",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "code_sha256": {name: digest(PROJECT_ROOT / name) for name in (
            "backend/app/rl/dispatch_policy_v7.py", "backend/app/rl/train_dispatch_v7.py",
            "backend/app/rl/environment.py", "backend/app/rl/robust.py",
            "backend/app/rl/hybrid_control.py",
        )},
        "production_boundary": BOUNDARY,
    }
    write_json(root / "protocol.json", protocol)
    with ProcessPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(_fit, [(seed, str(root)) for seed in SEEDS]))
    write_json(root / "training_results.json", results)
    print(json.dumps({"status": "all_policies_frozen", "output": str(root)}), flush=True)


if __name__ == "__main__":
    main()
