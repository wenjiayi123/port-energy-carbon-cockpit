from collections import deque
from datetime import datetime, timezone
import threading
from uuid import uuid4

from fastapi import APIRouter, Request

from app.schemas.dashboard import RecomputeRequest, DashboardSnapshot
from app.services.kpi_engine import KpiEngine

router = APIRouter(tags=["optimization"])
_linkage_lock = threading.Lock()
_linkage_receipts: deque[dict] = deque(maxlen=20)


def _record_xiaoyi_receipt(request: Request, payload: RecomputeRequest, snapshot: DashboardSnapshot) -> None:
    trace_id = request.headers.get("x-xiaoyi-trace-id", "").strip()
    origin = request.headers.get("x-xiaoyi-origin", "").strip()
    if not trace_id or origin != "xiaoyi-ai":
        return
    kpis = {item.key: {"label": item.label, "value": item.value, "unit": item.unit} for item in snapshot.kpis}
    receipt = {
        "schema_version": "xiaoyi-energy-linkage-receipt.v1",
        "event_id": f"xel-{uuid4().hex}",
        "trace_id": trace_id[:120],
        "received_at": datetime.now(timezone.utc).isoformat(),
        "source_system": "xiaoyi-ai",
        "target_system": "energy-cockpit",
        "action_id": "energy.compare",
        "status": "completed",
        "parameters": {
            "scenario_id": payload.scenario_id,
            "green_preference": payload.green_preference,
            "carbon_price_cny_per_ton": payload.carbon_price_cny_per_ton,
        },
        "result": {
            "total_cost_saving_cny": snapshot.carbon_market.total_cost_saving_cny,
            "abatement_ton": snapshot.carbon_market.abatement_ton,
            "kpis": kpis,
            "dataset_id": snapshot.rl_environment.dataset_id,
            "dataset_sha256": snapshot.rl_environment.dataset_sha256,
        },
        "production_authority": False,
        "notice": "已完成公开数据校准模拟试算；未修改生产调度参数，未下发设备控制。",
    }
    with _linkage_lock:
        _linkage_receipts.appendleft(receipt)


@router.get("/linkage-receipt")
def latest_linkage_receipt() -> dict:
    with _linkage_lock:
        items = list(_linkage_receipts)
    return {
        "available": bool(items),
        "latest": items[0] if items else None,
        "items": items[:8],
        "count": len(items),
        "production_authority": False,
    }


@router.post("/recompute", response_model=DashboardSnapshot)
def recompute(payload: RecomputeRequest, request: Request) -> DashboardSnapshot:
    snapshot = KpiEngine().build_snapshot(
        green_preference=payload.green_preference,
        carbon_price=payload.carbon_price_cny_per_ton,
    )
    _record_xiaoyi_receipt(request, payload, snapshot)
    return snapshot

