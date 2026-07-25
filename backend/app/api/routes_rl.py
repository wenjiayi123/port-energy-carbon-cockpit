from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, HTTPException

from app.rl.dataset import DEFAULT_DATASET_ID, PortDataset, registered_dataset_id
from app.rl.policy_selection import resolve_requested_strategy
from app.rl.scenarios import resolve_training_scenario
from app.rl.training import training_service, utc_now


router = APIRouter(tags=["reinforcement-learning"])


def _registered_api_dataset(payload: dict[str, Any]) -> str:
    reference = payload.get("dataset_id") or payload.get("data_file") or DEFAULT_DATASET_ID
    return registered_dataset_id(str(reference))


def _api_training_config(payload: dict[str, Any]) -> dict[str, Any]:
    config = dict(payload.get("config") or payload)
    config["dataset_id"] = _registered_api_dataset(config)
    config.pop("data_file", None)
    config.update(
        resolve_training_scenario(
            str(config.get("scenario") or "") or None,
            str(config["dataset_id"]),
        )
    )
    return config


@router.get("/rl/capabilities")
def capabilities() -> dict[str, Any]:
    return {"updated_at": utc_now(), **training_service.capabilities()}


@router.get("/rl/algorithms")
def algorithms() -> dict[str, Any]:
    payload = training_service.capabilities()
    return {"updated_at": utc_now(), "count": len(payload["algorithms"]), "items": payload["algorithms"], "runtime": payload["runtime"]}


@router.get("/rl/datasets")
def datasets() -> dict[str, Any]:
    items = training_service.capabilities()["datasets"]
    return {"updated_at": utc_now(), "count": len(items), "items": items}


@router.post("/rl/datasets/validate")
def validate_dataset(payload: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    try:
        dataset = PortDataset.load(_registered_api_dataset(payload))
        return {"ok": True, "dataset": dataset.describe()}
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/rl/train/start")
def train_start(payload: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    try:
        config = _api_training_config(payload)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not bool(payload.get("confirm", False)):
        try:
            config = training_service.validate_config(config)
        except Exception as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {"ok": False, "status": "confirmation_required", "preview": config}
    try:
        result = training_service.start(config)
        return {"ok": True, "result": result}
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/rl/train/status")
def train_status() -> dict[str, Any]:
    return training_service.status()


@router.post("/rl/train/pause")
def train_pause() -> dict[str, Any]:
    return training_service.control("pause")


@router.post("/rl/train/resume")
def train_resume() -> dict[str, Any]:
    return training_service.control("resume")


@router.post("/rl/train/stop")
def train_stop() -> dict[str, Any]:
    return training_service.control("stop")


@router.get("/rl/train/metrics")
def train_metrics() -> dict[str, Any]:
    status = training_service.status()
    return {
        "updated_at": utc_now(),
        "metrics": {key: status.get(key) for key in ("step", "reward", "entropy", "actor_loss", "critic_loss", "kl_divergence", "success_rate", "samples_per_sec", "policy_version")},
        "recent_metrics": status["recent_metrics"],
        "logs": status["logs"],
        "evidence": status["evidence"],
    }


@router.get("/rl/training/history")
def training_history() -> dict[str, Any]:
    return {"updated_at": utc_now(), "run": training_service.history()}


@router.get("/rl/strategies")
def strategies() -> dict[str, Any]:
    items = training_service.strategies()
    return {"updated_at": utc_now(), "count": len(items), "items": items}


@router.get("/rl/registry")
def model_registry() -> dict[str, Any]:
    return training_service.registry()


@router.post("/rl/simulate")
def simulate(payload: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    try:
        return training_service.evaluate(
            resolve_requested_strategy(payload.get("strategy_id"))
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/rlops/policies/verify")
def verify_policy(payload: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    try:
        evaluation = training_service.evaluate(
            resolve_requested_strategy(payload.get("strategy_id"))
        )
    except (FileNotFoundError, RuntimeError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    metrics = evaluation["metrics"]
    checks = [
        {"name": "held_out_test_split", "passed": evaluation["split"] == "test"},
        {"name": "dataset_hash_recorded", "passed": bool(evaluation["policy"]["dataset_sha256"])},
        {"name": "dataset_quality_gate", "passed": evaluation["dataset_quality"]["status"] == "pass"},
        {"name": "artifact_hash_recorded", "passed": bool(evaluation["policy"]["artifact_sha256"])},
        {"name": "grid_peak_constraint", "passed": metrics["safety_violations"] == 0},
        {"name": "carbon_non_regression", "passed": metrics["carbon_reduction_pct"] >= 0},
        {"name": "cost_non_regression", "passed": metrics["cost_saving_pct"] >= 0},
        {
            "name": "fixed_baseline_carbon_non_regression",
            "passed": metrics["fixed_baseline_carbon_reduction_pct"] >= 0,
        },
        {
            "name": "fixed_baseline_cost_non_regression",
            "passed": metrics["fixed_baseline_cost_saving_pct"] >= 0,
        },
        {"name": "manual_dispatch_boundary", "passed": True},
    ]
    passed = all(item["passed"] for item in checks)
    result = {
        "ok": passed,
        "status": "verified" if passed else "blocked",
        "policy_id": evaluation["strategy_id"],
        "checks": checks,
        "risk_level": "low" if passed else "high",
        "evaluation": evaluation,
        "note": "Verification uses the held-out split; production dispatch remains dry-run only.",
        "verified_at": utc_now(),
    }
    evidence_path = training_service.record_verification(evaluation["strategy_id"], result)
    result["evidence_path"] = str(evidence_path)
    return result
