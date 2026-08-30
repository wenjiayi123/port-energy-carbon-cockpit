from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time
from typing import Any

import numpy as np

from app.rl.dataset import PROJECT_ROOT, PortDataset
from app.rl.training import TrainingService
from app.rl.tuning import evaluate_model, portable_path, train_candidate


DATASET_ID = "port_la_2020_2024_operational_flex_hourly"
ALGORITHM = "ppo"
FINAL_SEEDS = (17, 37, 59)
BUDGETS = (50_000, 100_000)
WORKERS = 3
HYPERPARAMETERS = {
    "learning_rate": 0.0003,
    "batch_size": 64,
    "gamma": 0.99,
    "entropy_coef": 0.0,
}
DEFAULT_OUTPUT = PROJECT_ROOT / "reports/rl_refinement_operational_flex_v5_100k.json"
DEFAULT_ARTIFACT_DIR = (
    PROJECT_ROOT / "reports/rl_refinement_operational_flex_v5_100k_artifacts"
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _set_single_thread_runtime() -> None:
    try:
        import torch

        torch.set_num_threads(1)
        torch.set_num_interop_threads(1)
    except (ImportError, RuntimeError):
        pass


def _continued_evidence(
    base: dict[str, Any],
    *,
    duration_sec: float,
    actual_timesteps: int,
    validation: dict[str, Any],
) -> dict[str, Any]:
    return {
        **{key: value for key, value in base.items() if key != "validation"},
        "duration_sec": round(duration_sec, 3),
        "actual_timesteps": actual_timesteps,
        "validation": validation,
    }


def _train_seed(payload: tuple[int, str]) -> dict[str, Any]:
    seed, artifact_dir_value = payload
    _set_single_thread_runtime()
    artifact_dir = Path(artifact_dir_value)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    model, config, evidence_50k = train_candidate(
        ALGORITHM,
        HYPERPARAMETERS,
        DATASET_ID,
        BUDGETS[0],
        seed,
        24,
    )
    artifact_50k_base = artifact_dir / f"ppo-50k-seed-{seed}"
    model.save(str(artifact_50k_base))
    artifact_50k = artifact_50k_base.with_suffix(".zip")

    continued_started = time.perf_counter()
    model.learn(
        total_timesteps=BUDGETS[1] - BUDGETS[0],
        reset_num_timesteps=False,
        progress_bar=False,
    )
    continued_duration = time.perf_counter() - continued_started
    config_100k = {**config, "total_steps": BUDGETS[1]}
    validation_100k = evaluate_model(
        TrainingService(),
        model,
        config_100k,
        "validation",
    )
    evidence_100k = _continued_evidence(
        evidence_50k,
        duration_sec=float(evidence_50k["duration_sec"]) + continued_duration,
        actual_timesteps=int(model.num_timesteps),
        validation=validation_100k,
    )
    artifact_100k_base = artifact_dir / f"ppo-100k-seed-{seed}"
    model.save(str(artifact_100k_base))
    artifact_100k = artifact_100k_base.with_suffix(".zip")
    return {
        "seed": seed,
        "budgets": {
            "50000": {
                "training": evidence_50k,
                "artifact_path": portable_path(artifact_50k),
                "artifact_sha256": sha256_file(artifact_50k),
            },
            "100000": {
                "training": evidence_100k,
                "artifact_path": portable_path(artifact_100k),
                "artifact_sha256": sha256_file(artifact_100k),
            },
        },
    }


def _test_selected(payload: tuple[int, int, str]) -> dict[str, Any]:
    seed, budget, artifact_path = payload
    _set_single_thread_runtime()
    service = TrainingService()
    config = service.validate_config(
        {
            "algorithm": ALGORITHM,
            "dataset_id": DATASET_ID,
            "total_steps": budget,
            "seed": seed,
            "episode_hours": 24,
            **HYPERPARAMETERS,
        }
    )
    model = service._load_model(ALGORITHM, artifact_path)
    return evaluate_model(service, model, config, "test")


def _budget_summary(seed_results: list[dict[str, Any]], budget: int) -> dict[str, Any]:
    items = [item["budgets"][str(budget)]["training"]["validation"] for item in seed_results]
    returns = [float(item["mean"]["reward"]) for item in items]
    safety = [float(item["mean"]["safety_violations"]) for item in items]
    return {
        "budget": budget,
        "validation_mean_return": round(float(np.mean(returns)), 6),
        "validation_mean_safety_violations": round(float(np.mean(safety)), 6),
        "all_seed_zero_validation_safety": all(value == 0.0 for value in safety),
        "seed_validation": [
            {
                "seed": item["seed"],
                "mean": item["budgets"][str(budget)]["training"]["validation"]["mean"],
            }
            for item in seed_results
        ],
    }


def run(output: Path, artifact_dir: Path) -> dict[str, Any]:
    dataset = PortDataset.load(DATASET_ID)
    print(
        json.dumps(
            {
                "status": "phase_started",
                "phase": "parallel_validation_only_refinement",
                "seeds": list(FINAL_SEEDS),
                "budgets": list(BUDGETS),
                "workers": WORKERS,
            }
        ),
        flush=True,
    )
    with ProcessPoolExecutor(max_workers=WORKERS) as executor:
        seed_results = list(
            executor.map(
                _train_seed,
                [(seed, str(artifact_dir)) for seed in FINAL_SEEDS],
            )
        )
    summaries = [_budget_summary(seed_results, budget) for budget in BUDGETS]
    eligible = [item for item in summaries if item["all_seed_zero_validation_safety"]]
    selected_summary = max(
        eligible or summaries,
        key=lambda item: (
            item["all_seed_zero_validation_safety"],
            -item["validation_mean_safety_violations"],
            item["validation_mean_return"],
        ),
    )
    selected_budget = int(selected_summary["budget"])
    selected_records = [item["budgets"][str(selected_budget)] for item in seed_results]
    print(
        json.dumps(
            {
                "status": "phase_started",
                "phase": "selected_budget_test_evaluation",
                "selected_budget": selected_budget,
                "selection_basis": "validation_only",
            }
        ),
        flush=True,
    )
    with ProcessPoolExecutor(max_workers=WORKERS) as executor:
        tests = list(
            executor.map(
                _test_selected,
                [
                    (
                        seed,
                        selected_budget,
                        str(PROJECT_ROOT / record["artifact_path"]),
                    )
                    for seed, record in zip(FINAL_SEEDS, selected_records, strict=True)
                ],
            )
        )
    final_seed_results = [
        {
            "seed": seed,
            "training": record["training"],
            "test": test,
            "artifact_path": record["artifact_path"],
            "artifact_sha256": record["artifact_sha256"],
        }
        for seed, record, test in zip(FINAL_SEEDS, selected_records, tests, strict=True)
    ]
    report = {
        "schema_version": "operational-flex-refinement.v1",
        "generated_at": utc_now(),
        "evidence_label": "OFFLINE_RL_REFINEMENT_NOT_FIELD_KPI",
        "dataset_id": dataset.dataset_id,
        "dataset_package_sha256": dataset.package_sha256,
        "environment_id": dataset.environment_id,
        "total_steps_per_fit": selected_budget,
        "selection_protocol": {
            "fit_split": "train",
            "selection_split": "validation",
            "final_report_split": "test",
            "candidate_axis": "continued training budget only",
            "test_accessed_after_budget_selection": True,
        },
        "test_accessed": True,
        "runtime": TrainingService().capabilities()["runtime"],
        "algorithms": [
            {
                "algorithm": ALGORITHM,
                "selection_seed": None,
                "selected_candidate_index": list(BUDGETS).index(selected_budget),
                "selected_hyperparameters": {
                    **HYPERPARAMETERS,
                    "training_budget": selected_budget,
                },
                "selection_reason": (
                    "highest validation mean return among budgets with zero safety "
                    "violations in every final seed; test was inaccessible until selection"
                ),
                "trials": summaries,
                "final_seed_results": final_seed_results,
            }
        ],
        "budget_candidates": summaries,
        "all_budget_seed_artifacts": seed_results,
        "code_sha256": {
            path: sha256_file(PROJECT_ROOT / path)
            for path in (
                "backend/app/rl/environment.py",
                "backend/app/rl/training.py",
                "backend/app/rl/tuning.py",
                "backend/app/rl/operational_flex_refinement.py",
            )
        },
        "production_boundary": {
            "simulation_mode": True,
            "live_data_verified": False,
            "dispatch_allowed": False,
            "production_authority": False,
        },
        "limitations": [
            "Training budget selection uses validation only; selected-budget test metrics are final evidence.",
            "All 50k and 100k checkpoints are preserved, including non-selected and failed candidates.",
            "Offline scenario results are not field KPIs or production authority.",
        ],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Continue PPO v5 training on frozen budgets")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--artifact-dir", type=Path, default=DEFAULT_ARTIFACT_DIR)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    report = run(args.output, args.artifact_dir)
    print(
        json.dumps(
            {
                "status": "written",
                "output": portable_path(args.output),
                "selected_budget": report["total_steps_per_fit"],
            }
        )
    )


if __name__ == "__main__":
    main()
