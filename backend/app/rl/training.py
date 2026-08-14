from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import logging
from pathlib import Path
import platform
import re
import sys
import threading
import time
from typing import Any
import uuid

import numpy as np

from app.rl.catalog import ALGORITHM_CATALOG, algorithm_items
from app.rl.dataset import (
    DEFAULT_DATASET_ID,
    PortDataset,
    list_datasets,
)
from app.rl.environment import (
    FixedDispatchPolicy,
    MPCPolicy,
    PortEnergyDispatchEnv,
    encode_continuous_controls,
    observation_keys_for_environment,
)
from app.rl.robust import CausalForecastPortEnv, cvar, paired_bootstrap_interval


RUNS_DIR = Path(__file__).resolve().parents[1] / "data" / "runs"
RUNS_DIR.mkdir(parents=True, exist_ok=True)
PROJECT_ROOT = Path(__file__).resolve().parents[3]
RUN_ID_PATTERN = re.compile(r"^rl-\d{8}-\d{6}-[0-9a-f]{6}$")
logger = logging.getLogger(__name__)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def public_artifact_path(value: object) -> str | None:
    """Expose portable repository paths while retaining absolute paths internally."""
    if not value:
        return None
    path = Path(str(value))
    if not path.is_absolute():
        return path.as_posix()
    try:
        return path.resolve().relative_to(PROJECT_ROOT.resolve()).as_posix()
    except ValueError:
        return f"external-artifact/{path.name}"


def public_log_line(value: object) -> str:
    return str(value).replace(str(PROJECT_ROOT), ".")


