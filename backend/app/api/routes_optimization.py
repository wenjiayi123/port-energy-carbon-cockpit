from fastapi import APIRouter

from app.schemas.dashboard import RecomputeRequest, DashboardSnapshot
from app.services.kpi_engine import KpiEngine

router = APIRouter(tags=["optimization"])


@router.post("/recompute", response_model=DashboardSnapshot)
def recompute(request: RecomputeRequest) -> DashboardSnapshot:
    return KpiEngine().build_snapshot(
        green_preference=request.green_preference,
        carbon_price=request.carbon_price_cny_per_ton,
    )

