from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import time
from typing import Any

import numpy as np

from app.rl.catalog import ALGORITHM_CATALOG
from app.rl.dataset import DEFAULT_DATASET_ID, PROJECT_ROOT, PortDataset
from app.rl.robust import CausalForecastPortEnv
from app.rl.training import TrainingService


SEARCH_SPACE_PATH = PROJECT_ROOT / "configs" / "rl_search_space.json"
DEFAULT_OUTPUT = PROJECT_ROOT / "reports" / "rl_tuning_selection.json"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def portable_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(PROJECT_ROOT.resolve()).as_posix()
    except ValueError:
        return str(path)


def load_search_space(path: Path = SEARCH_SPACE_PATH) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    algorithms = payload.get("algorithms") or {}
    expected = {
        name
        for name, item in ALGORITHM_CATALOG.items()
        if item["family"] == "reinforcement_learning"
    }
    if set(algorithms) != expected:
        raise ValueError(
            f"Search-space algorithms must be {sorted(expected)}, got {sorted(algorithms)}"
        )
    for algorithm, candidates in algorithms.items():
        if not isinstance(candidates, list) or len(candidates) < 2:
            raise ValueError(f"{algorithm} requires at least two tuning candidates")
    protocol = payload.get("selection_protocol") or {}
    required_protocol = {
        "fit_split": "train",
        "selection_split": "validation",
        "final_report_split": "test",
    }
    for key, expected_value in required_protocol.items():
        if protocol.get(key) != expected_value:
            raise ValueError(f"selection_protocol.{key} must be {expected_value}")
    return payload


def _mean_totals(items: list[dict[str, Any]]) -> dict[str, float]:
    keys = (
        "reward",
        "energy_kwh",
        "carbon_kg",
        "cost",
        "delay_minutes",
        "processed_teu",
        "safety_violations",
        "peak_violation_steps",
        "delay_violation_steps",
        "soc_violation_steps",
        "peak_kw",
        "hybrid_solver_projection_l1",
        "hybrid_solver_constraint_violations",
        "jit_deviation_hours",
        "anchorage_auxiliary_fuel_liters",
        "berth_conflict_hours",
        "crane_task_late_teu",
        "yard_rehandles_teu",
        "truck_queue_teu_hours",
        "maintenance_overdue_hours",
        "maintenance_performed_ratio",
    )
    return {key: round(float(np.mean([float(item[key]) for item in items])), 6) for key in keys}


def evaluate_model(
    service: TrainingService,
    model: Any,
    config: dict[str, Any],
    split: str,
) -> dict[str, Any]:
    if split not in {"validation", "test"}:
        raise ValueError("Tuning evaluation is restricted to validation or test")
    dataset = PortDataset.load(config["data_file"])
    episodes: list[dict[str, Any]] = []
    frame = dataset.split(split)
    for row_index in dataset.evaluation_start_indices(split, config["episode_hours"]):
        hours = (
            min(config["episode_hours"], len(frame) - row_index)
            if dataset.temporal_mode == "sequential_rows"
            else config["episode_hours"]
        )
        env = CausalForecastPortEnv(
            dataset=config["data_file"],
            split=split,
            action_mode="discrete" if config["algorithm"] == "dqn" else "continuous",
            reward_weights=config.get("reward_weights"),
            episode_hours=hours,
            render_mode=None,
        )
        episodes.append(
            service.rollout(
                env,
                model,
                config["algorithm"],
                row_index,
                int(config["seed"]),
            )
        )
    totals = _mean_totals(episodes)
    return {
        "split": split,
        "episodes": len(episodes),
        "steps": int(sum(int(item["steps"]) for item in episodes)),
        "mean": totals,
        "selection_score": (
            totals["reward"]
            if totals["safety_violations"] <= 0.0
            else -1_000_000.0 - totals["safety_violations"]
        ),
    }


def train_candidate(
    algorithm: str,
    candidate: dict[str, Any],
    dataset: str,
    total_steps: int,
    seed: int,
    episode_hours: int,
) -> tuple[Any, dict[str, Any], dict[str, Any]]:
    service = TrainingService()
    config = service.validate_config(
        {
            "algorithm": algorithm,
            "dataset_id": dataset,
            "total_steps": total_steps,
            "seed": seed,
            "episode_hours": episode_hours,
            **candidate,
        }
    )
    if config["validation_split"] != "validation" or config["test_split"] != "test":
        raise RuntimeError("Temporal split contract was not preserved")
    env = CausalForecastPortEnv(
        dataset=config["data_file"],
        split="train",
        action_mode="discrete" if algorithm == "dqn" else "continuous",
        reward_weights=config.get("reward_weights"),
        episode_hours=config["episode_hours"],
        render_mode=None,
    )
    model = service.build_model(config, env)
    started = time.perf_counter()
    model.learn(total_timesteps=config["total_steps"], progress_bar=False)
    duration = time.perf_counter() - started
    validation = evaluate_model(service, model, config, "validation")
    evidence = {
        "duration_sec": round(duration, 3),
        "actual_timesteps": int(model.num_timesteps),
        "resolved_hyperparameters": {
            "policy": "MlpPolicy",
            "learning_rate": config["learning_rate"],
            "batch_size": config["batch_size"],
            "gamma": config["gamma"],
            "tau": config["tau"],
            "entropy_coef": float(config.get("entropy_coef") or 0.0),
            "exploration_fraction": float(config.get("exploration_fraction") or 0.25),
            "episode_hours": config["episode_hours"],
        },
        "fit_split": "train",
        "selection_split": "validation",
        "test_accessed": False,
        "render_during_fit_or_selection": False,
        "validation": validation,
    }
    return model, config, evidence


