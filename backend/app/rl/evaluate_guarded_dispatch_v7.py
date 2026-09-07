"""Equal-guard ablation and frozen business admission for the v7 bundle."""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
import json
from pathlib import Path

import numpy as np

from app.rl.dataset import PROJECT_ROOT, PortDataset
from app.rl.dispatch_policy_v7 import BOUNDARY, DATASET_ID, DispatchEnvV7, episode, objective
from app.rl.environment import MPCPolicy
from app.rl.evaluate_dispatch_v7 import static_weights
from app.rl.guarded_dispatch_v7 import GuardedDispatchPolicyV7
from app.rl.train_dispatch_v7 import compare, digest, means, write_json

CODE = (
    "backend/app/rl/dispatch_policy_v7.py", "backend/app/rl/train_dispatch_v7.py",
    "backend/app/rl/refine_dispatch_v7.py", "backend/app/rl/guarded_dispatch_v7.py",
    "backend/app/rl/evaluate_guarded_dispatch_v7.py", "backend/app/rl/evaluate_dispatch_v7.py",
    "backend/app/rl/environment.py", "backend/app/rl/robust.py", "backend/app/rl/hybrid_control.py",
)


class MemoMPC:
    """Exact memoization of the complete state read by the MPC transition model."""
    def __init__(self):
        self.cache = {}
        self.controller = MPCPolicy()

    def predict(self, env):
        key = (
            env.dataset.package_sha256, env.split_name, env.episode_hours,
            env._row_index, env._hour, env._queue_teu, env._battery_soc,
            env._maritime_hold_teu, env._customs_hold_teu, env._released_recovery_teu,
            env._reefer_thermal_debt, env._maintenance_debt, env._totals.get("peak_kw", 0),
            env.demand_multiplier, tuple(sorted(env.parameter_multipliers.items())),
        )
        if key not in self.cache:
            self.cache[key] = self.controller.predict(env)
        return dict(self.cache[key])


def _chunk(args):
    split, starts, specs = args
    env = DispatchEnvV7(dataset=DATASET_ID, split=split)
    results = {name: [] for name in specs}
    for start in starts:
        controller = MemoMPC()
        for name, weights in specs.items():
            policy = controller if name == "causal_mpc" else GuardedDispatchPolicyV7(weights, controller)
            results[name].append(episode(env, policy, start))
    return results


def batch(split, starts, specs):
    chunks = [[int(i) for i in c] for c in np.array_split(starts, 4)]
    with ProcessPoolExecutor(max_workers=4) as pool:
        parts = list(pool.map(_chunk, [(split, c, specs) for c in chunks if c]))
    return {name: [r for p in parts for r in p[name]] for name in specs}


