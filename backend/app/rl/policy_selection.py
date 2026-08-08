from __future__ import annotations

import json

from app.rl.training import RUNS_DIR


def resolve_requested_strategy(
    strategy_id: str | None,
    *,
    minimum_steps: int = 5_000,
    require_verified: bool = True,
) -> str:
    requested = str(strategy_id or "auto:latest")
    if requested != "auto:latest":
        return requested
    for manifest_path in sorted(RUNS_DIR.glob("*/manifest.json"), reverse=True):
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            continue
        if manifest.get("status") not in {"completed", "stopped"}:
            continue
        if int(manifest.get("step") or 0) < minimum_steps:
            continue
        if not manifest.get("artifact_path") or not manifest.get("artifact_sha256"):
            continue
        if require_verified:
            verification_path = manifest_path.parent / "verification.json"
            try:
                verification = json.loads(verification_path.read_text(encoding="utf-8"))
            except (OSError, ValueError, TypeError):
                continue
            if verification.get("status") != "verified":
                continue
        return str(manifest["job_id"])
    return "auto:no-admitted-policy" if require_verified else requested
