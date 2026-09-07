"""Safe policy improvement relative to the strongest frozen validation control."""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
import json
from pathlib import Path

import numpy as np

from app.rl.dataset import PROJECT_ROOT, PortDataset
from app.rl.dispatch_policy_v7 import BOUNDARY, DATASET_ID, DispatchEnvV7, episode, objective
from app.rl.evaluate_dispatch_v7 import static_weights
from app.rl.evaluate_guarded_dispatch_v7 import CODE as PREVIOUS_CODE, MemoMPC
from app.rl.guarded_dispatch_v7 import GuardedDispatchPolicyV7
from app.rl.train_dispatch_v7 import compare, digest, means, write_json

CODE = (*PREVIOUS_CODE, "backend/app/rl/qualified_dispatch_v7.py")


class QualifiedDispatchPolicyV7(GuardedDispatchPolicyV7):
    def __init__(self, weights, reference_weights, controller=None):
        reference = GuardedDispatchPolicyV7(reference_weights, controller)
        super().__init__(weights, reference)


def _chunk(args):
    split, starts, specs, reference_weights = args
    env = DispatchEnvV7(dataset=DATASET_ID, split=split)
    results = {name: [] for name in specs}
    for start in starts:
        controller = MemoMPC()
        for name, weights in specs.items():
            if name == "causal_mpc":
                policy = controller
            elif name == "validation_selected_static":
                policy = GuardedDispatchPolicyV7(reference_weights, controller)
            else:
                policy = QualifiedDispatchPolicyV7(weights, reference_weights, controller)
            results[name].append(episode(env, policy, start))
    return results


def batch(split, starts, specs, reference_weights):
    chunks = [[int(i) for i in c] for c in np.array_split(starts, 4)]
    with ProcessPoolExecutor(max_workers=4) as pool:
        parts = list(pool.map(_chunk, [(split, c, specs, reference_weights) for c in chunks if c]))
    return {name: [r for part in parts for r in part[name]] for name in specs}


def evaluate(fits, outcomes, validation, selected_seed):
    seeds = []
    for fit in fits:
        name = f"seed-{fit['seed']}"
        comparisons = {k: compare(outcomes[name], outcomes[k]) for k in (
            "causal_mpc", "service_reference", "validation_selected_static",
        )}
        val_comparisons = {k: compare(validation[name], validation[k]) for k in comparisons}
        tail = [c["objective"] for c in fit["checkpoints"][-4:]]
        plateau = (max(tail) - min(tail)) / abs(float(np.mean(tail))) * 100
        converged = plateau <= 0.25
        admitted = converged and not any(c["failed_checks"] for c in (
            *comparisons.values(), *val_comparisons.values(),
        ))
        seeds.append({"seed": fit["seed"], "metrics": means(outcomes[name]), "comparisons": comparisons,
                      "validation_comparisons": val_comparisons, "converged": converged,
                      "validation_tail_range_pct": plateau, "admitted": admitted,
                      "policy_path": fit["policy_path"], "policy_sha256": fit["policy_sha256"]})
    return {"seed_results": seeds,
            "champion_status": "admitted_offline" if all(s["admitted"] for s in seeds) else "blocked",
            "champion": next(s for s in seeds if f"seed-{s['seed']}" == selected_seed)
            if all(s["admitted"] for s in seeds) else None}


def run(training_root: Path, reference_root: Path, root: Path):
    root.mkdir(parents=True, exist_ok=False)
    fits = json.loads((training_root / "training_results.json").read_text())
    dataset = PortDataset.load(DATASET_ID)
    selection = json.loads((reference_root / "static_validation_selection.json").read_text())
    reference_name = selection["selected"]
    reference_weights = static_weights(*[float(x) for x in reference_name.split('-')[1:]]).tolist()
    specs = {"causal_mpc": None, "validation_selected_static": reference_weights, "service_reference": None,
             **{f"seed-{f['seed']}": json.loads((PROJECT_ROOT / f["policy_path"]).read_text())["weights"] for f in fits}}
    starts = dataset.evaluation_start_indices("validation", 24)
    protocol = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "fit_split": "train", "selection_split": "validation", "test_split": "test",
        "training_results_path": str((training_root / "training_results.json").relative_to(PROJECT_ROOT)),
        "training_results_sha256": digest(training_root / "training_results.json"),
        "training_protocol_path": str((training_root / "protocol.json").relative_to(PROJECT_ROOT)),
        "training_protocol_sha256": digest(training_root / "protocol.json"),
        "reference_selection_path": str((reference_root / "static_validation_selection.json").relative_to(PROJECT_ROOT)),
        "reference_selection_sha256": digest(reference_root / "static_validation_selection.json"),
        "reference_static_weights": reference_weights,
        "code_sha256": {p: digest(PROJECT_ROOT / p) for p in CODE},
        "production_boundary": BOUNDARY,
        "admission_gate": "Unchanged: all three seeds must pass every business/CI check versus all three comparators and >=0.1 percent extra settled-cost improvement.",
    }
    write_json(root / "protocol.json", protocol)
    print(json.dumps({"phase": "qualified_validation", "windows": len(starts)}), flush=True)
    validation = batch("validation", starts, specs, reference_weights)
    write_json(root / "validation_episodes.json", validation)
    selected_seed = max((f"seed-{f['seed']}" for f in fits), key=lambda name: float(np.mean(
        [objective(r) for r in validation[name]],
    )))
    source_protocol = json.loads((reference_root / "protocol.json").read_text())
    test_starts = source_protocol["test_start_indices"]
    write_json(root / "selection.json", {"selected_seed": selected_seed, "test_accessed": False,
                                        "test_start_indices": test_starts,
                                        "additional_disjoint_windows": source_protocol["additional_disjoint_windows"]})
    print(json.dumps({"phase": "qualified_frozen_test", "windows": len(test_starts)}), flush=True)
    test = batch("test", test_starts, specs, reference_weights)
    write_json(root / "test_episodes.json", test)
    result = evaluate(fits, test, validation, selected_seed)
    report = {
        "schema_version": "dispatch-qualified-business-value.v7", **result,
        "execution_guard": "causal_mpc_and_validation_static_dominance.v2",
        "dataset_id": DATASET_ID, "dataset_package_sha256": dataset.package_sha256,
        "validation_selected_seed": int(selected_seed.split('-')[1]),
        "test_window_count": len(test_starts), "reference_static_weights": reference_weights,
        "baseline_metrics": {k: means(test[k]) for k in ("causal_mpc", "service_reference", "validation_selected_static")},
        "evidence_label": "OFFLINE_PUBLIC_ANCHOR_ENGINEERING_SCENARIO_NOT_FIELD_KPI",
        "production_boundary": BOUNDARY,
        "limitations": ["Public-anchor engineering scenarios, not field operating savings.",
                        "The test year was examined in earlier failed attempts; it is retrospective regression evidence.",
                        "48 additional disjoint windows expand coverage; independent site/year validation remains outstanding.",
                        "Strong control and deterministic business projections share credit; learned extra savings use equal-guard ablations."],
        "artifact_sha256": {str(p.relative_to(PROJECT_ROOT)): digest(p) for p in root.glob("*.json")},
        "code_sha256": {p: digest(PROJECT_ROOT / p) for p in CODE},
    }
    write_json(root / "business_value.json", report)
    print(json.dumps({"champion_status": result["champion_status"], "seeds": [
        {"seed": s["seed"], "admitted": s["admitted"],
         "failed_test": {k: c["failed_checks"] for k, c in s["comparisons"].items()},
         "failed_validation": {k: c["failed_checks"] for k, c in s["validation_comparisons"].items()}}
        for s in result["seed_results"]]}), flush=True)
    return report


