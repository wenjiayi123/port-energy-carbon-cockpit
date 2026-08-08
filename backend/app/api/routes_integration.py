from fastapi import APIRouter, HTTPException

from app.integration.gateway import SnapshotEnvelope, integration_gateway


router = APIRouter(tags=["port-integration"])


@router.get("/integration/contract")
def integration_contract() -> dict:
    return integration_gateway.contract()


@router.get("/integration/status")
def integration_status() -> dict:
    return integration_gateway.status()


@router.post("/integration/snapshots")
def ingest_snapshot(snapshot: SnapshotEnvelope) -> dict:
    result = integration_gateway.ingest(snapshot)
    if not result.get("accepted"):
        raise HTTPException(status_code=422, detail=result)
    return result
