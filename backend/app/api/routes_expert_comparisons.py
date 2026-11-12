"""Explicit-parameter, versioned comparison facts for the new agent environment."""

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from app.api.routes_agent_comparisons import owner
from app.services.agent_comparisons import ComparisonConflict
from app.services.expert_comparisons import ExpertComparisonStore, source_context

router = APIRouter(prefix="/optimization/expert-comparisons", tags=["expert-comparison"])


class ExpertComparisonRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, strict=True)
    request_id: str = Field(pattern=r"^[A-Za-z0-9_-]{8,100}$")
    baseline_green_preference: float = Field(ge=0, le=1)
    green_preference: float = Field(ge=0, le=1)
    carbon_price_cny_per_ton: float = Field(ge=0, le=5000)
    expected_source_version: str = Field(pattern=r"^[a-f0-9]{64}$")


@router.get("/source-context")
def context(request: Request):
    owner(request)
    return source_context()


@router.post("")
def compare(payload: ExpertComparisonRequest, request: Request):
    try:
        return ExpertComparisonStore().compare(owner(request), payload.model_dump())
    except ComparisonConflict as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/{request_id}")
def read_receipt(request_id: str, request: Request):
    receipt = ExpertComparisonStore().get(owner(request), request_id)
    if receipt is None:
        raise HTTPException(404, "no completed receipt for this owner and request")
    return {"receipt": receipt, "source_context_now": source_context(), "readback_only": True}
