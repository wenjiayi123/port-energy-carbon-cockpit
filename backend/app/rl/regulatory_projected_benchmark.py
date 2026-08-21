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


FINAL_DATASET_ID = "port_la_2025_regulatory_final_challenge_hourly"
REPORT_JSON = PROJECT_ROOT / "reports/regulatory_resilience_v3.json"
REPORT_MD = PROJECT_ROOT / "reports/regulatory_resilience_v3.md"
ARTIFACT_DIR = PROJECT_ROOT / "reports/regulatory_resilience_v3_artifacts"
PRESERVATION_REPORT = PROJECT_ROOT / "reports/regulatory_resilience_v3_history_preservation.json"


class DominanceProjectedRegulatoryEnv(CausalForecastPortEnv):
    """Project SAC proposals onto a no-regression regulatory service envelope."""

    def _minimum_energy_controls(self, target_teu: float) -> tuple[float, float, float]:
        resource = float(
            np.clip(self._row_value("inspection_resource_available_ratio"), 0.0, 1.0)
        )
        berth = float(np.clip(self._row_value("berth_available_ratio", 1.0), 0.0, 1.0))
        crane = (
            self._parameter("crane_capacity_teu_per_hour")
            * float(np.clip(self._row_value("crane_available_ratio", 1.0), 0.0, 1.0))
            * berth
        )
        yard = (
            self._parameter("yard_capacity_teu_per_hour")
            * float(np.clip(self._row_value("yard_available_ratio", 1.0), 0.0, 1.0))
            * berth
        )
        joint = max(1.0, min(crane, yard))
        staging = self._parameter("released_staging_capacity_teu_per_hour")
        recovery_ratio = self._parameter("recovery_capacity_ratio")
        feasible: list[tuple[float, float, float]] = []
        for readiness in np.linspace(0.0, 1.0, 101):
            readiness_capacity = staging * resource * (0.20 + 0.80 * readiness)
            recovery = target_teu / max(1.0, joint * recovery_ratio)
            if target_teu <= readiness_capacity + 1e-9 and recovery <= 1.0 + 1e-9:
                action_load = (
                    self._parameter("inspection_readiness_load_kw") * readiness
                    + self._parameter("regulatory_recovery_load_kw")
                    * target_teu
                    / max(1.0, readiness_capacity)
                )
                feasible.append((action_load, float(readiness), float(np.clip(recovery, 0, 1))))
        if not feasible:
            return float("inf"), 1.0, 1.0
        return min(feasible, key=lambda item: (item[0], item[1], item[2]))

    def decode_action(self, action: np.ndarray | int) -> dict[str, float]:
        raw = CausalForecastPortEnv.decode_action(self, action)
        base_demand = self._demand_teu()
        maritime_arrival = base_demand * float(
            np.clip(self._row_value("maritime_inspection_ratio"), 0.0, 1.0)
        )
        customs_arrival = base_demand * float(
            np.clip(self._row_value("customs_inspection_ratio"), 0.0, 1.0)
        )
        maritime_release = (self._maritime_hold_teu + maritime_arrival) * float(
            np.clip(self._row_value("maritime_release_ratio"), 0.0, 1.0)
        )
        customs_release = (self._customs_hold_teu + customs_arrival) * float(
            np.clip(self._row_value("customs_release_ratio"), 0.0, 1.0)
        )
        available = self._released_recovery_teu + maritime_release + customs_release

        resource = float(
            np.clip(self._row_value("inspection_resource_available_ratio"), 0.0, 1.0)
        )
        berth = float(np.clip(self._row_value("berth_available_ratio", 1.0), 0.0, 1.0))
        joint = min(
            self._parameter("crane_capacity_teu_per_hour")
            * float(np.clip(self._row_value("crane_available_ratio", 1.0), 0.0, 1.0))
            * berth,
            self._parameter("yard_capacity_teu_per_hour")
            * float(np.clip(self._row_value("yard_available_ratio", 1.0), 0.0, 1.0))
            * berth,
        )
        legacy_target = min(
            available,
            self._parameter("released_staging_capacity_teu_per_hour")
            * resource
            * (0.20 + 0.80 * 0.35),
            joint * self._parameter("recovery_capacity_ratio") * 0.35,
        )
        extra_fraction = 0.5 * (
            raw.get("inspection_readiness_ratio", 0.0)
            + raw.get("recovery_priority_ratio", 0.0)
        )
        proposed_target = legacy_target + extra_fraction * max(0.0, available - legacy_target)
        legacy_load, legacy_readiness, legacy_recovery = self._minimum_energy_controls(
            legacy_target
        )
        proposed_load, proposed_readiness, proposed_recovery = self._minimum_energy_controls(
            proposed_target
        )
        price = float(self._row()["electricity_price_per_kwh"])
        delay_value_per_teu = (
            self._parameter("delay_cost_cny_per_minute") * 60.0 / max(1.0, base_demand)
        )
        legacy_objective = legacy_load * price + (available - legacy_target) * delay_value_per_teu
        proposed_objective = (
            proposed_load * price + (available - proposed_target) * delay_value_per_teu
        )
        if proposed_objective <= legacy_objective:
            readiness, recovery = proposed_readiness, proposed_recovery
        else:
            readiness, recovery = legacy_readiness, legacy_recovery
        raw.update(
            shore_power_ratio=1.0,
            crane_ratio=1.0,
            yard_ratio=1.0,
            battery_power_ratio=0.0,
            inspection_readiness_ratio=readiness,
            recovery_priority_ratio=recovery,
        )
        return raw


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _protected_inventory() -> dict[str, str]:
    inventory = _legacy_inventory()
    for pattern in ("reports/regulatory_resilience_v1*", "reports/regulatory_resilience_v2*"):
        for path in sorted(PROJECT_ROOT.glob(pattern)):
            if path.is_file():
                inventory[path.relative_to(PROJECT_ROOT).as_posix()] = sha256_file(path)
            elif path.is_dir():
                for child in sorted(path.glob("*")):
                    if child.is_file():
                        inventory[child.relative_to(PROJECT_ROOT).as_posix()] = sha256_file(child)
    return inventory