def tune_algorithm(
    algorithm: str,
    candidates: list[dict[str, Any]],
    dataset: str,
    total_steps: int,
    seed: int,
    episode_hours: int,
    artifact_dir: Path,
    final_seeds: list[int],
) -> dict[str, Any]:
    trials: list[dict[str, Any]] = []
    for index, candidate in enumerate(candidates):
        print(
            f"tuning: algorithm={algorithm} candidate={index + 1}/{len(candidates)}",
            file=sys.stderr,
            flush=True,
        )
        _, _, evidence = train_candidate(
            algorithm,
            candidate,
            dataset,
            total_steps,
            seed,
            episode_hours,
        )
        trials.append(
            {
                "candidate_index": index,
                "hyperparameters": candidate,
                **evidence,
            }
        )
    eligible = [
        trial for trial in trials if float(trial["validation"]["mean"]["safety_violations"]) <= 0.0
    ]
    selected = max(
        eligible or trials,
        key=lambda item: float(item["validation"]["selection_score"]),
    )
    selected_index = int(selected["candidate_index"])
    selected_candidate = candidates[selected_index]
    final_results: list[dict[str, Any]] = []
    if final_seeds:
        artifact_dir.mkdir(parents=True, exist_ok=True)
        for final_seed in final_seeds:
            print(
                f"tuning: algorithm={algorithm} final_seed={final_seed}",
                file=sys.stderr,
                flush=True,
            )
            model, config, evidence = train_candidate(
                algorithm,
                selected_candidate,
                dataset,
                total_steps,
                final_seed,
                episode_hours,
            )
            test = evaluate_model(TrainingService(), model, config, "test")
            artifact_base = artifact_dir / f"{algorithm}-seed-{final_seed}"
            model.save(str(artifact_base))
            artifact_path = artifact_base.with_suffix(".zip")
            final_results.append(
                {
                    "seed": final_seed,
                    "training": evidence,
                    "test": test,
                    "artifact_path": portable_path(artifact_path),
                    "artifact_sha256": sha256_file(artifact_path),
                }
            )
    return {
        "algorithm": algorithm,
        "selection_seed": seed,
        "selected_candidate_index": selected_index,
        "selected_hyperparameters": selected_candidate,
        "selection_reason": (
            "highest validation return among zero-violation candidates; "
            "test split remained inaccessible during selection"
        ),
        "trials": trials,
        "final_seed_results": final_results,
    }


def build_parser() -> argparse.ArgumentParser:
    algorithms = [
        name
        for name, item in ALGORITHM_CATALOG.items()
        if item["family"] == "reinforcement_learning"
    ]
    parser = argparse.ArgumentParser(description="Leakage-safe RL hyperparameter selection")
    parser.add_argument("--algorithm", choices=[*algorithms, "all"], default="all")
    parser.add_argument("--dataset", default=DEFAULT_DATASET_ID)
    parser.add_argument("--steps", type=int, default=10_000)
    parser.add_argument("--seed", type=int, default=20260724)
    parser.add_argument("--episode-hours", type=int, default=24)
    parser.add_argument(
        "--final-seeds",
        default="",
        help="Comma-separated final seeds. Test is accessed only when this is non-empty.",
    )
    parser.add_argument("--search-space", type=Path, default=SEARCH_SPACE_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    search = load_search_space(args.search_space)
    final_seeds = [int(value.strip()) for value in args.final_seeds.split(",") if value.strip()]
    algorithms = sorted(search["algorithms"]) if args.algorithm == "all" else [args.algorithm]
    artifact_dir = args.output.parent / f"{args.output.stem}_artifacts"
    results = [
        tune_algorithm(
            algorithm=algorithm,
            candidates=search["algorithms"][algorithm],
            dataset=args.dataset,
            total_steps=args.steps,
            seed=args.seed,
            episode_hours=args.episode_hours,
            artifact_dir=artifact_dir,
            final_seeds=final_seeds,
        )
        for algorithm in algorithms
    ]
    dataset = PortDataset.load(args.dataset)
    report = {
        "schema_version": "1.0",
        "generated_at": utc_now(),
        "evidence_label": (
            "RL_SMOKE_WIRING_ONLY" if args.steps < 10_000 else "OFFLINE_RL_EXPERIMENT_NOT_FIELD_KPI"
        ),
        "dataset_id": dataset.dataset_id,
        "dataset_package_sha256": dataset.package_sha256,
        "environment_id": dataset.environment_id,
        "search_space_path": portable_path(args.search_space),
        "search_space_sha256": sha256_file(args.search_space),
        "code_sha256": {
            path: sha256_file(PROJECT_ROOT / path)
            for path in (
                "backend/app/rl/environment.py",
                "backend/app/rl/training.py",
                "backend/app/rl/tuning.py",
            )
        },
        "runtime": TrainingService().capabilities()["runtime"],
        "total_steps_per_fit": args.steps,
        "selection_protocol": search["selection_protocol"],
        "test_accessed": bool(final_seeds),
        "algorithms": results,
        "limitations": [
            "A smoke-labelled run validates wiring only and must not be cited as convergence.",
            "Offline test results are scenario outputs, not field or production KPIs.",
            "At least three final seeds and a sufficient training budget are required for resume metrics.",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"status": "written", "output": str(args.output)}))


if __name__ == "__main__":
    main()
