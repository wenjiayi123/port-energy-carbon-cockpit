"""State-preserving policy replacement for the offline/shadow decision contract."""
from __future__ import annotations

import json
from pathlib import Path
import time
from typing import Any

import numpy as np

from app.rl.dataset import PROJECT_ROOT
from app.rl.dispatch_policy_v7 import BOUNDARY, FEATURES, OUTPUTS, DispatchEnvV7
from app.rl.environment import MPCPolicy
from app.rl.qualified_dispatch_v7 import QualifiedDispatchPolicyV7, verify_report
from app.rl.train_dispatch_v7 import digest

CURRENT = PROJECT_ROOT / "reports" / "dispatch_v7_current.json"


def _report_path(pointer: Path = CURRENT) -> Path:
    payload = json.loads(pointer.read_text())
    path = (PROJECT_ROOT / payload["report_path"]).resolve()
    if not path.is_relative_to((PROJECT_ROOT / "reports").resolve()):
        raise ValueError("Evidence must reside under reports")
    if digest(path) != payload["report_sha256"]:
        raise ValueError("Report hash mismatch")
    return path


def evidence(pointer: Path = CURRENT) -> dict[str, Any]:
    try:
        path = _report_path(pointer)
        verification = verify_report(path)
        report = json.loads(path.read_text())
        if not verification["ok"]:
            return {"available": False, "champion_status": "integrity_blocked",
                    "verification": verification, "production_boundary": BOUNDARY}
        return {"available": verification["ok"], "verification": verification,
                "report_path": str(path.relative_to(PROJECT_ROOT)),
                **{k: report[k] for k in (
                    "champion_status", "champion", "validation_selected_seed",
                    "seed_results", "test_window_count", "baseline_metrics", "limitations",
                    "evidence_label", "production_boundary",
                )}}
    except (OSError, ValueError, KeyError, TypeError):
        return {"available": False, "champion_status": "evidence_unavailable",
                "production_boundary": BOUNDARY}


class DispatchSwitcherV7:
    """Swap only the policy, never reset the environment or its liabilities.

Physical dispatch is absent from this adapter. A site-specific caller must
independently qualify its dataset and field cutover; dataset mismatch falls back.
"""

    def __init__(self, env: DispatchEnvV7, pointer: Path = CURRENT) -> None:
        self.env = env
        self.pointer = pointer
        self.policy = MPCPolicy()
        self.mode = "causal_mpc"
        self.policy_path: Path | None = None
        self.policy_sha: str | None = None
        self.switch_receipts: list[dict[str, Any]] = []

    def switch(self, mode: str) -> dict[str, Any]:
        if mode not in {"causal_mpc", "learned_v7"}:
            raise ValueError("Unknown policy mode")
        before = self.env.summary()
        reason = "requested"
        if mode == "learned_v7":
            try:
                path = _report_path(self.pointer)
                if not verify_report(path)["ok"]:
                    raise ValueError("Evidence verification failed")
                report = json.loads(path.read_text())
                if report["champion_status"] != "admitted_offline":
                    raise ValueError("Policy has not passed admission")
                if report["dataset_package_sha256"] != self.env.dataset.package_sha256:
                    raise ValueError("Dataset requires site-specific retraining and validation")
                champion = report["champion"]
                artifact = (PROJECT_ROOT / champion["policy_path"]).resolve()
                if not artifact.is_relative_to((PROJECT_ROOT / "reports").resolve()):
                    raise ValueError("Policy path outside evidence directory")
                if digest(artifact) != champion["policy_sha256"]:
                    raise ValueError("Policy hash mismatch")
                payload = json.loads(artifact.read_text())
                if payload["features"] != list(FEATURES) or payload["outputs"] != list(OUTPUTS):
                    raise ValueError("Policy contract mismatch")
                self.policy = QualifiedDispatchPolicyV7(
                    np.array(payload["weights"]), np.array(report["reference_static_weights"]),
                )
                self.policy_path, self.policy_sha = artifact, champion["policy_sha256"]
            except (OSError, ValueError, TypeError, KeyError):
                mode, reason = "causal_mpc", "admission_or_integrity_blocked"
        if mode == "causal_mpc":
            self.policy = MPCPolicy()
            self.policy_path = None
            self.policy_sha = None
        previous = self.mode
        self.mode = mode
        receipt = {"from": previous, "to": mode, "reason": reason,
                   "hour": self.env._hour, "state_preserved": self.env.summary() == before,
                   "policy_sha256": self.policy_sha, "production_boundary": BOUNDARY}
        self.switch_receipts.append(receipt)
        return receipt

    def step(self) -> dict[str, Any]:
        if self.env._hour >= self.env.episode_hours:
            raise ValueError("Replay has completed")
        if self.policy_path is not None:
            try:
                valid = digest(self.policy_path) == self.policy_sha
            except OSError:
                valid = False
            if not valid:
                self.switch("causal_mpc")
                self.switch_receipts[-1]["reason"] = "runtime_artifact_integrity_failure"
        started = time.perf_counter()
        before_soc = self.env._battery_soc
        action = self.policy.predict(self.env)
        _, _, terminated, _, info = self.env.step(action)
        return {"mode": self.mode, "hour": self.env._hour, "completed": terminated,
                "decision_latency_ms": (time.perf_counter() - started) * 1000.0,
                "controls": action, "battery_soc_before": before_soc,
                "battery_soc_after": self.env._battery_soc,
                "cost": info["cost"], "carbon_kg": info["carbon_kg"],
                "processed_teu": info["processed_teu"], "safety_violations": info["safety_violations"],
                "decision_receipt": getattr(self.policy, "last_receipt", {}), "production_boundary": BOUNDARY}


def replay_switches(start_index: int = 0, pointer: Path = CURRENT) -> dict[str, Any]:
    from app.rl.dispatch_policy_v7 import DATASET_ID

    env = DispatchEnvV7(dataset=DATASET_ID, split="test", episode_hours=72)
    if not 0 <= start_index <= len(env.frame) - 72:
        raise ValueError("Replay start is outside the test split")
    env.reset(seed=20260907, options={"row_index": start_index})
    switcher = DispatchSwitcherV7(env, pointer)
    decisions = []
    for hour in range(72):
        if hour == 12:
            switcher.switch("learned_v7")
        elif hour == 48:
            switcher.switch("causal_mpc")
        decisions.append(switcher.step())
    passed = (
        all(r["state_preserved"] for r in switcher.switch_receipts)
        and switcher.switch_receipts[0]["to"] == "learned_v7"
        and switcher.switch_receipts[1]["to"] == "causal_mpc"
        and env.summary()["safety_violations"] == 0
    )
    return {"status": "passed" if passed else "blocked", "steps": 72,
            "decision_latency_ms": {"p50": float(np.percentile([d["decision_latency_ms"] for d in decisions], 50)),
                                    "p95": float(np.percentile([d["decision_latency_ms"] for d in decisions], 95))},
            "switch_receipts": switcher.switch_receipts, "decisions": decisions,
            "summary": env.summary(), "production_boundary": BOUNDARY}


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    parser.add_argument("--start-index", type=int, default=0)
    args = parser.parse_args()
    if args.output and args.output.exists():
        parser.error("Refusing to overwrite an existing acceptance receipt")
    result = replay_switches(args.start_index)
    if args.output:
        result["switch_code_sha256"] = digest(Path(__file__))
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({k: v for k, v in result.items() if k != "decisions"}, ensure_ascii=False))
    raise SystemExit(0 if result["status"] == "passed" else 1)
