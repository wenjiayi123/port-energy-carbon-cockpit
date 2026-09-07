"""Validation-only continuation of frozen v7 models; previous attempts survive."""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
import json
from pathlib import Path

import numpy as np

from app.rl.dataset import PROJECT_ROOT
from app.rl.dispatch_policy_v7 import (
    BOUNDARY, DATASET_ID, FEATURES, OUTPUTS, SHAPE, DispatchEnvV7, DispatchPolicyV7,
    episode, objective,
)
from app.rl.train_dispatch_v7 import compare, digest, means, write_json

ITERATIONS = 24
POPULATION = 12


def refine(args):
    source, destination, previous = args
    seed = previous["seed"]
    root = Path(destination) / f"seed-{seed}"
    root.mkdir()
    policy_path = PROJECT_ROOT / previous["policy_path"]
    if digest(policy_path) != previous["policy_sha256"]:
        raise ValueError("Parent policy integrity mismatch")
    mean = np.array(json.loads(policy_path.read_text())["weights"])
    incumbent = mean.copy()
    std = np.full(SHAPE, 0.07)
    rng = np.random.default_rng(seed + 20260907)
    train = DispatchEnvV7(dataset=DATASET_ID, split="train")
    validation = DispatchEnvV7(dataset=DATASET_ID, split="validation")
    starts = validation.dataset.evaluation_start_indices("validation", 24)
    baseline = [episode(validation, DispatchPolicyV7(), i) for i in starts]
    write_json(root / "validation_reference.json", baseline)
    checkpoints, trace = [], []
    steps = previous["actual_training_steps"]
    for iteration in range(ITERATIONS + 1):
        if iteration:
            edges = np.linspace(0, len(train.frame) - 24, 7)
            windows = [int(rng.integers(int(lo), int(hi)))
                       for lo, hi in zip(edges[:-1], edges[1:], strict=True)]
            population = rng.normal(mean, std, (POPULATION, *SHAPE))
            population[0], population[1] = incumbent, mean
            scores = [float(np.mean([objective(episode(train, DispatchPolicyV7(w), i))
                                     for i in windows])) for w in population]
            elites = population[np.argsort(scores)[-4:]]
            incumbent = population[int(np.argmax(scores))].copy()
            mean = 0.3 * mean + 0.7 * elites.mean(axis=0)
            std = np.maximum(0.015, 0.3 * std + 0.7 * elites.std(axis=0))
            steps += POPULATION * 6 * 24
            trace.append({"iteration": iteration, "actual_training_steps": steps,
                          "start_indices": windows, "population_objectives": scores,
                          "search_std_mean": float(std.mean())})
        if iteration % 4 == 0:
            results = [episode(validation, DispatchPolicyV7(incumbent), i) for i in starts]
            comparison = compare(results, baseline)
            checkpoint = {"iteration": iteration, "actual_training_steps": steps,
                          "objective": float(np.mean([objective(r) for r in results])),
                          "weights": incumbent.tolist(), "validation_mean": means(results),
                          "versus_service_reference": comparison}
            checkpoints.append(checkpoint)
            write_json(root / f"checkpoint-{iteration:03d}.json", checkpoint)
            write_json(root / "training_trace.json", trace)
            print(json.dumps({"seed": seed, "iteration": iteration, "steps": steps,
                              "saving_pct": comparison["changes"]["settled_cost_reduction_pct"],
                              "failed": comparison["failed_checks"]}), flush=True)
    selected = max(checkpoints, key=lambda c: (
        not c["versus_service_reference"]["failed_checks"], c["objective"],
    ))
    tail = [c["objective"] for c in checkpoints[-4:]]
    plateau = (max(tail) - min(tail)) / abs(float(np.mean(tail))) * 100
    write_json(root / "policy.json", {
        "schema_version": "dispatch-cem-policy.v7", "algorithm": "cem_policy_search_rl",
        "seed": seed, "features": list(FEATURES), "outputs": list(OUTPUTS),
        "dataset_package_sha256": train.dataset.package_sha256,
        "selected_iteration": selected["iteration"], "weights": selected["weights"],
        "selection_split": "validation", "test_accessed": False,
        "parent_policy_path": previous["policy_path"], "parent_policy_sha256": previous["policy_sha256"],
        "production_boundary": BOUNDARY,
    })
    result = {"seed": seed, "actual_training_steps": steps, "selected": selected,
              "validation_tail_range_pct": plateau,
              "convergence_status": "validation_plateau" if plateau <= 0.25 else "not_plateaued",
              "policy_path": str((root / "policy.json").relative_to(PROJECT_ROOT)),
              "policy_sha256": digest(root / "policy.json"),
              "parent_policy_path": previous["policy_path"], "parent_policy_sha256": previous["policy_sha256"],
              "checkpoints": [{k: v for k, v in c.items() if k != "weights"} for c in checkpoints]}
    write_json(root / "training_result.json", result)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    source, root = args.source.resolve(), args.destination.resolve()
    root.mkdir(parents=True, exist_ok=False)
    previous = json.loads((source / "training_results.json").read_text())
    protocol = json.loads((source / "protocol.json").read_text())
    protocol.update({
        "created_at": datetime.now(timezone.utc).isoformat(),
        "parent_training_results": str((source / "training_results.json").relative_to(PROJECT_ROOT)),
        "parent_training_results_sha256": digest(source / "training_results.json"),
        "continuation_reason": "Seed 17 was still improving on validation; no test metrics used.",
        "iterations": ITERATIONS, "population": POPULATION,
        "initial_std": 0.07, "std_floor": 0.015,
    })
    protocol["code_sha256"]["backend/app/rl/refine_dispatch_v7.py"] = digest(Path(__file__))
    write_json(root / "protocol.json", protocol)
    with ProcessPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(refine, [(str(source), str(root), p) for p in previous]))
    write_json(root / "training_results.json", results)
    print(json.dumps({"status": "all_policies_frozen", "output": str(root)}), flush=True)


if __name__ == "__main__":
    main()
