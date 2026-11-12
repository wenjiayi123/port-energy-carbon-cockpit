"""Explicit opt-in Shanghai evaluation, independent of the existing live demo state."""
from fastapi import APIRouter, HTTPException
from app.services.shanghai_lab_v1.protocol import inputs, unpack
from app.services.shanghai_lab_v1.energy import evaluate as evaluate_storage

router = APIRouter(prefix="/shanghai-lab/v1", tags=["Shanghai-public-lab"])


@router.get("/health")
def health():
    return {"schema": "shanghai-adapter.v1", "system": "energy-cockpit", "production_authority": False}


@router.post("/evaluate")
def evaluate(payload: dict):
    try:
        case = inputs(payload)
        plan = unpack(payload, "plan")
        result = evaluate_storage(case, plan)
        result["historical_policy_preserved"] = True
        return result
    except (ValueError, KeyError, TypeError) as exc:
        raise HTTPException(422, str(exc)) from exc
