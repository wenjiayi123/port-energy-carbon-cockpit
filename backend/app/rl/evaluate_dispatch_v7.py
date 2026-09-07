"""Frozen evaluation, attribution, and artifact verification for dispatch v7."""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

import numpy as np

from app.rl.dataset import PROJECT_ROOT, PortDataset
from app.rl.dispatch_policy_v7 import (
    BOUNDARY, DATASET_ID, SHAPE, DispatchEnvV7, DispatchPolicyV7, episode, objective,
)
from app.rl.environment import MPCPolicy
from app.rl.train_dispatch_v7 import compare, digest, means, write_json


def _batch(args: tuple[str, list[int], list[list[float]] | None, str]) -> list[dict[str, Any]]:
    mode, starts, weights, split = args
    env = DispatchEnvV7(dataset=DATASET_ID, split=split)
    policy = MPCPolicy() if mode == "mpc" else DispatchPolicyV7(
        None if weights is None else np.array(weights),
    )
    return [episode(env, policy, start) for start in starts]


def evaluate(mode: str, starts: list[int], weights=None, split="test"):
    chunks = [[int(i) for i in c] for c in np.array_split(starts, min(4, len(starts)))]
    with ProcessPoolExecutor(max_workers=len(chunks)) as pool:
        return [r for batch in pool.map(_batch, [(mode, c, weights, split) for c in chunks])
                for r in batch]


def static_weights(ratio: float, inspection: float) -> np.ndarray:
    weights = np.zeros(SHAPE)
    weights[0:2, 0] = np.arctanh(np.clip((ratio - 1.0) / 0.4, -0.9999, 0.0))
    weights[2:4, 0] = np.arctanh(np.clip(inspection - 1.0, -0.9999, 0.0))
    return weights


def _static_fit(args: tuple[float, float, list[int]]) -> dict[str, Any]:
    ratio, inspection, starts = args
    weights = static_weights(ratio, inspection)
    results = _batch(("policy", starts, weights.tolist(), "validation"))
    return {"resource_ratio": ratio, "inspection_ratio": inspection,
            "weights": weights.tolist(), "objective": float(np.mean([objective(r) for r in results])),
            "mean": means(results)}


def verify_report(path: Path) -> dict[str, Any]:
    try:
        report = json.loads(path.read_text())
        protocol_path = PROJECT_ROOT / report["protocol_path"]
        protocol = json.loads(protocol_path.read_text())
        files = report["artifact_sha256"]
        checks = {
            "schema": report["schema_version"] == "dispatch-business-value.v7",
            "dataset": report["dataset_package_sha256"] == PortDataset.load(DATASET_ID).package_sha256,
            "protocol": digest(protocol_path) == report["protocol_sha256"],
            "code": all(digest(PROJECT_ROOT / p) == sha for p, sha in report["code_sha256"].items()),
            "artifacts": bool(files) and all(digest(PROJECT_ROOT / p) == sha for p, sha in files.items()),
            "three_seeds": {r["seed"] for r in report["seed_results"]} == {17, 37, 59},
            "selection_before_test": report["all_policies_frozen_before_test"] is True,
            "boundary": report["production_boundary"] == BOUNDARY,
            "frozen_training_code": all(digest(PROJECT_ROOT / p) == sha
                                        for p, sha in protocol["code_sha256"].items()),
        }
        admitted = all(r["admitted"] for r in report["seed_results"])
        checks["champion_consistency"] = (
            admitted == (report["champion_status"] == "admitted_offline")
            and bool(report.get("champion")) == admitted
        )
        expected_code = {
            "backend/app/rl/dispatch_policy_v7.py", "backend/app/rl/train_dispatch_v7.py",
            "backend/app/rl/evaluate_dispatch_v7.py", "backend/app/rl/environment.py",
            "backend/app/rl/robust.py", "backend/app/rl/hybrid_control.py",
        }
        checks["complete_code_contract"] = set(report["code_sha256"]) == expected_code
        root = path.parent
        comparisons = {
            "service_reference": json.loads((root / "test_service_reference.json").read_text()),
            "validation_selected_static": json.loads((root / "test_static_reference.json").read_text()),
            "causal_mpc": json.loads((root / "test_mpc_reference.json").read_text()),
        }
        fits = json.loads((root / "training_results.json").read_text())
        recomputed = []
        for result in report["seed_results"]:
            outcomes = json.loads((root / f"seed-{result['seed']}" / "test_episodes.json").read_text())
            evidence = {k: compare(outcomes, v) for k, v in comparisons.items()}
            fit = next(f for f in fits if f["seed"] == result["seed"])
            converged = fit["validation_tail_range_pct"] <= 0.25
            passed = converged and not any(c["failed_checks"] for c in evidence.values())
            recomputed.append(
                evidence == result["comparisons"] and passed == result["admitted"]
                and means(outcomes) == result["metrics"]
                and digest(PROJECT_ROOT / result["policy_path"]) == result["policy_sha256"]
            )
        checks["recomputed_business_gates"] = all(recomputed)
        checks["validation_selected_identity"] = report["validation_selected_seed"] == max(
            fits, key=lambda r: r["selected"]["objective"],
        )["seed"]
        return {"ok": all(checks.values()), "checks": checks}
    except (KeyError, OSError, ValueError, TypeError):
        return {"ok": False, "checks": {"readable_complete_evidence": False}}


