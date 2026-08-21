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
from app.rl.environment import FixedDispatchPolicy, encode_continuous_controls
from app.rl.regulatory_benchmark import (
    DATASET_ID as DEVELOPMENT_DATASET_ID,
    EVIDENCE_LABEL,
    REWARD_WEIGHTS,
    _aggregate,
    _comparison,
    _legacy_inventory,
    sha256_file,
)
from app.rl.robust import CausalForecastPortEnv, paired_bootstrap_interval


FORWARD_DATASET_ID = "port_la_2025_regulatory_forward_challenge_hourly"
REPORT_JSON = PROJECT_ROOT / "reports/regulatory_resilience_v2.json"
REPORT_MD = PROJECT_ROOT / "reports/regulatory_resilience_v2.md"
ARTIFACT_DIR = PROJECT_ROOT / "reports/regulatory_resilience_v2_artifacts"
PRESERVATION_REPORT = PROJECT_ROOT / "reports/regulatory_resilience_v2_history_preservation.json"


class ShieldedIncrementalRegulatoryEnv(CausalForecastPortEnv):
    """Learn only v4 additions while preserving the proven four-action baseline."""

    def decode_action(self, action: np.ndarray | int) -> dict[str, float]:
        controls = super().decode_action(action)
        authority_release_signal = max(
            self._row_value("maritime_release_ratio"),
            self._row_value("customs_release_ratio"),
        )
        release_work_exists = bool(
            self._released_recovery_teu > 0.0 or authority_release_signal >= 0.10
        )
        raw_readiness = controls.get("inspection_readiness_ratio", 0.0)
        raw_recovery = controls.get("recovery_priority_ratio", 0.0)
        # The learner may prepare a small standby team before release. Full
        # activation and recovery are enabled only by the exogenous release
        # signal or an already released queue.
        readiness = raw_readiness if release_work_exists else min(raw_readiness, 0.10)
        recovery = raw_recovery if release_work_exists else 0.0
        controls.update(
            shore_power_ratio=1.0,
            crane_ratio=1.0,
            yard_ratio=1.0,
            battery_power_ratio=0.0,
            inspection_readiness_ratio=float(readiness),
            recovery_priority_ratio=float(recovery),
        )
        return controls


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _protected_inventory() -> dict[str, str]:
    inventory = _legacy_inventory()
    for path in sorted(PROJECT_ROOT.glob("reports/regulatory_resilience_v1*")):
        if path.is_file():
            inventory[path.relative_to(PROJECT_ROOT).as_posix()] = sha256_file(path)
        elif path.is_dir():
            for child in sorted(path.glob("*")):
                if child.is_file():
                    inventory[child.relative_to(PROJECT_ROOT).as_posix()] = sha256_file(child)
    return inventory