def run(training_root: Path, root: Path):
    root.mkdir(parents=True, exist_ok=False)
    fits = json.loads((training_root / "training_results.json").read_text())
    dataset = PortDataset.load(DATASET_ID)
    policies = {f"seed-{r['seed']}": json.loads((PROJECT_ROOT / r["policy_path"]).read_text())["weights"]
                for r in fits}
    static_specs = {f"static-{r}-{i}": static_weights(r, i).tolist()
                    for r in (0.6, 0.7, 0.8, 0.9, 1.0) for i in (0.5, 1.0)}
    validation_starts = dataset.evaluation_start_indices("validation", 24)
    search_starts = [validation_starts[int(i)] for i in np.linspace(0, 47, 12)]
    print(json.dumps({"phase": "guarded_static_selection", "validation_windows": 12}), flush=True)
    search = batch("validation", search_starts, {"causal_mpc": None, **static_specs})
    scores = {name: float(np.mean([objective(r) for r in rows])) for name, rows in search.items()
              if name != "causal_mpc"}
    static_name = max(scores, key=scores.get)
    write_json(root / "static_validation_selection.json", {
        "selected": static_name, "objectives": scores, "episodes": search,
        "selection_start_indices": search_starts, "test_accessed": False,
    })
    specs = {"causal_mpc": None, "service_reference": None,
             "validation_selected_static": static_specs[static_name], **policies}
    print(json.dumps({"phase": "guarded_validation", "windows": 48}), flush=True)
    validation = batch("validation", validation_starts, specs)
    write_json(root / "validation_episodes.json", validation)
    selected_seed = max(policies, key=lambda name: float(np.mean([objective(r) for r in validation[name]])))
    published = dataset.evaluation_start_indices("test", 24)
    occupied = {h for start in published for h in range(start, start + 24)}
    additional = [i for i in range(0, len(dataset.split("test")) - 24, 24)
                  if all(h not in occupied for h in range(i, i + 24))]
    additional = [additional[int(i)] for i in np.linspace(0, len(additional) - 1, 48)]
    test_starts = sorted(published + additional)
    write_json(root / "protocol.json", {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "training_results_path": str((training_root / "training_results.json").relative_to(PROJECT_ROOT)),
        "training_results_sha256": digest(training_root / "training_results.json"),
        "training_protocol_path": str((training_root / "protocol.json").relative_to(PROJECT_ROOT)),
        "training_protocol_sha256": digest(training_root / "protocol.json"),
        "fit_split": "train", "selection_split": "validation", "test_split": "test",
        "selected_seed": selected_seed, "static_selected": static_name,
        "policy_sha256": {r["policy_path"]: r["policy_sha256"] for r in fits},
        "test_start_indices": test_starts, "additional_disjoint_windows": additional,
        "selection_before_test": True,
        "gate": "All three seeds: all non-regression checks, cost/carbon CI, >=0.1 percent incremental cost saving against each comparator, and validation convergence.",
        "code_sha256": {p: digest(PROJECT_ROOT / p) for p in CODE},
        "production_boundary": BOUNDARY,
    })
    print(json.dumps({"phase": "guarded_frozen_test", "windows": 96}), flush=True)
    test = batch("test", test_starts, specs)
    write_json(root / "test_episodes.json", test)
    seeds = []
    for fit in fits:
        name = f"seed-{fit['seed']}"
        comparisons = {k: compare(test[name], test[k]) for k in (
            "causal_mpc", "service_reference", "validation_selected_static",
        )}
        validation_comparisons = {k: compare(validation[name], validation[k]) for k in comparisons}
        converged = fit["convergence_status"] == "validation_plateau"
        admitted = converged and not any(c["failed_checks"] for c in (
            *comparisons.values(), *validation_comparisons.values(),
        ))
        seeds.append({"seed": fit["seed"], "metrics": means(test[name]), "comparisons": comparisons,
                      "validation_comparisons": validation_comparisons,
                      "converged": converged, "validation_tail_range_pct": fit["validation_tail_range_pct"],
                      "admitted": admitted, "policy_path": fit["policy_path"],
                      "policy_sha256": fit["policy_sha256"]})
        print(json.dumps({"seed": fit["seed"], "admitted": admitted,
                          "failed_test": {k: c["failed_checks"] for k, c in comparisons.items()},
                          "failed_validation": {k: c["failed_checks"] for k, c in validation_comparisons.items()}}), flush=True)
    admitted = all(s["admitted"] for s in seeds)
    report = {
        "schema_version": "dispatch-guarded-business-value.v7", "execution_guard": "causal_mpc_dominance.v1",
        "dataset_id": DATASET_ID, "dataset_package_sha256": dataset.package_sha256,
        "champion_status": "admitted_offline" if admitted else "blocked",
        "champion": next(s for s in seeds if f"seed-{s['seed']}" == selected_seed) if admitted else None,
        "validation_selected_seed": int(selected_seed.split('-')[1]), "seed_results": seeds,
        "test_window_count": len(test_starts),
        "baseline_metrics": {k: means(test[k]) for k in ("causal_mpc", "service_reference", "validation_selected_static")},
        "evidence_label": "OFFLINE_PUBLIC_ANCHOR_ENGINEERING_SCENARIO_NOT_FIELD_KPI",
        "production_boundary": BOUNDARY,
        "limitations": ["Public-anchor engineering scenarios, not measured port savings.",
                        "2024 is a retrospective regression year; 48 disjoint windows add coverage, not a new port/year.",
                        "Physical site cutover requires calibrated source mappings and independent acceptance.",
                        "CEM learns five resource decisions; MPC and deterministic priority projection share credit for business gains."],
        "artifact_sha256": {str(p.relative_to(PROJECT_ROOT)): digest(p) for p in root.glob("*.json")},
        "code_sha256": {p: digest(PROJECT_ROOT / p) for p in CODE},
    }
    write_json(root / "business_value.json", report)
    return report