def run(root: Path) -> dict[str, Any]:
    output = root / "business_value.json"
    if output.exists():
        raise ValueError("Refusing to overwrite frozen evaluation")
    fits = json.loads((root / "training_results.json").read_text())
    policies = [json.loads((PROJECT_ROOT / r["policy_path"]).read_text()) for r in fits]
    dataset = PortDataset.load(DATASET_ID)
    val_starts = dataset.evaluation_start_indices("validation", 24)
    # Fit the non-learning ablation on validation before touching test metrics.
    with ProcessPoolExecutor(max_workers=4) as pool:
        static_search = list(pool.map(_static_fit, [(r, i, val_starts)
                              for r in (0.6, 0.7, 0.8, 0.9, 1.0) for i in (0.5, 1.0)]))
    static = max(static_search, key=lambda r: r["objective"])
    write_json(root / "static_validation_selection.json", {"selected": static, "search": static_search})
    published = dataset.evaluation_start_indices("test", 24)
    occupied = {h for start in published for h in range(start, start + 24)}
    additional = [i for i in range(0, len(dataset.split("test")) - 24, 24)
                  if all(h not in occupied for h in range(i, i + 24))]
    additional = [additional[int(i)] for i in np.linspace(0, len(additional) - 1, 48)]
    starts = sorted(published + additional)
    write_json(root / "evaluation_protocol.json", {
        "frozen_at": datetime.now(timezone.utc).isoformat(),
        "published_regression_windows": published, "additional_disjoint_windows": additional,
        "all_policy_hashes": [r["policy_sha256"] for r in fits],
        "static_weights": static["weights"], "test_accessed": False,
    })
    print(json.dumps({"phase": "frozen_test", "windows": len(starts)}), flush=True)
    reference = evaluate("policy", starts)
    write_json(root / "test_service_reference.json", reference)
    static_test = evaluate("policy", starts, static["weights"])
    write_json(root / "test_static_reference.json", static_test)
    print(json.dumps({"phase": "causal_mpc_replay", "windows": len(starts)}), flush=True)
    mpc = evaluate("mpc", starts)
    write_json(root / "test_mpc_reference.json", mpc)
    seed_results = []
    for fit, policy in zip(fits, policies, strict=True):
        results = evaluate("policy", starts, policy["weights"])
        write_json(root / f"seed-{fit['seed']}" / "test_episodes.json", results)
        comparisons = {"service_reference": compare(results, reference),
                       "validation_selected_static": compare(results, static_test),
                       "causal_mpc": compare(results, mpc)}
        passed = not any(c["failed_checks"] for c in comparisons.values())
        converged = fit["convergence_status"] == "validation_plateau"
        seed_results.append({
            "seed": fit["seed"], "metrics": means(results), "comparisons": comparisons,
            "converged": converged, "validation_tail_range_pct": fit["validation_tail_range_pct"],
            "admitted": passed and converged, "policy_path": fit["policy_path"],
            "policy_sha256": fit["policy_sha256"],
        })
        print(json.dumps({"phase": "seed_evaluated", "seed": fit["seed"], "admitted": passed and converged,
                          "failed": {k: c["failed_checks"] for k, c in comparisons.items()}}), flush=True)
    # Champion identity is chosen on validation only, never by test return.
    selected_fit = max(fits, key=lambda r: r["selected"]["objective"])
    champion = next(r for r in seed_results if r["seed"] == selected_fit["seed"])
    admitted = all(r["admitted"] for r in seed_results)
    report = {
        "schema_version": "dispatch-business-value.v7",
        "evidence_label": "OFFLINE_PUBLIC_ANCHOR_ENGINEERING_SCENARIO_NOT_FIELD_KPI",
        "algorithm": "CEM episodic policy-search RL; 55 learned coefficients; no neural dependency",
        "dataset_id": DATASET_ID, "dataset_package_sha256": dataset.package_sha256,
        "protocol_path": str((root / "protocol.json").relative_to(PROJECT_ROOT)),
        "protocol_sha256": digest(root / "protocol.json"),
        "all_policies_frozen_before_test": True,
        "test_window_count": len(starts), "test_start_indices": starts,
        "additional_disjoint_windows": additional,
        "baseline_metrics": {"service_reference": means(reference),
                             "validation_selected_static": means(static_test), "causal_mpc": means(mpc)},
        "seed_results": seed_results,
        "champion_status": "admitted_offline" if admitted else "blocked",
        "champion": champion if admitted else None,
        "validation_selected_seed": selected_fit["seed"],
        "production_boundary": BOUNDARY,
        "limitations": [
            "Public anchors and engineering scenarios; no measured port savings.",
            "2024 was previously used by v6; disjoint windows add coverage, not an independent port/year.",
            "Full-site mappings, calibration, shadow validation and independent physical interlocks remain required.",
            "Solver improvements and learned incremental savings are reported against separate ablations.",
        ],
        "code_sha256": {name: digest(PROJECT_ROOT / name) for name in (
            "backend/app/rl/dispatch_policy_v7.py", "backend/app/rl/train_dispatch_v7.py",
            "backend/app/rl/evaluate_dispatch_v7.py", "backend/app/rl/environment.py",
            "backend/app/rl/robust.py", "backend/app/rl/hybrid_control.py",
        )},
        "artifact_sha256": {str(p.relative_to(PROJECT_ROOT)): digest(p)
                            for p in sorted(root.rglob("*.json"))},
    }
    write_json(output, report)
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    if args.verify:
        result = verify_report(args.root)
        print(json.dumps(result))
        raise SystemExit(0 if result["ok"] else 1)
    report = run(args.root.resolve())
    print(json.dumps({"champion_status": report["champion_status"]}))


if __name__ == "__main__":
    main()