class TrainingService:
    """Run one real SB3 training job in a background thread and persist its evidence."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._job: dict[str, Any] | None = None
        self._thread: threading.Thread | None = None
        self._pause = threading.Event()
        self._stop = threading.Event()
        self._digest_cache: dict[str, tuple[int, int, str]] = {}
        self._load_latest_state()

    def capabilities(self) -> dict[str, Any]:
        try:
            runtime = {"available": True, **self._runtime_versions(), "device": "cpu"}
        except Exception:
            logger.exception("RL runtime capability detection failed")
            runtime = {"available": False, "error": "rl_runtime_unavailable", "device": None}
        return {
            "algorithms": algorithm_items(),
            "datasets": list_datasets(),
            "runtime": runtime,
            "training_render_mode": None,
            "evaluation_render_mode": "trajectory",
        }

    def validate_config(self, raw: dict[str, Any]) -> dict[str, Any]:
        algorithm = str(raw.get("algorithm") or "sac").lower()
        aliases = {"td3_bc": "td3", "real_port_rule": "mpc", "iql": "dqn"}
        algorithm = aliases.get(algorithm, algorithm)
        if algorithm not in ALGORITHM_CATALOG:
            raise ValueError(
                f"Unknown algorithm: {algorithm}; choose from {', '.join(ALGORITHM_CATALOG)}"
            )
        dataset_value = raw.get("data_file") or raw.get("dataset_id") or DEFAULT_DATASET_ID
        dataset = PortDataset.load(dataset_value)
        defaults = ALGORITHM_CATALOG[algorithm]["defaults"]
        total_steps = int(raw.get("total_steps") or defaults["total_steps"])
        if algorithm != "mpc" and not 32 <= total_steps <= 5_000_000:
            raise ValueError("total_steps must be between 32 and 5,000,000")
        if int(raw.get("step_min") or 60) != 60:
            raise ValueError(f"{dataset.environment_id} uses a fixed 60-minute environment step")
        if str(raw.get("guardrail_mode") or "strict") != "strict":
            raise ValueError("Only strict environment constraints are implemented")
        weights = raw.get("reward_weights") or {}
        config = {
            **raw,
            "algorithm": algorithm,
            "algorithm_family": ALGORITHM_CATALOG[algorithm]["family"],
            "dataset_id": dataset.dataset_id,
            "data_file": dataset.dataset_id,
            "dataset_sha256": dataset.package_sha256,
            "dataset_csv_sha256": dataset.sha256,
            "dataset_metadata_sha256": dataset.metadata_sha256,
            "total_steps": 0 if algorithm == "mpc" else total_steps,
            "batch_size": int(raw.get("batch_size") or defaults["batch_size"] or 1),
            "learning_rate": float(raw.get("learning_rate") or defaults["learning_rate"] or 0.0),
            "gamma": float(raw.get("gamma") or defaults["gamma"]),
            "tau": float(raw.get("tau") or 0.005),
            "seed": int(raw.get("seed") or 20260720),
            "episode_hours": int(
                raw.get("episode_hours")
                or min(24, max(4, int(raw.get("horizon_min") or 1440) // 60))
            ),
            "step_min": 60,
            "guardrail_mode": "strict",
            "eval_interval": max(
                1, int(raw.get("eval_interval") or min(max(total_steps // 10, 1), 10_000))
            ),
            "checkpoint_interval": max(
                1, int(raw.get("checkpoint_interval") or min(max(total_steps // 4, 1), 25_000))
            ),
            "reward_weights": weights,
            "train_split": "train",
            "validation_split": "validation",
            "test_split": "test",
            "render_during_training": False,
            "forecast_protocol": "causal_persistence_v1",
            "runtime_versions": self._runtime_versions(),
            "environment_id": dataset.environment_id,
            "observation_count": len(observation_keys_for_environment(dataset.environment_id)),
            "action_contract": {
                "continuous": 4,
                "dqn_discrete_combinations": 81,
            },
        }
        return config

    def start(self, raw_config: dict[str, Any]) -> dict[str, Any]:
        config = self.validate_config(raw_config)
        with self._lock:
            if self._job and self._job.get("status") in {"running", "paused", "stopping"}:
                raise RuntimeError(f"Training job {self._job['job_id']} is already active")
            job_id = f"rl-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
            run_dir = RUNS_DIR / job_id
            run_dir.mkdir(parents=True, exist_ok=False)
            config_path = run_dir / "config.json"
            config_path.write_text(
                json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            self._pause.clear()
            self._stop.clear()
            self._job = {
                "job_id": job_id,
                "status": "running",
                "started_at": utc_now(),
                "started_monotonic": time.monotonic(),
                "paused_total_sec": 0.0,
                "pause_started_monotonic": None,
                "step": 0,
                "total_steps": int(config["total_steps"]),
                "progress": 0.0,
                "config": config,
                "run_dir": str(run_dir),
                "artifact_path": None,
                "policy_version": f"{config['algorithm']}-{job_id}",
                "recent_metrics": [],
                "logs": [
                    f"Loaded training split from {config['dataset_id']} ({config['dataset_sha256'][:12]})",
                    "render_mode=None: training will not emit visual trajectories",
                ],
                "error": None,
            }
            self._persist_state()
            if config["algorithm"] == "mpc":
                self._complete_mpc_job()
                return self.status()
            self._thread = threading.Thread(target=self._run_training, name=job_id, daemon=True)
            self._thread.start()
            return self.status()

    def status(self) -> dict[str, Any]:
        with self._lock:
            if not self._job:
                return self._idle_status()
            job = dict(self._job)
            elapsed = self._elapsed(job)
            step = int(job.get("step") or 0)
            rate = step / elapsed if elapsed > 0 else 0.0
            remaining = max(0, int(job.get("total_steps") or 0) - step)
            remaining_sec = (
                remaining / rate if rate > 0 and job.get("status") == "running" else None
            )
            metrics = list(job.get("recent_metrics") or [])
            latest = metrics[-1] if metrics else {}
            return {
                "status": job["status"],
                "job_id": job["job_id"],
                "progress": round(float(job.get("progress") or 0.0), 2),
                "step": step,
                "total_steps": int(job.get("total_steps") or 0),
                "reward": latest.get("reward", 0.0),
                "entropy": latest.get("entropy", latest.get("train/entropy_loss", 0.0)),
                "actor_loss": latest.get("actor_loss", latest.get("train/actor_loss", 0.0)),
                "critic_loss": latest.get("critic_loss", latest.get("train/critic_loss", 0.0)),
                "kl_divergence": latest.get("train/approx_kl", 0.0),
                "success_rate": latest.get("success_rate", 0.0),
                "samples_per_sec": round(rate, 2),
                "step_rate_per_min": round(rate * 60, 2),
                "recent_metrics": metrics[-120:],
                "policy_version": job["policy_version"],
                "artifact_path": public_artifact_path(job.get("artifact_path")),
                "started_at": job.get("started_at"),
                "completed_at": job.get("completed_at"),
                "duration_sec": round(elapsed, 2),
                "elapsed_sec": round(elapsed, 2),
                "estimated_duration_sec": round(elapsed + remaining_sec, 2)
                if remaining_sec is not None
                else None,
                "remaining_sec": round(remaining_sec, 2) if remaining_sec is not None else None,
                "eta_at": self._eta(remaining_sec),
                "can_pause": job["status"] == "running",
                "can_resume": job["status"] == "paused",
                "can_stop": job["status"] in {"running", "paused"},
                "config": job["config"],
                "logs": [public_log_line(line) for line in list(job.get("logs") or [])[-20:]],
                "error": job.get("error"),
                "summary": self._summary(job, step),
                "rendering": False,
                "evidence": "measured callback state; no timer-derived progress",
            }

    def control(self, action: str) -> dict[str, Any]:
        with self._lock:
            if not self._job:
                return {
                    **self._idle_status(),
                    "control_action": action,
                    "control_result": "no_active_job",
                }
            status = self._job["status"]
            changed = False
            if action == "pause" and status == "running":
                self._pause.set()
                self._job["status"] = "paused"
                self._job["pause_started_monotonic"] = time.monotonic()
                self._job["logs"].append(
                    "Pause requested; learner callback is holding before the next environment step"
                )
                changed = True
            elif action == "resume" and status == "paused":
                pause_started = self._job.get("pause_started_monotonic")
                if pause_started:
                    self._job["paused_total_sec"] += max(
                        0.0, time.monotonic() - float(pause_started)
                    )
                self._job["pause_started_monotonic"] = None
                self._job["status"] = "running"
                self._pause.clear()
                self._job["logs"].append("Learner resumed")
                changed = True
            elif action == "stop" and status in {"running", "paused"}:
                self._stop.set()
                self._pause.clear()
                self._job["status"] = "stopping"
                self._job["logs"].append("Stop requested; current checkpoint will be saved")
                changed = True
            self._persist_state()
        return {
            **self.status(),
            "control_action": action,
            "control_result": "applied" if changed else "ignored",
        }

    def strategies(self) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for manifest_path in sorted(RUNS_DIR.glob("*/manifest.json"), reverse=True):
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except Exception:
                continue
            items.append(
                {
                    "strategy_id": manifest["job_id"],
                    "policy_version": manifest["policy_version"],
                    "algorithm": manifest["config"]["algorithm"],
                    "artifact_path": public_artifact_path(manifest.get("artifact_path")),
                    "artifact_sha256": manifest.get("artifact_sha256"),
                    "objective": manifest["config"].get("objective_label")
                    or manifest["config"].get("objective_id"),
                    "dataset_id": manifest["config"]["dataset_id"],
                    "dataset_sha256": manifest["config"]["dataset_sha256"],
                    "ready": manifest["status"] in {"completed", "stopped"},
                    "completed_at": manifest.get("completed_at"),
                }
            )
        return items

    def registry(self) -> dict[str, Any]:
        policies: list[dict[str, Any]] = []
        for manifest_path in sorted(RUNS_DIR.glob("*/manifest.json"), reverse=True):
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                config = manifest["config"]
            except Exception:
                continue
            run_dir = manifest_path.parent
            artifact_value = manifest.get("artifact_path")
            artifact = Path(artifact_value) if artifact_value else None
            artifact_exists = bool(artifact and artifact.exists())
            artifact_sha256 = (
                self._cached_sha256(artifact) if artifact_exists and artifact else None
            )
            recorded_artifact_sha256 = manifest.get("artifact_sha256")
            artifact_integrity = (
                "verified"
                if artifact_sha256 and recorded_artifact_sha256 == artifact_sha256
                else "unrecorded_legacy"
                if artifact_sha256 and not recorded_artifact_sha256
                else "failed"
            )
            dataset_status = "unavailable"
            drift: dict[str, Any] = {"status": "unavailable"}
            current_dataset_sha256 = None
            try:
                dataset = PortDataset.load(config["data_file"])
                current_dataset_sha256 = dataset.package_sha256
                dataset_status = (
                    "verified"
                    if current_dataset_sha256 == config.get("dataset_sha256")
                    else "changed"
                )
                drift = dataset.drift_report()
            except Exception:
                logger.exception("Model-registry dataset drift calculation failed")
                drift = {"status": "unavailable", "error": "dataset_drift_unavailable"}
            evaluation_path = run_dir / "evaluation.json"
            verification_path = run_dir / "verification.json"
            evaluation = (
                json.loads(evaluation_path.read_text(encoding="utf-8"))
                if evaluation_path.exists()
                else {}
            )
            verification = (
                json.loads(verification_path.read_text(encoding="utf-8"))
                if verification_path.exists()
                else {}
            )
            safety_violations = (evaluation.get("metrics") or {}).get("safety_violations")
            if artifact_integrity == "failed" or dataset_status != "verified":
                stage = "blocked"
            elif manifest.get("status") not in {"completed", "stopped"}:
                stage = "training" if manifest.get("status") in {"running", "paused"} else "blocked"
            elif not evaluation:
                stage = "candidate"
            elif safety_violations != 0 or drift.get("status") == "high_shift":
                stage = "blocked"
            elif verification.get("status") == "blocked":
                stage = "blocked"
            elif verification.get("status") == "verified":
                stage = "verified_offline"
            else:
                stage = "validated_offline"
            policies.append(
                {
                    "policy_id": manifest.get("job_id"),
                    "policy_version": manifest.get("policy_version"),
                    "algorithm": config.get("algorithm"),
                    "stage": stage,
                    "run_status": manifest.get("status"),
                    "trained_at": manifest.get("completed_at"),
                    "dataset_id": config.get("dataset_id"),
                    "trained_dataset_sha256": config.get("dataset_sha256"),
                    "current_dataset_sha256": current_dataset_sha256,
                    "dataset_status": dataset_status,
                    "artifact_path": public_artifact_path(artifact_value),
                    "artifact_sha256": artifact_sha256,
                    "recorded_artifact_sha256": recorded_artifact_sha256,
                    "artifact_integrity": artifact_integrity,
                    "evaluation_status": evaluation.get("status", "not_tested"),
                    "evaluation_metrics": evaluation.get("metrics", {}),
                    "verification_status": verification.get("status", "not_verified"),
                    "drift": drift,
                    "production_eligible": False,
                    "production_blocker": "Human-approved port adapters and production validation are required.",
                }
            )
        return {
            "updated_at": utc_now(),
            "count": len(policies),
            "production_dispatch_enabled": False,
            "stage_definitions": {
                "candidate": "Artifact exists but held-out evaluation has not completed.",
                "validated_offline": "Held-out evaluation passed offline gates.",
                "verified_offline": "Offline verification evidence is persisted.",
                "blocked": "Integrity, data, safety, or lifecycle gate failed.",
            },
            "policies": policies,
        }

    def evaluate(self, strategy_id: str = "auto:latest") -> dict[str, Any]:
        manifest = self._resolve_manifest(strategy_id)
        config = manifest["config"]
        algorithm = config["algorithm"]
        action_mode = "discrete" if algorithm == "dqn" else "continuous"
        model = (
            None if algorithm == "mpc" else self._load_model(algorithm, manifest["artifact_path"])
        )
        dataset = PortDataset.load(config["data_file"])
        environment_class = (
            CausalForecastPortEnv
            if config.get("forecast_protocol") == "causal_persistence_v1"
            else PortEnergyDispatchEnv
        )
        learned_totals: list[dict[str, Any]] = []
        baseline_totals: list[dict[str, Any]] = []
        fixed_totals: list[dict[str, Any]] = []
        learned_trajectory: list[dict[str, Any]] = []
        baseline_trajectory: list[dict[str, Any]] = []
        test_frame = dataset.split("test")
        test_start_indices = dataset.evaluation_start_indices("test", config["episode_hours"])
        for row_index in test_start_indices:
            evaluation_hours = (
                min(config["episode_hours"], len(test_frame) - row_index)
                if dataset.temporal_mode == "sequential_rows"
                else config["episode_hours"]
            )
            learned = environment_class(
                dataset=config["data_file"],
                split="test",
                action_mode=action_mode,
                reward_weights=config.get("reward_weights"),
                episode_hours=evaluation_hours,
                render_mode="trajectory",
            )
            baseline = environment_class(
                dataset=config["data_file"],
                split="test",
                action_mode="continuous",
                reward_weights=config.get("reward_weights"),
                episode_hours=evaluation_hours,
                render_mode="trajectory",
            )
            fixed = environment_class(
                dataset=config["data_file"],
                split="test",
                action_mode="continuous",
                reward_weights=config.get("reward_weights"),
                episode_hours=evaluation_hours,
                render_mode=None,
            )
            learned_summary = self.rollout(
                learned, model, algorithm, row_index, int(config["seed"])
            )
            baseline_summary = self.rollout(baseline, None, "mpc", row_index, int(config["seed"]))
            fixed_summary = self.rollout(fixed, None, "fixed", row_index, int(config["seed"]))
            learned_totals.append(learned_summary)
            baseline_totals.append(baseline_summary)
            fixed_totals.append(fixed_summary)
            if row_index == 0:
                learned_trajectory = learned.render() or []
                baseline_trajectory = baseline.render() or []
        policy = self._mean_totals(learned_totals)
        control = self._mean_totals(baseline_totals)
        fixed = self._mean_totals(fixed_totals)
        policy_shore_rate = (
            policy["shore_power_kwh"] / max(1.0, policy["shore_power_opportunity_kwh"]) * 100.0
        )
        control_shore_rate = (
            control["shore_power_kwh"] / max(1.0, control["shore_power_opportunity_kwh"]) * 100.0
        )
        metrics = {
            "mean_reward": policy["reward"],
            "control_mean_reward": control["reward"],
            "carbon_reduction_pct": self._saving(control["carbon_kg"], policy["carbon_kg"]),
            "shore_power_gain_pct": round(policy_shore_rate - control_shore_rate, 3),
            "cost_saving_pct": self._saving(control["cost"], policy["cost"]),
            "delay_reduction_pct": self._saving(control["delay_minutes"], policy["delay_minutes"]),
            "peak_reduction_kw": round(control["peak_kw"] - policy["peak_kw"], 3),
            "safety_violations": int(policy["safety_violations"]),
            "control_safety_violations": int(control["safety_violations"]),
            "fixed_baseline_carbon_reduction_pct": self._saving(
                fixed["carbon_kg"], policy["carbon_kg"]
            ),
            "fixed_baseline_cost_saving_pct": self._saving(fixed["cost"], policy["cost"]),
            "fixed_baseline_peak_change_pct": round(
                (policy["peak_kw"] - fixed["peak_kw"]) / max(abs(fixed["peak_kw"]), 1e-9) * 100.0,
                3,
            ),
            "fixed_baseline_throughput_change_pct": round(
                (policy["processed_teu"] - fixed["processed_teu"])
                / max(abs(fixed["processed_teu"]), 1e-9)
                * 100.0,
                3,
            ),
            "fixed_baseline_safety_violations": int(fixed["safety_violations"]),
            "constraint_success_rate_pct": (
                100.0 if int(policy["safety_violations"]) == 0 else 0.0
            ),
            "test_episodes": len(learned_totals),
            "test_steps": int(sum(item["steps"] for item in learned_totals)),
        }
        uncertainty = {
            "fixed_baseline_carbon_reduction_ci95": paired_bootstrap_interval(
                [float(item["carbon_kg"]) for item in learned_totals],
                [float(item["carbon_kg"]) for item in fixed_totals],
            ),
            "fixed_baseline_cost_reduction_ci95": paired_bootstrap_interval(
                [float(item["cost"]) for item in learned_totals],
                [float(item["cost"]) for item in fixed_totals],
                seed=20260809,
            ),
            "policy_carbon_cvar95_kg": cvar(
                [float(item["carbon_kg"]) for item in learned_totals]
            ),
            "fixed_baseline_carbon_cvar95_kg": cvar(
                [float(item["carbon_kg"]) for item in fixed_totals]
            ),
            "policy_cost_cvar95": cvar([float(item["cost"]) for item in learned_totals]),
            "fixed_baseline_cost_cvar95": cvar(
                [float(item["cost"]) for item in fixed_totals]
            ),
        }
        result = {
            "status": "tested",
            "strategy_id": manifest["job_id"],
            "policy": {
                "policy_version": manifest["policy_version"],
                "algorithm": algorithm,
                "artifact_path": public_artifact_path(manifest.get("artifact_path")),
                "artifact_sha256": self._sha256_file(Path(manifest["artifact_path"])),
                "dataset_id": config["dataset_id"],
                "data_file": config["data_file"],
                "dataset_sha256": config["dataset_sha256"],
                "forecast_protocol": config.get("forecast_protocol", "legacy_future-row_oracle"),
            },
            "metrics": metrics,
            "uncertainty": uncertainty,
            "per_episode_metrics": [
                {
                    "period": item["period"],
                    "steps": item["steps"],
                    "carbon_kg": item["carbon_kg"],
                    "cost": item["cost"],
                    "peak_kw": item["peak_kw"],
                    "processed_teu": item["processed_teu"],
                    "delay_minutes": item["delay_minutes"],
                    "safety_violations": item["safety_violations"],
                }
                for item in learned_totals
            ],
            "policy_totals": policy,
            "control_baseline_totals": control,
            "fixed_dispatch_baseline": {
                "definition": {
                    "shore_power_ratio": 1.0,
                    "crane_ratio": 1.0,
                    "yard_ratio": 1.0,
                    "evidence_scope": (
                        "strong full-shore-power fixed-resource comparator; "
                        "not observed terminal practice"
                    ),
                },
                "totals": fixed,
            },
            "trajectory": learned_trajectory,
            "baseline_trajectory": baseline_trajectory,
            "render_mode": "trajectory",
            "split": "test",
            "dataset_quality": dataset.quality_report(),
            "dataset_drift": dataset.drift_report(),
            "evaluated_at": utc_now(),
            "summary": (
                f"Held-out test complete: carbon {metrics['carbon_reduction_pct']:+.2f}%, "
                f"cost {metrics['cost_saving_pct']:+.2f}% vs MPC; safety violations={metrics['safety_violations']}"
            ),
        }
        evaluation_path = Path(manifest["run_dir"]) / "evaluation.json"
        evaluation_path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return result

    def record_verification(self, strategy_id: str, result: dict[str, Any]) -> Path:
        manifest = self._resolve_manifest(strategy_id)
        path = Path(manifest["run_dir"]) / "verification.json"
        path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def history(self) -> dict[str, Any]:
        items = self.strategies()
        if not items:
            return {
                "available": False,
                "series": [],
                "metrics": {},
                "checkpoints": [],
                "title": "No completed training runs",
            }
        manifest = self._resolve_manifest(items[0]["strategy_id"])
        metric_path = Path(manifest["run_dir"]) / "metrics.jsonl"
        series: list[dict[str, Any]] = []
        if metric_path.exists():
            for line in metric_path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    series.append(json.loads(line))
        evaluation_path = Path(manifest["run_dir"]) / "evaluation.json"
        evaluation = (
            json.loads(evaluation_path.read_text(encoding="utf-8"))
            if evaluation_path.exists()
            else {}
        )
        evaluation_metrics = dict(evaluation.get("metrics") or {})
        rewards = [float(point.get("reward", 0.0)) for point in series]
        if rewards:
            evaluation_metrics.setdefault("best_callback_reward", round(max(rewards), 6))
            evaluation_metrics.setdefault(
                "mean_last_20_callback_reward", round(float(np.mean(rewards[-20:])), 6)
            )
        if "safety_violations" in evaluation_metrics:
            evaluation_metrics.setdefault(
                "constraint_success_rate_pct",
                100.0 if int(evaluation_metrics["safety_violations"]) == 0 else 0.0,
            )
        validation_by_step = {
            int(point["step"]): point for point in series if "validation_return" in point
        }
        checkpoints = []
        for checkpoint_path in sorted(
            (Path(manifest["run_dir"]) / "checkpoints").glob("step-*.zip")
        ):
            checkpoint_step = int(checkpoint_path.stem.split("-")[-1])
            validation = validation_by_step.get(checkpoint_step, {})
            checkpoints.append(
                {
                    "step": checkpoint_step,
                    "path": public_artifact_path(checkpoint_path),
                    "validation_return": validation.get("validation_return"),
                    "validation_safety_violations": validation.get("validation_safety_violations"),
                }
            )
        return {
            "available": True,
            "run_id": manifest["job_id"],
            "title": f"{manifest['config']['algorithm'].upper()} real training run",
            "title_en": "Persisted callback metrics from the actual learner",
            "source": manifest["config"]["data_file"],
            "evidence_level": "dataset hash + measured callback metrics + saved model",
            "environment": manifest["config"].get("environment_id", "PortEnergyDispatchEnv-v1"),
            "algorithm": manifest["config"]["algorithm"].upper(),
            "seed": manifest["config"]["seed"],
            "total_steps": manifest["step"],
            "episodes": sum(1 for item in series if item.get("episode_complete")),
            "duration_sec": manifest.get("duration_sec", 0),
            "started_at": manifest["started_at"],
            "completed_at": manifest.get("completed_at"),
            "checkpoint": public_artifact_path(manifest.get("artifact_path")),
            "metrics": evaluation_metrics,
            "checkpoints": checkpoints,
            "series": series,
        }

    def _run_training(self) -> None:
        assert self._job is not None
        job_id = self._job["job_id"]
        try:
            from stable_baselines3.common.callbacks import BaseCallback

            service = self

            class EvidenceCallback(BaseCallback):
                def _on_step(callback_self) -> bool:
                    while service._pause.is_set() and not service._stop.is_set():
                        time.sleep(0.15)
                    if service._stop.is_set():
                        return False
                    service._record_callback(callback_self)
                    service._checkpoint_if_due(callback_self)
                    return True

            with self._lock:
                config = dict(self._job["config"])
            env = CausalForecastPortEnv(
                dataset=config["data_file"],
                split="train",
                action_mode="discrete" if config["algorithm"] == "dqn" else "continuous",
                reward_weights=config.get("reward_weights"),
                episode_hours=config["episode_hours"],
                render_mode=None,
            )
            model = self.build_model(config, env)
            model.learn(
                total_timesteps=config["total_steps"],
                callback=EvidenceCallback(),
                progress_bar=False,
            )
            with self._lock:
                if not self._job or self._job["job_id"] != job_id:
                    return
                run_dir = Path(self._job["run_dir"])
                artifact_base = run_dir / "model"
                model.save(str(artifact_base))
                self._job["artifact_path"] = str(artifact_base.with_suffix(".zip"))
                self._job["step"] = int(model.num_timesteps)
                self._job["progress"] = min(
                    100.0, self._job["step"] / max(1, config["total_steps"]) * 100
                )
                self._job["status"] = "stopped" if self._stop.is_set() else "completed"
                self._job["completed_at"] = utc_now()
                self._job["duration_sec"] = self._elapsed(self._job)
                self._job["logs"].append(f"Saved real model artifact: {self._job['artifact_path']}")
                self._write_manifest()
                self._persist_state()
        except Exception:
            logger.exception("RL training job failed: %s", job_id)
            with self._lock:
                if self._job and self._job["job_id"] == job_id:
                    self._job["status"] = "failed"
                    self._job["error"] = "training_failed"
                    self._job["completed_at"] = utc_now()
                    self._job["logs"].append(self._job["error"])
                    self._write_manifest()
                    self._persist_state()

    def build_model(self, config: dict[str, Any], env: PortEnergyDispatchEnv):
        from stable_baselines3 import DQN, PPO, SAC, TD3
        from stable_baselines3.common.noise import NormalActionNoise

        common = {
            "policy": "MlpPolicy",
            "env": env,
            "learning_rate": config["learning_rate"],
            "gamma": config["gamma"],
            "seed": config["seed"],
            "verbose": 0,
            "device": "cpu",
        }
        steps = int(config["total_steps"])
        algorithm = config["algorithm"]
        if algorithm == "ppo":
            n_steps = min(256, max(8, steps))
            batch_size = self._valid_ppo_batch(min(config["batch_size"], n_steps), n_steps)
            return PPO(
                **common,
                n_steps=n_steps,
                batch_size=batch_size,
                ent_coef=float(config.get("entropy_coef") or 0.0),
            )
        if algorithm == "sac":
            return SAC(
                **common,
                batch_size=min(config["batch_size"], max(2, steps)),
                tau=config["tau"],
                learning_starts=min(1_000, max(10, steps // 10)),
                buffer_size=max(1_000, min(500_000, steps * 2)),
            )
        if algorithm == "td3":
            action_dim = int(np.prod(env.action_space.shape))
            noise = NormalActionNoise(
                mean=np.zeros(action_dim),
                sigma=0.1 * np.ones(action_dim),
            )
            return TD3(
                **common,
                batch_size=min(config["batch_size"], max(2, steps)),
                tau=config["tau"],
                action_noise=noise,
                learning_starts=min(1_000, max(10, steps // 10)),
                buffer_size=max(1_000, min(500_000, steps * 2)),
            )
        if algorithm == "dqn":
            return DQN(
                **common,
                batch_size=min(config["batch_size"], max(2, steps)),
                learning_starts=min(1_000, max(10, steps // 10)),
                buffer_size=max(1_000, min(500_000, steps * 2)),
                exploration_fraction=float(config.get("exploration_fraction") or 0.25),
            )
        raise ValueError(f"Unsupported trainable algorithm: {algorithm}")

    def _record_callback(self, callback: Any) -> None:
        with self._lock:
            if not self._job:
                return
            step = int(callback.num_timesteps)
            total = max(1, int(self._job["total_steps"]))
            interval = max(1, total // 200)
            eval_interval = max(1, int(self._job["config"].get("eval_interval") or total))
            evaluation_due = step == total or step % eval_interval == 0
            if not evaluation_due and step - int(self._job.get("last_metric_step") or 0) < interval:
                self._job["step"] = step
                self._job["progress"] = min(100.0, step / total * 100)
                return
            rewards = np.asarray(callback.locals.get("rewards", [0.0]), dtype=float)
            logger_values = dict(getattr(callback.model.logger, "name_to_value", {}) or {})
            infos = callback.locals.get("infos") or []
            episode = next(
                (
                    info.get("episode")
                    for info in infos
                    if isinstance(info, dict) and info.get("episode")
                ),
                None,
            )
            metric = {
                "step": step,
                "elapsed_sec": round(self._elapsed(self._job), 3),
                "reward": round(float(rewards.mean()), 6),
                "episode_complete": bool(episode),
                "success_rate": round(
                    100.0 * float((episode or {}).get("safety_violations", 0) == 0), 2
                )
                if episode
                else 0.0,
            }
            for key, value in logger_values.items():
                if isinstance(value, (int, float, np.number)):
                    metric[str(key)] = round(float(value), 8)
            if evaluation_due:
                validation = self._validation_rollout(callback.model, self._job["config"], step)
                metric.update(validation)
            metric["actor_loss"] = metric.get(
                "train/actor_loss", metric.get("train/policy_gradient_loss", 0.0)
            )
            metric["critic_loss"] = metric.get(
                "train/critic_loss", metric.get("train/value_loss", 0.0)
            )
            metric["entropy"] = abs(metric.get("train/entropy_loss", 0.0))
            previous = (self._job.get("recent_metrics") or [])[-1:] or [{}]
            previous_ema = float(previous[0].get("reward_ema", metric["reward"]))
            metric["reward_ema"] = round(previous_ema * 0.9 + float(metric["reward"]) * 0.1, 6)
            self._job["step"] = step
            self._job["progress"] = min(100.0, step / total * 100)
            self._job["last_metric_step"] = step
            self._job["recent_metrics"] = [*(self._job.get("recent_metrics") or [])[-119:], metric]
            metric_path = Path(self._job["run_dir"]) / "metrics.jsonl"
            with metric_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(metric, ensure_ascii=False) + "\n")
            self._persist_state()

    def _validation_rollout(self, model: Any, config: dict[str, Any], step: int) -> dict[str, Any]:
        env = CausalForecastPortEnv(
            dataset=config["data_file"],
            split=config["validation_split"],
            action_mode="discrete" if config["algorithm"] == "dqn" else "continuous",
            reward_weights=config.get("reward_weights"),
            episode_hours=config["episode_hours"],
            render_mode=None,
        )
        summary = self.rollout(
            env,
            model,
            config["algorithm"],
            step % len(env.frame),
            int(config["seed"]),
        )
        return {
            "validation_return": round(float(summary["reward"]), 6),
            "validation_safety_violations": int(summary["safety_violations"]),
            "validation_split": config["validation_split"],
            "validation_rendering": False,
        }

    def _checkpoint_if_due(self, callback: Any) -> None:
        with self._lock:
            if not self._job:
                return
            step = int(callback.num_timesteps)
            interval = max(
                1, int(self._job["config"].get("checkpoint_interval") or self._job["total_steps"])
            )
            if (
                step < interval
                or step % interval != 0
                or step == int(self._job.get("last_checkpoint_step") or 0)
            ):
                return
            checkpoint_dir = Path(self._job["run_dir"]) / "checkpoints"
            checkpoint_dir.mkdir(parents=True, exist_ok=True)
            checkpoint_base = checkpoint_dir / f"step-{step}"
            callback.model.save(str(checkpoint_base))
            self._job["last_checkpoint_step"] = step
            self._job["logs"].append(
                f"Saved measured-step checkpoint: {checkpoint_base.with_suffix('.zip')}"
            )
            self._persist_state()

    def _complete_mpc_job(self) -> None:
        assert self._job is not None
        run_dir = Path(self._job["run_dir"])
        artifact_path = run_dir / "mpc_policy.json"
        artifact_path.write_text(
            json.dumps(
                {
                    "algorithm": "mpc",
                    "controller": "four-step constrained MPC beam search with storage and terminal-SOC constraints",
                    "config": self._job["config"],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        self._job["artifact_path"] = str(artifact_path)
        self._job["status"] = "completed"
        self._job["completed_at"] = utc_now()
        self._job["duration_sec"] = 0.0
        self._job["logs"].append(
            "MPC has no fitted parameters; controller artifact recorded for held-out evaluation"
        )
        self._write_manifest()
        self._persist_state()

    def rollout(
        self,
        env: PortEnergyDispatchEnv,
        model: Any,
        algorithm: str,
        row_index: int,
        seed: int,
    ) -> dict[str, Any]:
        observation, _ = env.reset(
            seed=seed + row_index, options={"row_index": row_index, "start_hour": 0}
        )
        terminated = truncated = False
        controller = MPCPolicy()
        fixed_controller = FixedDispatchPolicy()
        while not (terminated or truncated):
            if algorithm == "mpc":
                action = encode_continuous_controls(controller.predict(env))
            elif algorithm == "fixed":
                action = encode_continuous_controls(fixed_controller.predict(env))
            else:
                action, _ = model.predict(observation, deterministic=True)
            observation, _, terminated, truncated, _ = env.step(action)
        return env.summary()

    def _load_model(self, algorithm: str, artifact_path: str):
        from stable_baselines3 import DQN, PPO, SAC, TD3

        classes = {"ppo": PPO, "sac": SAC, "td3": TD3, "dqn": DQN}
        return classes[algorithm].load(artifact_path, device="cpu")

    def _resolve_manifest(self, strategy_id: str) -> dict[str, Any]:
        if strategy_id == "auto:no-admitted-policy":
            raise FileNotFoundError(
                "No substantial policy with persisted verified admission evidence is available"
            )
        if strategy_id == "auto:latest":
            items = self.strategies()
            if not items:
                raise FileNotFoundError("No completed strategy is available; train a policy first")
            strategy_id = items[0]["strategy_id"]
        if not RUN_ID_PATTERN.fullmatch(strategy_id):
            raise FileNotFoundError(f"Invalid strategy ID: {strategy_id}")
        path = RUNS_DIR / strategy_id / "manifest.json"
        if not path.exists():
            raise FileNotFoundError(f"Strategy manifest not found: {strategy_id}")
        manifest = json.loads(path.read_text(encoding="utf-8"))
        if manifest["status"] not in {"completed", "stopped"}:
            raise RuntimeError(f"Strategy is not testable: {manifest['status']}")
        return manifest

    def _write_manifest(self) -> None:
        assert self._job is not None
        manifest = {
            key: value
            for key, value in self._job.items()
            if key not in {"started_monotonic", "pause_started_monotonic", "recent_metrics", "logs"}
        }
        manifest["duration_sec"] = round(self._elapsed(self._job), 3)
        artifact_value = manifest.get("artifact_path")
        artifact_path = Path(artifact_value) if artifact_value else None
        manifest["artifact_sha256"] = (
            self._sha256_file(artifact_path) if artifact_path and artifact_path.exists() else None
        )
        self._job["artifact_sha256"] = manifest["artifact_sha256"]
        path = Path(self._job["run_dir"]) / "manifest.json"
        path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    def _persist_state(self) -> None:
        if not self._job:
            return
        state = {
            key: value
            for key, value in self._job.items()
            if key not in {"started_monotonic", "pause_started_monotonic"}
        }
        state["duration_sec"] = round(self._elapsed(self._job), 3)
        path = Path(self._job["run_dir"]) / "state.json"
        path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

    def _load_latest_state(self) -> None:
        paths = sorted(RUNS_DIR.glob("*/state.json"), reverse=True)
        if not paths:
            return
        try:
            state = json.loads(paths[0].read_text(encoding="utf-8"))
            if state.get("status") in {"running", "paused", "stopping"}:
                state["status"] = "interrupted"
                state["error"] = "Backend restarted before the learner completed"
            state["started_monotonic"] = time.monotonic() - float(state.get("duration_sec") or 0.0)
            state["paused_total_sec"] = 0.0
            state["pause_started_monotonic"] = None
            self._job = state
        except Exception:
            self._job = None

    @staticmethod
    def _mean_totals(items: list[dict[str, Any]]) -> dict[str, float]:
        keys = (
            "reward",
            "energy_kwh",
            "carbon_kg",
            "grid_carbon_kg",
            "fuel_carbon_kg",
            "cost",
            "delay_cost_cny",
            "delay_minutes",
            "processed_teu",
            "shore_power_kwh",
            "shore_power_opportunity_kwh",
            "safety_violations",
            "peak_violation_steps",
            "delay_violation_steps",
            "peak_kw",
        )
        return {key: round(float(np.mean([float(item[key]) for item in items])), 6) for key in keys}

    @staticmethod
    def _saving(baseline: float, policy: float) -> float:
        return round((baseline - policy) / max(abs(baseline), 1e-9) * 100.0, 3)

    @staticmethod
    def _sha256_file(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _cached_sha256(self, path: Path) -> str:
        stat = path.stat()
        key = str(path.resolve())
        with self._lock:
            cached = self._digest_cache.get(key)
            if cached and cached[:2] == (stat.st_mtime_ns, stat.st_size):
                return cached[2]
        digest = self._sha256_file(path)
        with self._lock:
            self._digest_cache[key] = (stat.st_mtime_ns, stat.st_size, digest)
        return digest

    @staticmethod
    def _runtime_versions() -> dict[str, str]:
        import gymnasium
        import stable_baselines3
        import torch

        return {
            "python": platform.python_version(),
            "python_implementation": platform.python_implementation(),
            "platform": sys.platform,
            "machine": platform.machine(),
            "numpy": np.__version__,
            "torch": torch.__version__,
            "gymnasium": gymnasium.__version__,
            "stable_baselines3": stable_baselines3.__version__,
        }

    @staticmethod
    def _valid_ppo_batch(candidate: int, n_steps: int) -> int:
        for value in range(max(2, candidate), 1, -1):
            if n_steps % value == 0:
                return value
        return n_steps

    @staticmethod
    def _elapsed(job: dict[str, Any]) -> float:
        if (
            job.get("status") in {"completed", "stopped", "failed", "interrupted"}
            and job.get("duration_sec") is not None
        ):
            return float(job["duration_sec"])
        end = time.monotonic()
        if job.get("status") == "paused" and job.get("pause_started_monotonic"):
            end = float(job["pause_started_monotonic"])
        return max(
            0.0,
            end
            - float(job.get("started_monotonic") or end)
            - float(job.get("paused_total_sec") or 0.0),
        )

    @staticmethod
    def _eta(remaining_sec: float | None) -> str | None:
        if remaining_sec is None:
            return None
        return (
            datetime.fromtimestamp(time.time() + remaining_sec, timezone.utc)
            .isoformat()
            .replace("+00:00", "Z")
        )

    @staticmethod
    def _summary(job: dict[str, Any], step: int) -> str:
        config = job["config"]
        return f"{job['status'].upper()} · {config['algorithm'].upper()} · {config['dataset_id']} · step={step}/{job['total_steps']}"

    def _idle_status(self) -> dict[str, Any]:
        return {
            "status": "idle",
            "progress": 0.0,
            "step": 0,
            "total_steps": 0,
            "reward": 0.0,
            "entropy": 0.0,
            "actor_loss": 0.0,
            "critic_loss": 0.0,
            "kl_divergence": 0.0,
            "success_rate": 0.0,
            "samples_per_sec": 0.0,
            "step_rate_per_min": 0.0,
            "recent_metrics": [],
            "policy_version": "—",
            "artifact_path": None,
            "started_at": None,
            "completed_at": None,
            "duration_sec": 0.0,
            "elapsed_sec": 0.0,
            "estimated_duration_sec": None,
            "remaining_sec": None,
            "eta_at": None,
            "can_pause": False,
            "can_resume": False,
            "can_stop": False,
            "config": {},
            "logs": [],
            "error": None,
            "summary": "No training job",
            "rendering": False,
            "evidence": "progress will come from learner callbacks",
        }


training_service = TrainingService()
