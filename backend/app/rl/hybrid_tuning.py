from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any

from app.rl.dataset import PROJECT_ROOT, PortDataset
from app.rl.training import TrainingService
from app.rl.tuning import evaluate_model, portable_path, train_candidate


DATASET_ID = "port_la_2020_2024_hybrid_rl_hourly"
SEARCH_STEPS = 20_000
FINAL_STEPS = 50_000
SELECTION_SEED = 23
FINAL_SEEDS = (17, 37, 59)
WORKERS = 3
DEFAULT_OUTPUT = PROJECT_ROOT / "reports/rl_tuning_hybrid_v6_50k.json"
DEFAULT_ARTIFACT_DIR = PROJECT_ROOT / "reports/rl_tuning_hybrid_v6_50k_artifacts"

SEARCH_SPACE: dict[str, list[dict[str, Any]]] = {
    "ppo": [
        {
            "learning_rate": 3e-4,
            "batch_size": 64,
            "gamma": 0.99,
            "entropy_coef": 0.0,
        },
        {
            "learning_rate": 1e-4,
            "batch_size": 128,
            "gamma": 0.995,
            "entropy_coef": 0.005,
        },
    ],
    "sac": [
        {"learning_rate": 3e-4, "batch_size": 256, "gamma": 0.99, "tau": 0.005},
        {"learning_rate": 1e-4, "batch_size": 256, "gamma": 0.995, "tau": 0.01},
    ],
    "td3": [
        {"learning_rate": 3e-4, "batch_size": 256, "gamma": 0.99, "tau": 0.005},
        {"learning_rate": 1e-4, "batch_size": 256, "gamma": 0.995, "tau": 0.01},
    ],
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _single_thread_runtime() -> None:
    try:
        import torch

        torch.set_num_threads(1)
        torch.set_num_interop_threads(1)
    except (ImportError, RuntimeError):
        pass


def _fit(payload: tuple[str, int, dict[str, Any], int, int, str, str]) -> dict[str, Any]:
    algorithm, candidate_index, candidate, steps, seed, phase, artifact_dir_value = payload
    _single_thread_runtime()
    model, _, evidence = train_candidate(
        algorithm,
        candidate,
        DATASET_ID,
        steps,
        seed,
        24,
    )
    artifact_dir = Path(artifact_dir_value)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    base = artifact_dir / (
        f"{phase}-{algorithm}-candidate-{candidate_index}-steps-{steps}-seed-{seed}"
    )
    model.save(str(base))
    artifact = base.with_suffix(".zip")
    return {
        "phase": phase,
        "algorithm": algorithm,
        "candidate_index": candidate_index,
        "hyperparameters": candidate,
        "steps": steps,
        "seed": seed,
        "training": evidence,
        "artifact_path": portable_path(artifact),
        "artifact_sha256": sha256_file(artifact),
    }


def _test(payload: tuple[str, dict[str, Any], int, int, str]) -> dict[str, Any]:
    algorithm, candidate, steps, seed, artifact_path = payload
    _single_thread_runtime()
    service = TrainingService()
    config = service.validate_config(
        {
            "algorithm": algorithm,
            "dataset_id": DATASET_ID,
            "total_steps": steps,
            "seed": seed,
            "episode_hours": 24,
            **candidate,
        }
    )
    model = service._load_model(algorithm, artifact_path)
    return evaluate_model(service, model, config, "test")


def _rank(record: dict[str, Any]) -> tuple[bool, float, float]:
    validation = record["training"]["validation"]["mean"]
    safety = float(validation["safety_violations"])
    reward = float(validation["reward"])
    return safety == 0.0, -safety, reward


def run(output: Path, artifact_dir: Path) -> dict[str, Any]:
    dataset = PortDataset.load(DATASET_ID)
    search_jobs = [
        (
            algorithm,
            candidate_index,
            candidate,
            SEARCH_STEPS,
            SELECTION_SEED,
            "search",
            str(artifact_dir),
        )
        for algorithm, candidates in SEARCH_SPACE.items()
        for candidate_index, candidate in enumerate(candidates)
    ]
    print(
        json.dumps(
            {
                "status": "phase_started",
                "phase": "validation_only_algorithm_search",
                "fits": len(search_jobs),
                "steps_per_fit": SEARCH_STEPS,
                "workers": WORKERS,
            }
        ),
        flush=True,
    )
    with ProcessPoolExecutor(max_workers=WORKERS) as executor:
        search_results = list(executor.map(_fit, search_jobs))
    selected = max(search_results, key=_rank)
    final_jobs = [
        (
            selected["algorithm"],
            selected["candidate_index"],
            selected["hyperparameters"],
            FINAL_STEPS,
            seed,
            "final",
            str(artifact_dir),
        )
        for seed in FINAL_SEEDS
    ]
    print(
        json.dumps(
            {
                "status": "phase_started",
                "phase": "selected_candidate_final_seeds",
                "algorithm": selected["algorithm"],
                "candidate_index": selected["candidate_index"],
                "seeds": list(FINAL_SEEDS),
                "steps_per_fit": FINAL_STEPS,
            }
        ),
        flush=True,
    )
    with ProcessPoolExecutor(max_workers=WORKERS) as executor:
        final_results = list(executor.map(_fit, final_jobs))
    print(
        json.dumps(
            {
                "status": "phase_started",
                "phase": "frozen_test_evaluation",
                "algorithm": selected["algorithm"],
            }
        ),
        flush=True,
    )
    with ProcessPoolExecutor(max_workers=WORKERS) as executor:
        tests = list(
            executor.map(
                _test,
                [
                    (
                        item["algorithm"],
                        item["hyperparameters"],
                        item["steps"],
                        item["seed"],
                        str(PROJECT_ROOT / item["artifact_path"]),
                    )
                    for item in final_results
                ],
            )
        )
    for item, test in zip(final_results, tests, strict=True):
        item["test"] = test
    report = {
        "schema_version": "hybrid-rl-tuning.v1",
        "generated_at": utc_now(),
        "evidence_label": "OFFLINE_HYBRID_RL_NOT_FIELD_KPI",
        "dataset_id": dataset.dataset_id,
        "dataset_package_sha256": dataset.package_sha256,
        "environment_id": dataset.environment_id,
        "selection_protocol": {
            "fit_split": "train",
            "algorithm_and_hyperparameter_selection_split": "validation",
            "final_report_split": "test",
            "test_accessed_after_selection": True,
            "search_steps_per_fit": SEARCH_STEPS,
            "final_steps_per_fit": FINAL_STEPS,
            "selection_seed": SELECTION_SEED,
            "final_seeds": list(FINAL_SEEDS),
        },
        "search_results": search_results,
        "selected": {
            "algorithm": selected["algorithm"],
            "candidate_index": selected["candidate_index"],
            "hyperparameters": selected["hyperparameters"],
            "selection_reason": (
                "zero validation safety first, then minimum safety violations, "
                "then maximum validation return; test inaccessible until frozen"
            ),
        },
        "final_seed_results": final_results,
        "runtime": TrainingService().capabilities()["runtime"],
        "code_sha256": {
            path: sha256_file(PROJECT_ROOT / path)
            for path in (
                "backend/app/rl/environment.py",
                "backend/app/rl/hybrid_control.py",
                "backend/app/rl/training.py",
                "backend/app/rl/tuning.py",
                "backend/app/rl/hybrid_tuning.py",
                "scripts/build_hybrid_rl_dataset.py",
            )
        },
        "production_boundary": {
            "simulation_mode": True,
            "live_data_verified": False,
            "dispatch_allowed": False,
            "production_authority": False,
        },
        "limitations": [
            "New v6 operational fields are deterministic engineering scenarios, not port telemetry.",
            "Validation selects the algorithm and hyperparameters; test is final evidence only.",
            "All search and final artifacts are retained, including losing candidates and seeds.",
        ],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Train the v6 hybrid residual-RL policy")
    result.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    result.add_argument("--artifact-dir", type=Path, default=DEFAULT_ARTIFACT_DIR)
    return result


def main() -> None:
    args = parser().parse_args()
    report = run(args.output, args.artifact_dir)
    print(
        json.dumps(
            {
                "status": "written",
                "output": portable_path(args.output),
                "selected_algorithm": report["selected"]["algorithm"],
            }
        )
    )


if __name__ == "__main__":
    main()