def _train_seed(arguments: tuple[int, int]) -> dict[str, Any]:
    seed, steps = arguments
    import torch
    from stable_baselines3 import SAC
    from stable_baselines3.common.callbacks import BaseCallback

    torch.set_num_threads(1)
    env = ShieldedIncrementalRegulatoryEnv(
        dataset=DEVELOPMENT_DATASET_ID,
        split="train",
        action_mode="continuous",
        reward_weights=REWARD_WEIGHTS,
        episode_hours=24,
        render_mode=None,
    )
    samples: list[dict[str, Any]] = []

    class EvidenceCallback(BaseCallback):
        def _on_step(self) -> bool:
            if self.num_timesteps % 250 == 0 or self.num_timesteps == steps:
                rewards = np.asarray(self.locals.get("rewards", [0.0]), dtype=float)
                samples.append(
                    {
                        "step": int(self.num_timesteps),
                        "reward": round(float(rewards.mean()), 6),
                    }
                )
            return True

    model = SAC(
        "MlpPolicy",
        env,
        learning_rate=3e-4,
        batch_size=128,
        gamma=0.99,
        tau=0.005,
        learning_starts=min(500, max(100, steps // 10)),
        buffer_size=max(10_000, steps * 2),
        policy_kwargs={"net_arch": [128, 128]},
        seed=seed,
        verbose=0,
        device="cpu",
    )
    started = time.monotonic()
    model.learn(total_timesteps=steps, callback=EvidenceCallback(), progress_bar=False)
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    artifact_base = ARTIFACT_DIR / f"shielded-sac-seed-{seed}"
    model.save(str(artifact_base))
    artifact = artifact_base.with_suffix(".zip")
    env.close()
    return {
        "seed": seed,
        "algorithm": "Shielded incremental SAC",
        "actual_steps": int(model.num_timesteps),
        "duration_sec": round(time.monotonic() - started, 3),
        "artifact": artifact.relative_to(PROJECT_ROOT).as_posix(),
        "artifact_sha256": sha256_file(artifact),
        "callback_metrics": samples,
    }


def _rollout_model(dataset_id: str, split: str, row_index: int, model: Any) -> dict[str, Any]:
    env = ShieldedIncrementalRegulatoryEnv(
        dataset=dataset_id,
        split=split,
        action_mode="continuous",
        reward_weights=REWARD_WEIGHTS,
        episode_hours=24,
        render_mode=None,
    )
    observation, _ = env.reset(seed=20260821 + row_index, options={"row_index": row_index})
    terminated = truncated = False
    while not (terminated or truncated):
        action, _ = model.predict(observation, deterministic=True)
        observation, _, terminated, truncated, _ = env.step(action)
    summary = env.summary()
    env.close()
    return summary


def _rollout_legacy(dataset_id: str, split: str, row_index: int) -> dict[str, Any]:
    env = CausalForecastPortEnv(
        dataset=dataset_id,
        split=split,
        action_mode="continuous",
        reward_weights=REWARD_WEIGHTS,
        episode_hours=24,
        render_mode=None,
    )
    _, _ = env.reset(seed=20260821 + row_index, options={"row_index": row_index})
    policy = FixedDispatchPolicy()
    terminated = truncated = False
    while not (terminated or truncated):
        _, _, terminated, truncated, _ = env.step(
            encode_continuous_controls(policy.predict(env))
        )
    summary = env.summary()
    env.close()
    return summary


def _evaluate_model(artifact: Path, dataset_id: str, split: str) -> dict[str, Any]:
    from stable_baselines3 import SAC

    package = PortDataset.load(dataset_id)
    starts = package.evaluation_start_indices(split, 24)
    model = SAC.load(str(artifact), device="cpu")
    episodes = [_rollout_model(dataset_id, split, index, model) for index in starts]
    return {
        "dataset_id": dataset_id,
        "split": split,
        "episode_count": len(episodes),
        "episode_hours": 24,
        "start_indices": starts,
        "aggregate": _aggregate(episodes),
        "episodes": episodes,
    }


def _evaluate_legacy(dataset_id: str, split: str) -> dict[str, Any]:
    package = PortDataset.load(dataset_id)
    starts = package.evaluation_start_indices(split, 24)
    episodes = [_rollout_legacy(dataset_id, split, index) for index in starts]
    return {
        "dataset_id": dataset_id,
        "split": split,
        "episode_count": len(episodes),
        "episode_hours": 24,
        "start_indices": starts,
        "aggregate": _aggregate(episodes),
        "episodes": episodes,
    }


def _markdown(report: dict[str, Any]) -> str:
    metrics = report["business_metrics_vs_preserved_legacy"]
    rows = "\n".join(
        f"| {item['name']} | {'PASS' if item['passed'] else 'BLOCKED'} | {item['value']} |"
        for item in report["offline_admission_gate"]["checks"]
    )
    return f"""# 海事/海关检查能碳韧性策略 v2

> {report['evidence_label']}。监管事件与 v3 接入变量是冻结压力情景，不是现场或监管机关实测 KPI。

## 结果

首轮全动作 SAC 失败候选完整保留；v2 冻结原四项能碳动作，只学习检查准备度与放行恢复优先级，并由外生放行信号启用动作。

在未参与训练、选种和门控设计的 2025 前向挑战 test 上，相对保留的旧固定策略：情景成本 {metrics['scenario_cost_reduction_pct']:+.3f}%，碳排 {metrics['carbon_reduction_pct']:+.3f}%，总延误 {metrics['total_delay_reduction_pct']:+.3f}%，监管链延误 {metrics['regulatory_delay_reduction_pct']:+.3f}%，峰值 {metrics['peak_change_pct']:+.3f}%。

## 离线准入门

| 检查 | 结果 | 数值 |
|---|---:|---:|
{rows}

状态：**{report['offline_admission_gate']['status']}**。生产权限始终关闭。
"""


def run(steps: int, seeds: list[int], workers: int) -> dict[str, Any]:
    protected_before = _protected_inventory()
    development = PortDataset.load(DEVELOPMENT_DATASET_ID)
    forward = PortDataset.load(FORWARD_DATASET_ID)
    jobs = [(seed, steps) for seed in seeds]
    if workers > 1:
        with ProcessPoolExecutor(max_workers=min(workers, len(jobs))) as pool:
            candidates = list(pool.map(_train_seed, jobs))
    else:
        candidates = [_train_seed(job) for job in jobs]
    for candidate in candidates:
        candidate["validation"] = _evaluate_model(
            PROJECT_ROOT / candidate["artifact"],
            DEVELOPMENT_DATASET_ID,
            "validation",
        )
    selected = min(
        candidates,
        key=lambda item: (
            item["validation"]["aggregate"]["safety_violations"],
            -item["validation"]["aggregate"]["reward"],
            item["seed"],
        ),
    )
    # First and only policy evaluation on the frozen 2025 forward test split.
    selected_forward = _evaluate_model(
        PROJECT_ROOT / selected["artifact"], FORWARD_DATASET_ID, "test"
    )
    legacy_forward = _evaluate_legacy(FORWARD_DATASET_ID, "test")
    candidate_aggregate = selected_forward["aggregate"]
    legacy_aggregate = legacy_forward["aggregate"]
    business = _comparison(candidate_aggregate, legacy_aggregate)
    cost_ci = paired_bootstrap_interval(
        [float(item["cost"]) for item in selected_forward["episodes"]],
        [float(item["cost"]) for item in legacy_forward["episodes"]],
        samples=2_000,
        seed=20260823,
    )
    delay_ci = paired_bootstrap_interval(
        [float(item["delay_minutes"]) for item in selected_forward["episodes"]],
        [float(item["delay_minutes"]) for item in legacy_forward["episodes"]],
        samples=2_000,
        seed=20260824,
    )
    protected_after = _protected_inventory()
    preservation = {
        "history_preserved": protected_before == protected_after,
        "file_count": len(protected_before),
        "before_sha256": hashlib.sha256(
            json.dumps(protected_before, sort_keys=True).encode()
        ).hexdigest(),
        "after_sha256": hashlib.sha256(
            json.dumps(protected_after, sort_keys=True).encode()
        ).hexdigest(),
        "changed_files": sorted(
            key
            for key in set(protected_before) | set(protected_after)
            if protected_before.get(key) != protected_after.get(key)
        ),
        "files": protected_after,
    }
    PRESERVATION_REPORT.write_text(
        json.dumps(preservation, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    checks = [
        {"name": "development_dataset_quality", "passed": development.quality_report()["status"] == "pass", "value": development.quality_report()["status"]},
        {"name": "forward_dataset_quality", "passed": forward.quality_report()["status"] == "pass", "value": forward.quality_report()["status"]},
        {"name": "minimum_training_steps", "passed": selected["actual_steps"] >= 5_000, "value": selected["actual_steps"]},
        {"name": "validation_only_selection", "passed": True, "value": "2024 validation"},
        {"name": "untouched_forward_test", "passed": True, "value": "2025 test evaluated once after selection"},
        {"name": "forward_window_count", "passed": selected_forward["episode_count"] >= 30, "value": selected_forward["episode_count"]},
        {"name": "cost_non_regression", "passed": business["scenario_cost_reduction_pct"] >= 0, "value": business["scenario_cost_reduction_pct"]},
        {"name": "carbon_non_regression", "passed": business["carbon_reduction_pct"] >= 0, "value": business["carbon_reduction_pct"]},
        {"name": "delay_non_regression", "passed": business["total_delay_reduction_pct"] >= 0, "value": business["total_delay_reduction_pct"]},
        {"name": "regulatory_delay_non_regression", "passed": business["regulatory_delay_reduction_pct"] >= 0, "value": business["regulatory_delay_reduction_pct"]},
        {"name": "cost_ci95_non_regression", "passed": cost_ci["ci95_low_pct"] >= 0, "value": cost_ci["ci95_low_pct"]},
        {"name": "delay_ci95_non_regression", "passed": delay_ci["ci95_low_pct"] >= 0, "value": delay_ci["ci95_low_pct"]},
        {"name": "zero_mean_safety_violations", "passed": candidate_aggregate["safety_violations"] == 0, "value": candidate_aggregate["safety_violations"]},
        {"name": "old_and_failed_artifacts_preserved", "passed": preservation["history_preserved"], "value": preservation["file_count"]},
    ]
    passed = all(item["passed"] for item in checks)
    v1_path = PROJECT_ROOT / "reports/regulatory_resilience_v1.json"
    v1 = json.loads(v1_path.read_text(encoding="utf-8"))
    report: dict[str, Any] = {
        "report_version": "2.0",
        "generated_at": utc_now(),
        "status": "qualified_offline" if passed else "blocked_candidate_preserved",
        "evidence_label": EVIDENCE_LABEL,
        "strategy": {
            "name": "shielded_incremental_regulatory_sac_v2",
            "preserved_controls": [
                "shore_power_ratio",
                "crane_ratio",
                "yard_ratio",
                "battery_power_ratio",
            ],
            "learned_controls": [
                "inspection_readiness_ratio",
                "recovery_priority_ratio",
            ],
            "release_gate": "full activation requires exogenous release >= 0.10 or an officially released recovery queue",
        },
        "boundary": {
            "authority_signals": "exogenous",
            "policy_authority": "terminal readiness and post-release recovery only",
            "simulation_mode": True,
            "live_data_verified": False,
            "dispatch_allowed": False,
            "production_authority": False,
        },
        "datasets": {
            "development": {"id": development.dataset_id, "package_sha256": development.package_sha256},
            "forward_challenge": {"id": forward.dataset_id, "package_sha256": forward.package_sha256},
        },
        "protocol": {
            "algorithm": "SAC with action projection",
            "seeds": seeds,
            "steps_per_seed": steps,
            "train_split": "2024 train",
            "selection_split": "2024 validation",
            "final_forward_split": "2025 test",
            "forward_test_access_before_selection": False,
            "train_render_mode": None,
            "selection_rule": "minimum validation safety violations, then maximum validation reward, then seed",
        },
        "candidates": candidates,
        "selected_seed": selected["seed"],
        "selected_artifact": selected["artifact"],
        "selected_artifact_sha256": selected["artifact_sha256"],
        "forward_test": {
            "selected_policy": selected_forward,
            "preserved_legacy": legacy_forward,
        },
        "business_metrics_vs_preserved_legacy": business,
        "uncertainty": {
            "cost_reduction_ci95": cost_ci,
            "delay_reduction_ci95": delay_ci,
        },
        "offline_admission_gate": {
            "status": "passed" if passed else "blocked",
            "checks": checks,
            "production_authority": False,
        },
        "history_preservation": {
            key: preservation[key]
            for key in ("history_preserved", "file_count", "before_sha256", "after_sha256", "changed_files")
        },
        "preserved_failed_candidate": {
            "report": "reports/regulatory_resilience_v1.json",
            "report_file_sha256": sha256_file(v1_path),
            "status": v1["status"],
            "offline_admission": v1["offline_admission_gate"]["status"],
        },
        "limitations": [
            "All regulatory events are frozen stress variables, not authority history or live feeds.",
            "The forward package adds scenario vessel and deployment covariates because 2025 daily official activity was not bundled.",
            "Offline admission never grants field dispatch or regulatory decision authority.",
        ],
    }
    report["evidence_sha256"] = hashlib.sha256(
        json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    REPORT_JSON.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    REPORT_MD.write_text(_markdown(report), encoding="utf-8")
    return report


def verify(path: Path) -> dict[str, Any]:
    report = json.loads(path.read_text(encoding="utf-8"))
    expected = report.pop("evidence_sha256")
    actual = hashlib.sha256(
        json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    artifact = PROJECT_ROOT / report["selected_artifact"]
    return {
        "valid": expected == actual and sha256_file(artifact) == report["selected_artifact_sha256"],
        "report_sha256_matches": expected == actual,
        "artifact_sha256_matches": sha256_file(artifact) == report["selected_artifact_sha256"],
        "offline_admission_status": report["offline_admission_gate"]["status"],
        "history_preserved": report["history_preservation"]["history_preserved"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Shielded incremental regulatory SAC evidence")
    sub = parser.add_subparsers(dest="command", required=True)
    run_parser = sub.add_parser("run")
    run_parser.add_argument("--steps", type=int, default=5_000)
    run_parser.add_argument("--seeds", default="13,31,53")
    run_parser.add_argument("--workers", type=int, default=3)
    verify_parser = sub.add_parser("verify")
    verify_parser.add_argument("path", nargs="?", default=str(REPORT_JSON))
    args = parser.parse_args()
    if args.command == "verify":
        print(json.dumps(verify(Path(args.path)), ensure_ascii=False, indent=2))
        return
    report = run(
        args.steps,
        [int(value) for value in args.seeds.split(",") if value.strip()],
        args.workers,
    )
    print(
        json.dumps(
            {
                "status": report["status"],
                "selected_seed": report["selected_seed"],
                "business_metrics": report["business_metrics_vs_preserved_legacy"],
                "offline_admission": report["offline_admission_gate"]["status"],
                "report": REPORT_JSON.relative_to(PROJECT_ROOT).as_posix(),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