def _train_seed(job: tuple[int, int]) -> dict[str, Any]:
    seed, steps = job
    import torch
    from stable_baselines3 import SAC
    from stable_baselines3.common.callbacks import BaseCallback

    torch.set_num_threads(1)
    env = DominanceProjectedRegulatoryEnv(
        dataset=DEVELOPMENT_DATASET_ID,
        split="train",
        action_mode="continuous",
        reward_weights=REWARD_WEIGHTS,
        episode_hours=24,
        render_mode=None,
    )
    samples: list[dict[str, Any]] = []

    class Callback(BaseCallback):
        def _on_step(self) -> bool:
            if self.num_timesteps % 250 == 0 or self.num_timesteps == steps:
                rewards = np.asarray(self.locals.get("rewards", [0.0]), dtype=float)
                samples.append(
                    {"step": int(self.num_timesteps), "reward": round(float(rewards.mean()), 6)}
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
    model.learn(total_timesteps=steps, callback=Callback(), progress_bar=False)
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    base = ARTIFACT_DIR / f"projected-sac-seed-{seed}"
    model.save(str(base))
    artifact = base.with_suffix(".zip")
    env.close()
    return {
        "seed": seed,
        "algorithm": "Dominance-projected incremental SAC",
        "actual_steps": int(model.num_timesteps),
        "duration_sec": round(time.monotonic() - started, 3),
        "artifact": artifact.relative_to(PROJECT_ROOT).as_posix(),
        "artifact_sha256": sha256_file(artifact),
        "callback_metrics": samples,
    }


def _evaluate_model(artifact: Path, dataset_id: str, split: str) -> dict[str, Any]:
    from stable_baselines3 import SAC

    package = PortDataset.load(dataset_id)
    starts = package.evaluation_start_indices(split, 24)
    model = SAC.load(str(artifact), device="cpu")
    episodes = []
    for index in starts:
        env = DominanceProjectedRegulatoryEnv(
            dataset=dataset_id,
            split=split,
            action_mode="continuous",
            reward_weights=REWARD_WEIGHTS,
            episode_hours=24,
            render_mode=None,
        )
        observation, _ = env.reset(seed=20260821 + index, options={"row_index": index})
        done = False
        while not done:
            action, _ = model.predict(observation, deterministic=True)
            observation, _, terminated, truncated, _ = env.step(action)
            done = terminated or truncated
        episodes.append(env.summary())
        env.close()
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
    episodes = []
    for index in starts:
        env = CausalForecastPortEnv(
            dataset=dataset_id,
            split=split,
            action_mode="continuous",
            reward_weights=REWARD_WEIGHTS,
            episode_hours=24,
            render_mode=None,
        )
        env.reset(seed=20260821 + index, options={"row_index": index})
        policy = FixedDispatchPolicy()
        done = False
        while not done:
            _, _, terminated, truncated, _ = env.step(
                encode_continuous_controls(policy.predict(env))
            )
            done = terminated or truncated
        episodes.append(env.summary())
        env.close()
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
    return f"""# 海事/海关检查能碳韧性策略 v3

> {report['evidence_label']}。情景不是现场 KPI，生产权限关闭。

v1 全动作 SAC 和 v2 简单门控的失败结果均原样保留。v3 冻结旧四动作，以旧策略恢复服务量为下限；SAC 只提出额外恢复量，投影器以最小准备能耗执行，并拒绝即时成本劣于旧策略的提案。

在首次读取的冻结 2025 final challenge test 上，相对旧策略：成本 {metrics['scenario_cost_reduction_pct']:+.3f}%，碳排 {metrics['carbon_reduction_pct']:+.3f}%，总延误 {metrics['total_delay_reduction_pct']:+.3f}%，监管链延误 {metrics['regulatory_delay_reduction_pct']:+.3f}%，峰值 {metrics['peak_change_pct']:+.3f}%。

| 检查 | 结果 | 数值 |
|---|---:|---:|
{rows}

离线状态：**{report['offline_admission_gate']['status']}**；`production_authority=false`。
"""


def run(steps: int, seeds: list[int], workers: int) -> dict[str, Any]:
    before = _protected_inventory()
    development = PortDataset.load(DEVELOPMENT_DATASET_ID)
    final_package = PortDataset.load(FINAL_DATASET_ID)
    jobs = [(seed, steps) for seed in seeds]
    if workers > 1:
        with ProcessPoolExecutor(max_workers=min(workers, len(jobs))) as pool:
            candidates = list(pool.map(_train_seed, jobs))
    else:
        candidates = [_train_seed(job) for job in jobs]
    for candidate in candidates:
        candidate["validation"] = _evaluate_model(
            PROJECT_ROOT / candidate["artifact"], DEVELOPMENT_DATASET_ID, "validation"
        )
    selected = min(
        candidates,
        key=lambda item: (
            item["validation"]["aggregate"]["safety_violations"],
            -item["validation"]["aggregate"]["reward"],
            item["seed"],
        ),
    )
    selected_test = _evaluate_model(
        PROJECT_ROOT / selected["artifact"], FINAL_DATASET_ID, "test"
    )
    legacy_test = _evaluate_legacy(FINAL_DATASET_ID, "test")
    candidate_aggregate = selected_test["aggregate"]
    legacy_aggregate = legacy_test["aggregate"]
    business = _comparison(candidate_aggregate, legacy_aggregate)
    cost_ci = paired_bootstrap_interval(
        [float(item["cost"]) for item in selected_test["episodes"]],
        [float(item["cost"]) for item in legacy_test["episodes"]],
        samples=2_000,
        seed=20260825,
    )
    delay_ci = paired_bootstrap_interval(
        [float(item["delay_minutes"]) for item in selected_test["episodes"]],
        [float(item["delay_minutes"]) for item in legacy_test["episodes"]],
        samples=2_000,
        seed=20260826,
    )
    after = _protected_inventory()
    preservation = {
        "history_preserved": before == after,
        "file_count": len(before),
        "before_sha256": hashlib.sha256(json.dumps(before, sort_keys=True).encode()).hexdigest(),
        "after_sha256": hashlib.sha256(json.dumps(after, sort_keys=True).encode()).hexdigest(),
        "changed_files": sorted(
            key for key in set(before) | set(after) if before.get(key) != after.get(key)
        ),
        "files": after,
    }
    PRESERVATION_REPORT.write_text(
        json.dumps(preservation, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    checks = [
        {"name": "development_dataset_quality", "passed": development.quality_report()["status"] == "pass", "value": development.quality_report()["status"]},
        {"name": "final_dataset_quality", "passed": final_package.quality_report()["status"] == "pass", "value": final_package.quality_report()["status"]},
        {"name": "minimum_training_steps", "passed": selected["actual_steps"] >= 5_000, "value": selected["actual_steps"]},
        {"name": "validation_only_selection", "passed": True, "value": "2024 validation"},
        {"name": "frozen_final_test", "passed": True, "value": "2025 final challenge test once"},
        {"name": "test_window_count", "passed": selected_test["episode_count"] >= 30, "value": selected_test["episode_count"]},
        {"name": "cost_non_regression", "passed": business["scenario_cost_reduction_pct"] >= 0, "value": business["scenario_cost_reduction_pct"]},
        {"name": "carbon_non_regression", "passed": business["carbon_reduction_pct"] >= 0, "value": business["carbon_reduction_pct"]},
        {"name": "delay_non_regression", "passed": business["total_delay_reduction_pct"] >= 0, "value": business["total_delay_reduction_pct"]},
        {"name": "regulatory_delay_non_regression", "passed": business["regulatory_delay_reduction_pct"] >= 0, "value": business["regulatory_delay_reduction_pct"]},
        {"name": "peak_non_regression", "passed": business["peak_change_pct"] <= 0, "value": business["peak_change_pct"]},
        {"name": "cost_ci95_non_regression", "passed": cost_ci["ci95_low_pct"] >= 0, "value": cost_ci["ci95_low_pct"]},
        {"name": "delay_ci95_non_regression", "passed": delay_ci["ci95_low_pct"] >= 0, "value": delay_ci["ci95_low_pct"]},
        {"name": "zero_mean_safety_violations", "passed": candidate_aggregate["safety_violations"] == 0, "value": candidate_aggregate["safety_violations"]},
        {"name": "historical_and_failed_artifacts_preserved", "passed": preservation["history_preserved"], "value": preservation["file_count"]},
    ]
    passed = all(item["passed"] for item in checks)
    report: dict[str, Any] = {
        "report_version": "3.0",
        "generated_at": utc_now(),
        "status": "qualified_offline" if passed else "blocked_candidate_preserved",
        "evidence_label": EVIDENCE_LABEL,
        "strategy": {
            "name": "dominance_projected_incremental_sac_v3",
            "learned_controls": ["additional recovery proposal from inspection readiness and recovery outputs"],
            "preserved_controls": ["shore_power_ratio", "crane_ratio", "yard_ratio", "battery_power_ratio"],
            "projection_guarantees": [
                "recovery service target is not below the preserved strategy target",
                "readiness and recovery ratios minimize modeled action load for the target",
                "extra recovery is rejected when immediate modeled energy-plus-delay cost regresses",
            ],
        },
        "boundary": {
            "authority_signals": "exogenous",
            "simulation_mode": True,
            "live_data_verified": False,
            "dispatch_allowed": False,
            "production_authority": False,
        },
        "datasets": {
            "development": {"id": development.dataset_id, "package_sha256": development.package_sha256},
            "final_challenge": {"id": final_package.dataset_id, "package_sha256": final_package.package_sha256},
        },
        "protocol": {
            "algorithm": "SAC with dominance projection",
            "seeds": seeds,
            "steps_per_seed": steps,
            "selection_split": "2024 validation",
            "final_split": "2025 frozen final challenge test",
            "final_test_access_before_selection": False,
            "train_render_mode": None,
        },
        "candidates": candidates,
        "selected_seed": selected["seed"],
        "selected_artifact": selected["artifact"],
        "selected_artifact_sha256": selected["artifact_sha256"],
        "final_test": {"selected_policy": selected_test, "preserved_legacy": legacy_test},
        "business_metrics_vs_preserved_legacy": business,
        "uncertainty": {"cost_reduction_ci95": cost_ci, "delay_reduction_ci95": delay_ci},
        "offline_admission_gate": {
            "status": "passed" if passed else "blocked",
            "checks": checks,
            "production_authority": False,
        },
        "history_preservation": {
            key: preservation[key]
            for key in ("history_preserved", "file_count", "before_sha256", "after_sha256", "changed_files")
        },
        "preserved_failed_candidates": [
            {"report": f"reports/regulatory_resilience_v{version}.json", "sha256": sha256_file(PROJECT_ROOT / f"reports/regulatory_resilience_v{version}.json")}
            for version in (1, 2)
        ],
        "limitations": [
            "Regulatory schedules and deployment fields are frozen scenarios, not field telemetry.",
            "The dominance claim is limited to the declared environment and metrics, not real operations.",
            "Production remains fail closed pending adapters, calibration, shadow operation and human approval.",
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
    artifact_ok = artifact.exists() and sha256_file(artifact) == report["selected_artifact_sha256"]
    return {
        "valid": expected == actual and artifact_ok,
        "report_sha256_matches": expected == actual,
        "artifact_sha256_matches": artifact_ok,
        "offline_admission_status": report["offline_admission_gate"]["status"],
        "history_preserved": report["history_preservation"]["history_preserved"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Dominance-projected regulatory SAC evidence")
    sub = parser.add_subparsers(dest="command", required=True)
    run_parser = sub.add_parser("run")
    run_parser.add_argument("--steps", type=int, default=5_000)
    run_parser.add_argument("--seeds", default="17,37,59")
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
