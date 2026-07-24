import os
from pathlib import Path

from fastapi import APIRouter, Response
from fastapi.responses import PlainTextResponse

from app.core.config import settings
from app.core.observability import request_metrics
from app.rl.dataset import DEFAULT_DATASET_ID, PortDataset
from app.rl.training import RUNS_DIR

router = APIRouter(tags=["health"])


@router.get("/health")
def health_check() -> dict[str, str]:
    return {
        "status": "ok",
        "service": "energy-carbon-dispatch-cockpit",
        "version": "0.2.0",
        "mode": "offline_benchmark",
    }


@router.get("/health/live")
def liveness() -> dict[str, str]:
    return {"status": "ok", "check": "process_alive"}


@router.get("/health/ready")
def readiness(response: Response) -> dict[str, object]:
    checks: dict[str, dict[str, object]] = {}
    try:
        dataset = PortDataset.load(DEFAULT_DATASET_ID)
        quality = dataset.quality_report()
        checks["default_dataset"] = {
            "ok": quality["status"] == "pass",
            "quality_score": quality["score"],
            "package_sha256": dataset.package_sha256,
        }
    except Exception as exc:
        checks["default_dataset"] = {"ok": False, "error": str(exc)}
    run_directory = Path(RUNS_DIR)
    run_directory.mkdir(parents=True, exist_ok=True)
    checks["run_storage"] = {
        "ok": run_directory.is_dir() and os.access(run_directory, os.R_OK | os.W_OK | os.X_OK)
    }
    try:
        import stable_baselines3  # noqa: F401

        checks["rl_runtime"] = {"ok": True}
    except ImportError as exc:
        checks["rl_runtime"] = {"ok": False, "error": str(exc)}
    ready = all(bool(check["ok"]) for check in checks.values())
    if not ready:
        response.status_code = 503
    return {
        "status": "ready" if ready else "not_ready",
        "checks": checks,
        "auth_mode": settings.api_auth_mode,
        "production_dispatch_enabled": False,
    }


@router.get("/metrics", response_class=PlainTextResponse)
def metrics() -> str:
    return request_metrics.render_prometheus()
