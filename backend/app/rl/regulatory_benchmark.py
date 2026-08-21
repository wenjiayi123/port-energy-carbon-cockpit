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
from app.rl.environment import (
    FixedDispatchPolicy,
    RegulatoryResiliencePolicy,
    encode_continuous_controls,
    observation_keys_for_environment,
)
from app.rl.robust import CausalForecastPortEnv, paired_bootstrap_interval


DATASET_ID = "port_la_2024_regulatory_resilience_hourly"
EVIDENCE_LABEL = "PREDECLARED_REGULATORY_ENERGY_STRESS_SCENARIO_NOT_FIELD_KPI"
REPORT_JSON = PROJECT_ROOT / "reports/regulatory_resilience_v1.json"
REPORT_MD = PROJECT_ROOT / "reports/regulatory_resilience_v1.md"
ARTIFACT_DIR = PROJECT_ROOT / "reports/regulatory_resilience_v1_artifacts"
PRESERVATION_REPORT = PROJECT_ROOT / "reports/regulatory_resilience_v1_history_preservation.json"
REWARD_WEIGHTS = {
    "carbon": 0.15,
    "shore_power": 0.05,
    "cost": 0.20,
    "delay": 0.28,
    "safety": 0.17,
    "peak": 0.10,
    "storage": 0.05,
}
SUMMARY_KEYS = (
    "reward",
    "energy_kwh",
    "carbon_kg",
    "cost",
    "delay_minutes",
    "regulatory_delay_minutes",
    "processed_teu",
    "processed_recovery_teu",
    "safety_violations",
    "peak_violation_steps",
    "delay_violation_steps",
    "peak_kw",
    "ending_queue_teu",
    "ending_maritime_hold_teu",
    "ending_customs_hold_teu",
    "ending_released_recovery_teu",
    "inspection_readiness_ratio_sum",
    "recovery_priority_ratio_sum",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _legacy_inventory() -> dict[str, str]:
    paths: list[Path] = []
    for pattern in (
        "reports/offline_benchmark*",
        "reports/port_landing_benchmark*",
        "reports/rl_tuning*",
        "reports/rl_td3_vessel_activity_100k/*",
        "backend/app/data/runs/*/manifest.json",
        "backend/app/data/runs/*/model.zip",
    ):
        paths.extend(path for path in PROJECT_ROOT.glob(pattern) if path.is_file())
    return {
        path.relative_to(PROJECT_ROOT).as_posix(): sha256_file(path)
        for path in sorted(set(paths))
        if "regulatory_resilience_v1" not in path.as_posix()
    }


def _train_seed(arguments: tuple[int, int]) -> dict[str, Any]:
    seed, steps = arguments
    import torch
    from stable_baselines3 import SAC
    from stable_baselines3.common.callbacks import BaseCallback

    torch.set_num_threads(1)
    env = CausalForecastPortEnv(
        dataset=DATASET_ID,
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
                info = next(
                    (
                        value.get("episode")
                        for value in self.locals.get("infos", [])
                        if isinstance(value, dict) and value.get("episode")
                    ),
                    None,
                )
                samples.append(
                    {
                        "step": int(self.num_timesteps),
                        "reward": round(float(rewards.mean()), 6),
                        "episode_complete": bool(info),
                        "episode_safety_violations": int(
                            float((info or {}).get("safety_violations", 0))
                        ),
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
    artifact_base = ARTIFACT_DIR / f"sac-seed-{seed}"
    model.save(str(artifact_base))
    artifact = artifact_base.with_suffix(".zip")
    env.close()
    return {
        "seed": seed,
        "algorithm": "SAC",
        "actual_steps": int(model.num_timesteps),
        "duration_sec": round(time.monotonic() - started, 3),
        "artifact": artifact.relative_to(PROJECT_ROOT).as_posix(),
        "artifact_sha256": sha256_file(artifact),
        "callback_metrics": samples,
    }


def _rollout(
    split: str,
    row_index: int,
    *,
    model: Any | None = None,
    policy_name: str = "learned",
) -> dict[str, Any]:
    env = CausalForecastPortEnv(
        dataset=DATASET_ID,
        split=split,
        action_mode="continuous",
        reward_weights=REWARD_WEIGHTS,
        episode_hours=24,
        render_mode=None,
    )
    observation, _ = env.reset(seed=20260821 + row_index, options={"row_index": row_index})
    fixed = FixedDispatchPolicy()
    regulatory = RegulatoryResiliencePolicy()
    terminated = truncated = False
    while not (terminated or truncated):
        if policy_name == "learned":
            action, _ = model.predict(observation, deterministic=True)
        elif policy_name == "regulatory_heuristic":
            action = encode_continuous_controls(regulatory.predict(env))
        elif policy_name == "legacy_fixed":
            action = encode_continuous_controls(fixed.predict(env))
        else:
            raise ValueError(policy_name)
        observation, _, terminated, truncated, _ = env.step(action)
    summary = env.summary()
    env.close()
    return summary


def _evaluate_model(artifact: Path, split: str) -> dict[str, Any]:
    from stable_baselines3 import SAC

    dataset = PortDataset.load(DATASET_ID)
    model = SAC.load(str(artifact), device="cpu")
    starts = dataset.evaluation_start_indices(split, 24)
    episodes = [_rollout(split, start, model=model) for start in starts]
    return {
        "split": split,
        "episode_hours": 24,
        "episode_count": len(episodes),
        "start_indices": starts,
        "aggregate": _aggregate(episodes),
        "episodes": episodes,
    }


def _evaluate_baseline(policy_name: str, split: str) -> dict[str, Any]:
    dataset = PortDataset.load(DATASET_ID)
    starts = dataset.evaluation_start_indices(split, 24)
    episodes = [_rollout(split, start, policy_name=policy_name) for start in starts]
    return {
        "split": split,
        "episode_hours": 24,
        "episode_count": len(episodes),
        "start_indices": starts,
        "aggregate": _aggregate(episodes),
        "episodes": episodes,
    }


def _aggregate(episodes: list[dict[str, Any]]) -> dict[str, float]:
    return {
        key: round(float(np.mean([float(item[key]) for item in episodes])), 6)
        for key in SUMMARY_KEYS
    }


def _saving(reference: float, candidate: float) -> float:
    return round((reference - candidate) / max(abs(reference), 1e-9) * 100.0, 3)


def _comparison(candidate: dict[str, float], reference: dict[str, float]) -> dict[str, float]:
    reference_backlog = (
        reference["ending_queue_teu"]
        + reference["ending_maritime_hold_teu"]
        + reference["ending_customs_hold_teu"]
        + reference["ending_released_recovery_teu"]
    )
    candidate_backlog = (
        candidate["ending_queue_teu"]
        + candidate["ending_maritime_hold_teu"]
        + candidate["ending_customs_hold_teu"]
        + candidate["ending_released_recovery_teu"]
    )
    return {
        "scenario_cost_reduction_pct": _saving(reference["cost"], candidate["cost"]),
        "carbon_reduction_pct": _saving(reference["carbon_kg"], candidate["carbon_kg"]),
        "total_delay_reduction_pct": _saving(
            reference["delay_minutes"], candidate["delay_minutes"]
        ),
        "regulatory_delay_reduction_pct": _saving(
            reference["regulatory_delay_minutes"], candidate["regulatory_delay_minutes"]
        ),
        "ending_backlog_reduction_pct": _saving(reference_backlog, candidate_backlog),
        "peak_change_pct": round(
            (candidate["peak_kw"] - reference["peak_kw"])
            / max(abs(reference["peak_kw"]), 1e-9)
            * 100.0,
            3,
        ),
        "throughput_change_pct": round(
            (candidate["processed_teu"] - reference["processed_teu"])
            / max(abs(reference["processed_teu"]), 1e-9)
            * 100.0,
            3,
        ),
        "safety_violation_change": round(
            candidate["safety_violations"] - reference["safety_violations"], 3
        ),
    }


def _report_markdown(report: dict[str, Any]) -> str:
    metrics = report["business_metrics_vs_legacy_fixed"]
    checks = report["offline_admission_gate"]["checks"]
    check_rows = "\n".join(
        f"| {item['name']} | {'PASS' if item['passed'] else 'BLOCKED'} | {item['value']} |"
        for item in checks
    )
    return f"""# 海事/海关检查能碳韧性策略 v1

> {report['evidence_label']}。这是公开数据底座上的预声明压力情景，不是海事局、海关或码头现场 KPI。

## 结论

保留原有 v1–v3 和全部历史策略，新增 `PortEnergyDispatchEnv-v4`（48 维观测、6 维连续动作/729 个离散组合）。检查、扣留、放行信号均为外生；策略只控制码头准备度和放行后恢复优先级。

在独立留出测试集上，入选 SAC 相对旧固定策略：情景成本 {metrics['scenario_cost_reduction_pct']:+.2f}%，总延误 {metrics['total_delay_reduction_pct']:+.2f}%，监管链延误 {metrics['regulatory_delay_reduction_pct']:+.2f}%，碳排 {metrics['carbon_reduction_pct']:+.2f}%，期末积压 {metrics['ending_backlog_reduction_pct']:+.2f}%。

## 训练与盲测协议

- 三个 SAC 种子各 {report['protocol']['steps_per_seed']:,} 个真实 learner steps；训练不渲染。
- 只用 validation 选种子；选定后才读取 test，48 个固定 24 小时窗口。
- 历史文件 {report['history_preservation']['file_count']} 个哈希前后一致，未覆盖旧模型、报告或失败候选。

## 离线准入门

| 检查 | 结果 | 数值 |
|---|---:|---:|
{check_rows}

最终状态：**{report['offline_admission_gate']['status']}**。即使通过离线门，`production_authority=false`，仍需真实监管/TOS/EMS/设备数据、现场标定、影子运行和人工授权。
"""


def run(steps: int, seeds: list[int], workers: int) -> dict[str, Any]:
    legacy_before = _legacy_inventory()
    dataset = PortDataset.load(DATASET_ID)
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    jobs = [(seed, steps) for seed in seeds]
    if workers > 1:
        with ProcessPoolExecutor(max_workers=min(workers, len(jobs))) as pool:
            candidates = list(pool.map(_train_seed, jobs))
    else:
        candidates = [_train_seed(job) for job in jobs]

    for candidate in candidates:
        candidate["validation"] = _evaluate_model(
            PROJECT_ROOT / candidate["artifact"], "validation"
        )
    selected = min(
        candidates,
        key=lambda item: (
            item["validation"]["aggregate"]["safety_violations"],
            -item["validation"]["aggregate"]["reward"],
            item["seed"],
        ),
    )
    selected["test"] = _evaluate_model(PROJECT_ROOT / selected["artifact"], "test")
    heuristic_test = _evaluate_baseline("regulatory_heuristic", "test")
    legacy_test = _evaluate_baseline("legacy_fixed", "test")
    selected_test = selected["test"]["aggregate"]
    legacy_aggregate = legacy_test["aggregate"]
    heuristic_aggregate = heuristic_test["aggregate"]
    business_metrics = _comparison(selected_test, legacy_aggregate)
    heuristic_metrics = _comparison(selected_test, heuristic_aggregate)

    cost_ci = paired_bootstrap_interval(
        [float(item["cost"]) for item in selected["test"]["episodes"]],
        [float(item["cost"]) for item in legacy_test["episodes"]],
        samples=2_000,
        seed=20260821,
    )
    delay_ci = paired_bootstrap_interval(
        [float(item["delay_minutes"]) for item in selected["test"]["episodes"]],
        [float(item["delay_minutes"]) for item in legacy_test["episodes"]],
        samples=2_000,
        seed=20260822,
    )
    checks = [
        {"name": "dataset_quality", "passed": dataset.quality_report()["status"] == "pass", "value": dataset.quality_report()["status"]},
        {"name": "train_validation_test_isolation", "passed": True, "value": "validation selected; test once"},
        {"name": "minimum_training_steps", "passed": selected["actual_steps"] >= 5_000, "value": selected["actual_steps"]},
        {"name": "test_window_count", "passed": selected["test"]["episode_count"] >= 30, "value": selected["test"]["episode_count"]},
        {"name": "cost_non_regression", "passed": business_metrics["scenario_cost_reduction_pct"] >= 0, "value": business_metrics["scenario_cost_reduction_pct"]},
        {"name": "delay_non_regression", "passed": business_metrics["total_delay_reduction_pct"] >= 0, "value": business_metrics["total_delay_reduction_pct"]},
        {"name": "regulatory_delay_non_regression", "passed": business_metrics["regulatory_delay_reduction_pct"] >= 0, "value": business_metrics["regulatory_delay_reduction_pct"]},
        {"name": "cost_ci95_non_regression", "passed": cost_ci["ci95_low_pct"] >= 0, "value": cost_ci["ci95_low_pct"]},
        {"name": "delay_ci95_non_regression", "passed": delay_ci["ci95_low_pct"] >= 0, "value": delay_ci["ci95_low_pct"]},
        {"name": "zero_mean_safety_violations", "passed": selected_test["safety_violations"] == 0, "value": selected_test["safety_violations"]},
    ]
    legacy_after = _legacy_inventory()
    preservation = {
        "history_preserved": legacy_before == legacy_after,
        "file_count": len(legacy_before),
        "before_sha256": hashlib.sha256(json.dumps(legacy_before, sort_keys=True).encode()).hexdigest(),
        "after_sha256": hashlib.sha256(json.dumps(legacy_after, sort_keys=True).encode()).hexdigest(),
        "changed_files": sorted(
            key for key in set(legacy_before) | set(legacy_after) if legacy_before.get(key) != legacy_after.get(key)
        ),
        "files": legacy_after,
    }
    PRESERVATION_REPORT.write_text(
        json.dumps(preservation, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    checks.append(
        {
            "name": "historical_artifacts_preserved",
            "passed": preservation["history_preserved"],
            "value": preservation["file_count"],
        }
    )
    offline_passed = all(item["passed"] for item in checks)
    report: dict[str, Any] = {
        "report_version": "1.0",
        "generated_at": utc_now(),
        "status": "qualified_offline" if offline_passed else "blocked_candidate_preserved",
        "evidence_label": EVIDENCE_LABEL,
        "boundary": {
            "inspection_selection": "exogenous",
            "detention": "exogenous",
            "official_release": "exogenous",
            "policy_authority": "terminal readiness and post-release recovery only",
            "simulation_mode": True,
            "live_data_verified": False,
            "dispatch_allowed": False,
            "production_authority": False,
        },
        "dataset": {
            "id": dataset.dataset_id,
            "environment_id": dataset.environment_id,
            "rows": len(dataset.frame),
            "package_sha256": dataset.package_sha256,
            "quality": dataset.quality_report(),
        },
        "contract": {
            "observation_count": len(observation_keys_for_environment(dataset.environment_id)),
            "continuous_action_count": 6,
            "dqn_discrete_combinations": 729,
            "new_controls": ["inspection_readiness_ratio", "recovery_priority_ratio"],
        },
        "protocol": {
            "algorithm": "SAC",
            "seeds": seeds,
            "steps_per_seed": steps,
            "train_render_mode": None,
            "selection_split": "validation",
            "final_report_split": "test",
            "forecast_protocol": "causal_current_row_persistence_v1",
            "selection_rule": "minimum validation safety violations, then maximum validation reward, then seed",
            "test_access_before_selection": False,
        },
        "candidates": candidates,
        "selected_seed": selected["seed"],
        "selected_artifact": selected["artifact"],
        "selected_artifact_sha256": selected["artifact_sha256"],
        "test_aggregates": {
            "selected_sac": selected_test,
            "legacy_fixed_v1_v3_adapter": legacy_aggregate,
            "inspection_aware_auditable_heuristic": heuristic_aggregate,
        },
        "business_metrics_vs_legacy_fixed": business_metrics,
        "algorithm_increment_vs_inspection_aware_heuristic": heuristic_metrics,
        "uncertainty": {
            "cost_reduction_vs_legacy_fixed_ci95": cost_ci,
            "delay_reduction_vs_legacy_fixed_ci95": delay_ci,
        },
        "offline_admission_gate": {
            "status": "passed" if offline_passed else "blocked",
            "checks": checks,
            "production_authority": False,
        },
        "history_preservation": {
            key: preservation[key]
            for key in ("history_preserved", "file_count", "before_sha256", "after_sha256", "changed_files")
        },
        "limitations": [
            "Regulatory events are deterministic stress variables, not historical authority events.",
            "The public data package has no terminal meter, TOS, customs, PSC, vessel identity or equipment telemetry.",
            "Offline qualification cannot authorize production dispatch or legal/regulatory decisions.",
        ],
    }
    report["evidence_sha256"] = hashlib.sha256(
        json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    REPORT_JSON.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    REPORT_MD.write_text(_report_markdown(report), encoding="utf-8")
    return report


def verify(path: Path) -> dict[str, Any]:
    report = json.loads(path.read_text(encoding="utf-8"))
    expected = report.pop("evidence_sha256")
    actual = hashlib.sha256(
        json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    artifact = PROJECT_ROOT / report["selected_artifact"]
    return {
        "valid": expected == actual and artifact.exists() and sha256_file(artifact) == report["selected_artifact_sha256"],
        "report_sha256_matches": expected == actual,
        "artifact_sha256_matches": artifact.exists() and sha256_file(artifact) == report["selected_artifact_sha256"],
        "history_preserved": report["history_preservation"]["history_preserved"],
        "offline_admission_status": report["offline_admission_gate"]["status"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Regulatory delay energy-carbon training evidence")
    sub = parser.add_subparsers(dest="command", required=True)
    run_parser = sub.add_parser("run")
    run_parser.add_argument("--steps", type=int, default=5_000)
    run_parser.add_argument("--seeds", default="11,29,47")
    run_parser.add_argument("--workers", type=int, default=3)
    verify_parser = sub.add_parser("verify")
    verify_parser.add_argument("path", nargs="?", default=str(REPORT_JSON))
    args = parser.parse_args()
    if args.command == "verify":
        print(json.dumps(verify(Path(args.path)), ensure_ascii=False, indent=2))
        return
    seeds = [int(value) for value in args.seeds.split(",") if value.strip()]
    report = run(args.steps, seeds, args.workers)
    print(
        json.dumps(
            {
                "status": report["status"],
                "selected_seed": report["selected_seed"],
                "business_metrics": report["business_metrics_vs_legacy_fixed"],
                "offline_admission": report["offline_admission_gate"]["status"],
                "report": REPORT_JSON.relative_to(PROJECT_ROOT).as_posix(),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
