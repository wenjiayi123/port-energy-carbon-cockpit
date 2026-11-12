"""Version-checked, idempotent calculation receipts for agent recovery."""

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from app.services.agent_comparisons import (
    ComparisonConflict,
    ComparisonStore,
    digest,
    source_context,
)

router = APIRouter(prefix="/optimization/agent-comparisons", tags=["agent-comparison-receipts"])


class ComparisonRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    request_id: str = Field(pattern=r"^[A-Za-z0-9_-]{8,100}$")
    baseline_green_preference: float = Field(0.5, ge=0, le=1)
    green_preference: float = Field(0.82, ge=0, le=1)
    carbon_price_cny_per_ton: float = Field(85, ge=0, le=5000)
    expected_source_version: str = Field(pattern=r"^[a-f0-9]{64}$")


def owner(request):
    principal = getattr(request.state, "principal", None)
    tenant = getattr(request.state, "tenant_id", None)
    if not principal or not tenant:
        raise HTTPException(401, "authenticated owner context required")
    return digest({"principal": principal, "tenant": tenant})


@router.get("/source-context")
def context(request: Request):
    owner(request)
    return source_context()


@router.post("")
def compare(payload: ComparisonRequest, request: Request):
    try:
        return ComparisonStore().compare(owner(request), payload.model_dump())
    except ComparisonConflict as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/{request_id}")
def read_receipt(request_id: str, request: Request):
    result = ComparisonStore().get(owner(request), request_id)
    if result is None:
        raise HTTPException(404, "no completed receipt for this owner and request")
    return {"receipt": result, "source_context_now": source_context(), "readback_only": True}