def verify_report(path: Path):
    try:
        report = json.loads(path.read_text())
        root = path.parent
        protocol = json.loads((root / "protocol.json").read_text())
        train_protocol = json.loads((PROJECT_ROOT / protocol["training_protocol_path"]).read_text())
        fits = json.loads((PROJECT_ROOT / protocol["training_results_path"]).read_text())
        test = json.loads((root / "test_episodes.json").read_text())
        validation = json.loads((root / "validation_episodes.json").read_text())
        checks = {
            "schema": report["schema_version"] == "dispatch-guarded-business-value.v7",
            "dataset": report["dataset_package_sha256"] == PortDataset.load(DATASET_ID).package_sha256,
            "code": set(report["code_sha256"]) == set(CODE)
            and all(digest(PROJECT_ROOT / p) == h for p, h in report["code_sha256"].items()),
            "training_code": all(digest(PROJECT_ROOT / p) == h for p, h in train_protocol["code_sha256"].items()),
            "artifacts": all(digest(PROJECT_ROOT / p) == h for p, h in report["artifact_sha256"].items()),
            "training_results": digest(PROJECT_ROOT / protocol["training_results_path"]) == protocol["training_results_sha256"],
            "training_protocol": digest(PROJECT_ROOT / protocol["training_protocol_path"]) == protocol["training_protocol_sha256"],
            "three_seeds": {s["seed"] for s in report["seed_results"]} == {17, 37, 59},
            "boundary": report["production_boundary"] == BOUNDARY,
        }
        required_artifacts = {str((root / name).relative_to(PROJECT_ROOT)) for name in (
            "protocol.json", "static_validation_selection.json", "validation_episodes.json", "test_episodes.json",
        )}
        checks["complete_artifact_contract"] = set(report["artifact_sha256"]) == required_artifacts
        checks["frozen_protocol_code"] = protocol["code_sha256"] == report["code_sha256"]
        checks["paired_test_windows"] = all(
            [r["start_index"] for r in rows] == protocol["test_start_indices"] for rows in test.values()
        ) and len(protocol["test_start_indices"]) == report["test_window_count"] == 96
        recomputed = []
        for result in report["seed_results"]:
            name = f"seed-{result['seed']}"
            fit = next(f for f in fits if f["seed"] == result["seed"])
            comparisons = {k: compare(test[name], test[k]) for k in ("causal_mpc", "service_reference", "validation_selected_static")}
            val_comparisons = {k: compare(validation[name], validation[k]) for k in comparisons}
            tail = [c["objective"] for c in fit["checkpoints"][-4:]]
            plateau = (max(tail) - min(tail)) / abs(float(np.mean(tail))) * 100
            converged = plateau <= 0.25
            passed = converged and not any(c["failed_checks"] for c in (*comparisons.values(), *val_comparisons.values()))
            recomputed.append(result["admitted"] == passed and result["comparisons"] == comparisons
                              and result["validation_comparisons"] == val_comparisons
                              and result["metrics"] == means(test[name])
                              and abs(plateau - result["validation_tail_range_pct"]) < 1e-10
                              and digest(PROJECT_ROOT / result["policy_path"]) == result["policy_sha256"])
        checks["business_gates_recomputed"] = all(recomputed)
        admitted = all(s["admitted"] for s in report["seed_results"])
        checks["champion_consistency"] = (admitted == (report["champion_status"] == "admitted_offline")
                                          and bool(report["champion"]) == admitted)
        selected = max((f"seed-{f['seed']}" for f in fits), key=lambda name: float(np.mean(
            [objective(r) for r in validation[name]],
        )))
        checks["validation_selected_identity"] = (
            selected == protocol["selected_seed"] == f"seed-{report['validation_selected_seed']}"
            and (not admitted or report["champion"] == next(s for s in report["seed_results"]
                                                           if f"seed-{s['seed']}" == selected))
        )
        return {"ok": all(checks.values()), "checks": checks}
    except (OSError, ValueError, KeyError, TypeError):
        return {"ok": False, "checks": {"complete_evidence": False}}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("training_root", type=Path)
    parser.add_argument("output", type=Path, nargs="?")
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    if args.verify:
        result = verify_report(args.training_root)
        print(json.dumps(result))
        raise SystemExit(0 if result["ok"] else 1)
    if args.output is None:
        parser.error("output is required")
    report = run(args.training_root.resolve(), args.output.resolve())
    print(json.dumps({"champion_status": report["champion_status"]}))


if __name__ == "__main__":
    main()
