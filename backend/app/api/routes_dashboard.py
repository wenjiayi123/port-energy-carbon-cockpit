from typing import Annotated

from fastapi import APIRouter, Query

from app.schemas.dashboard import DashboardSnapshot, TimeSeriesResponse
from app.services.kpi_engine import KpiEngine

router = APIRouter(tags=["dashboard"])


@router.get("/snapshot", response_model=DashboardSnapshot)
def get_snapshot(
    green_preference: Annotated[float, Query(ge=0, le=1)] = 0.5,
    carbon_price_cny_per_ton: Annotated[float, Query(ge=0)] = 85.0,
) -> DashboardSnapshot:
    return KpiEngine().build_snapshot(
        green_preference=green_preference,
        carbon_price=carbon_price_cny_per_ton,
    )


@router.get("/timeseries", response_model=TimeSeriesResponse)
def get_timeseries(
    green_preference: Annotated[float, Query(ge=0, le=1)] = 0.5,
) -> TimeSeriesResponse:
    return KpiEngine().build_timeseries(green_preference=green_preference)
