from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from app.rl import benchmark, landing_benchmark
from app.rl.dataset import PROJECT_ROOT
from app.rl.environment import (
    OBSERVATION_KEYS,
    OPERATIONAL_OBSERVATION_KEYS,
    PortEnergyDispatchEnv,
    observation_keys_for_environment,
)


DEFAULT_MANIFEST = PROJECT_ROOT / "reports" / "regulatory_v4_legacy_extension.json"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _legacy_contracts() -> dict[str, Any]:
    default_env = PortEnergyDispatchEnv(
        dataset="port_la_2020_2025_hourly",
        split="test",
        action_mode="continuous",
        episode_hours=1,
    )
    vessel_env = PortEnergyDispatchEnv(
        dataset="port_la_2020_2024_vessel_activity_hourly",
        split="test",
        action_mode="discrete",
        episode_hours=1,
    )
    return {
        "v1_observations": len(observation_keys_for_environment("PortEnergyDispatchEnv-v1")),
        "v2_observations": len(observation_keys_for_environment("PortEnergyDispatchEnv-v2")),
        "v3_observations": len(observation_keys_for_environment("PortEnergyDispatchEnv-v3")),
        "v1_continuous_actions": int(default_env.action_space.shape[0]),
        "v2_discrete_actions": int(vessel_env.action_space.n),
        "base_observation_keys": len(OBSERVATION_KEYS),
        "operational_observation_keys": len(OPERATIONAL_OBSERVATION_KEYS),
    }


def verify(report_path: Path, manifest_path: Path = DEFAULT_MANIFEST) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entry = manifest["protected_reports"].get(report_path.name)
    if entry is None:
        return {"status": "failed", "reason": "report_not_in_manifest"}

    if entry["verifier"] == "offline_benchmark":
        underlying = benchmark.verify_report(report_path)
        failed_checks = sorted(
            name for name, passed in underlying["checks"].items() if not passed
        )
    elif entry["verifier"] == "landing_benchmark":
        underlying = landing_benchmark.verify_report(report_path)
        failed_checks = sorted(
            name for name, passed in underlying["checks"].items() if not passed
        )
    else:
        return {"status": "failed", "reason": "unsupported_verifier"}

    current_code_hashes = {
        name: sha256_file(PROJECT_ROOT / name)
        for name in manifest["extended_code_sha256"]
    }
    checks = {
        "base_report_immutable": sha256_file(report_path) == entry["report_sha256"],
        "only_predeclared_source_hash_checks_changed": (
            failed_checks == sorted(entry["expected_failed_checks"])
        ),
        "extended_sources_pinned": (
            current_code_hashes == manifest["extended_code_sha256"]
        ),
        "legacy_executable_contracts": (
            _legacy_contracts() == manifest["legacy_executable_contracts"]
        ),
        "underlying_non_source_evidence_valid": all(
            passed
            for name, passed in underlying["checks"].items()
            if name not in entry["expected_failed_checks"]
        ),
    }
    return {
        "status": "verified_versioned_extension" if all(checks.values()) else "failed",
        "checks": checks,
        "underlying": underlying,
        "failed_checks_accepted_only_by_manifest": failed_checks,
        "report": str(report_path),
        "manifest": str(manifest_path),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("verify",))
    parser.add_argument("report", type=Path)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    args = parser.parse_args()
    result = verify(args.report, args.manifest)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["status"] == "verified_versioned_extension" else 1)


if __name__ == "__main__":
    main()