def verify_report(path: Path):
    try:
        root = path.parent
        report = json.loads(path.read_text())
        protocol = json.loads((root / "protocol.json").read_text())
        selection = json.loads((root / "selection.json").read_text())
        training = json.loads((PROJECT_ROOT / protocol["training_protocol_path"]).read_text())
        fits = json.loads((PROJECT_ROOT / protocol["training_results_path"]).read_text())
        test = json.loads((root / "test_episodes.json").read_text())
        val = json.loads((root / "validation_episodes.json").read_text())
        selected = max((f"seed-{f['seed']}" for f in fits), key=lambda name: float(np.mean([objective(r) for r in val[name]])))
        recomputed = evaluate(fits, test, val, selected)
        ref_selection = json.loads((PROJECT_ROOT / protocol["reference_selection_path"]).read_text())
        ref_weights = static_weights(*[float(x) for x in ref_selection["selected"].split('-')[1:]]).tolist()
        required_artifacts = {str((root / name).relative_to(PROJECT_ROOT)) for name in (
            "protocol.json", "selection.json", "validation_episodes.json", "test_episodes.json",
        )}
        checks = {
            "schema": report["schema_version"] == "dispatch-qualified-business-value.v7",
            "dataset": report["dataset_package_sha256"] == PortDataset.load(DATASET_ID).package_sha256,
            "three_seeds": {s["seed"] for s in report["seed_results"]} == {17, 37, 59},
            "business_gates_recomputed": all(report[k] == value for k, value in recomputed.items()),
            "validation_selected_identity": selected == selection["selected_seed"] == f"seed-{report['validation_selected_seed']}",
            "selection_before_test": selection["test_accessed"] is False,
            "reference_contract": ref_weights == protocol["reference_static_weights"] == report["reference_static_weights"],
            "code": set(report["code_sha256"]) == set(CODE)
            and all(digest(PROJECT_ROOT / p) == h for p, h in report["code_sha256"].items()),
            "frozen_code": report["code_sha256"] == protocol["code_sha256"],
            "training_code": all(digest(PROJECT_ROOT / p) == h for p, h in training["code_sha256"].items()),
            "artifacts": set(report["artifact_sha256"]) == required_artifacts
            and all(digest(PROJECT_ROOT / p) == h for p, h in report["artifact_sha256"].items()),
            "parent_artifacts": all(digest(PROJECT_ROOT / protocol[f"{name}_path"]) == protocol[f"{name}_sha256"]
                                    for name in ("training_results", "training_protocol", "reference_selection")),
            "models": all(digest(PROJECT_ROOT / s["policy_path"]) == s["policy_sha256"] for s in report["seed_results"]),
            "paired_windows": all([r["start_index"] for r in rows] == selection["test_start_indices"] for rows in test.values())
            and report["test_window_count"] == len(selection["test_start_indices"]) == 96,
            "boundary": report["production_boundary"] == BOUNDARY,
        }
        return {"ok": all(checks.values()), "checks": checks}
    except (OSError, ValueError, KeyError, TypeError):
        return {"ok": False, "checks": {"complete_evidence": False}}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("training_root", type=Path)
    parser.add_argument("reference_root", type=Path, nargs="?")
    parser.add_argument("output", type=Path, nargs="?")
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    if args.verify:
        result = verify_report(args.training_root)
        print(json.dumps(result))
        raise SystemExit(0 if result["ok"] else 1)
    if args.reference_root is None or args.output is None:
        parser.error("reference_root and output are required")
    run(args.training_root.resolve(), args.reference_root.resolve(), args.output.resolve())
