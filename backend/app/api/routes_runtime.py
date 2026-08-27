from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas.runtime import (
    ApprovalRequest,
    DecisionRequest,
    ExecuteRequest,
    RollbackRequest,
    RuntimeControlRequest,
    ScenarioInjectionRequest,
)
from app.services.runtime_decision import runtime_decision_service
from app.services.runtime_forecast import runtime_forecast_model
from app.services.runtime_simulator import runtime_simulator


router = APIRouter(prefix="/runtime", tags=["runtime-closed-loop"])


SCENARIOS = [
    {
        "scenario_id": "normal",
        "category": "baseline",
        "description": "Public replay plus bounded engineering physics; no injected fault.",
        "settlement_evidence": False,
    },
    {
        "scenario_id": "communications_loss",
        "category": "data_quality",
        "description": "All field qualities become disconnected and decisions fail closed.",
        "settlement_evidence": False,
    },
    {
        "scenario_id": "sensor_drift",
        "category": "data_quality",
        "description": "Meter, transformer and SOC fields receive declared 7% drift.",
        "settlement_evidence": False,
    },
    {
        "scenario_id": "transformer_derating",
        "category": "electrical",
        "description": "Transformer available capacity is reduced to 78%.",
        "settlement_evidence": False,
    },
    {
        "scenario_id": "battery_overtemperature",
        "category": "equipment",
        "description": "Battery thermal state is abnormal and power is derated.",
        "settlement_evidence": False,
    },
    {
        "scenario_id": "extreme_heat",
        "category": "weather",
        "description": "Engineering heat event increases HVAC and reefer load.",
        "settlement_evidence": False,
    },
    {
        "scenario_id": "equipment_fault",
        "category": "operations",
        "description": "Quay and yard availability fall through the equipment state machine.",
        "settlement_evidence": False,
    },
    {
        "scenario_id": "demand_response_event",
        "category": "market_engineering_calendar",
        "description": "Engineering event calendar applies a 14.5 MW import cap; not a market settlement.",
        "settlement_evidence": False,
    },
]


@router.get("/contract")
def runtime_contract() -> dict[str, Any]:
    return runtime_simulator.contract()


@router.get("/snapshot")
def runtime_snapshot() -> dict[str, Any]:
    return runtime_simulator.snapshot()


@router.get("/history")
def runtime_history(
    limit: Annotated[int, Query(ge=1, le=192)] = 48,
) -> dict[str, Any]:
    return runtime_simulator.history(limit)


@router.get("/forecast")
def runtime_forecast() -> dict[str, Any]:
    try:
        return runtime_forecast_model.predict(runtime_simulator.snapshot())
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/forecast/model")
def runtime_forecast_model_metadata() -> dict[str, Any]:
    return runtime_forecast_model.metadata()


@router.get("/scenarios")
def runtime_scenarios() -> dict[str, Any]:
    return {
        "schema_version": "runtime-scenario-catalog.v1",
        "items": SCENARIOS,
        "note": "All injected scenarios are engineering simulation and never field incidents or settlement evidence.",
    }


@router.post("/scenarios/inject")
def inject_runtime_scenario(request: ScenarioInjectionRequest) -> dict[str, Any]:
    snapshot = runtime_simulator.inject_scenario(
        request.scenario_id,
        request.duration_steps,
        request.idempotency_key,
    )
    return {
        "status": "injected",
        "idempotency_key": request.idempotency_key,
        "scenario": snapshot["active_scenario"],
        "snapshot": snapshot,
        "production_authority": False,
    }


@router.post("/control")
def control_runtime(
    request: RuntimeControlRequest,
) -> dict[str, Any]:
    try:
        return runtime_simulator.control(
            request.action,
            request.idempotency_key,
            request.steps,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/decisions")
def create_runtime_decision(request: DecisionRequest) -> dict[str, Any]:
    try:
        return runtime_decision_service.create(
            objective=request.objective,
            idempotency_key=request.idempotency_key,
            requested_by=request.requested_by,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/decisions")
def list_runtime_decisions(
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> dict[str, Any]:
    return runtime_decision_service.list(limit)


@router.get("/decisions/statistics")
def runtime_decision_statistics() -> dict[str, Any]:
    return runtime_decision_service.statistics()


@router.get("/decisions/{decision_id}")
def get_runtime_decision(decision_id: str) -> dict[str, Any]:
    try:
        return runtime_decision_service.get(decision_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc.args[0])) from exc


@router.post("/decisions/{decision_id}/approve")
def approve_runtime_decision(
    decision_id: str,
    request: ApprovalRequest,
) -> dict[str, Any]:
    try:
        return runtime_decision_service.approve(
            decision_id,
            approver_id=request.approver_id,
            decision=request.decision,
            comment=request.comment,
            idempotency_key=request.idempotency_key,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc.args[0])) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/decisions/{decision_id}/execute")
def execute_runtime_decision(
    decision_id: str,
    request: ExecuteRequest,
) -> dict[str, Any]:
    try:
        return runtime_decision_service.execute(
            decision_id,
            idempotency_key=request.idempotency_key,
            executor_id=request.executor_id,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc.args[0])) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/decisions/{decision_id}/rollback")
def rollback_runtime_decision(
    decision_id: str,
    request: RollbackRequest,
) -> dict[str, Any]:
    try:
        return runtime_decision_service.rollback(
            decision_id,
            idempotency_key=request.idempotency_key,
            requested_by=request.requested_by,
            reason=request.reason,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc.args[0])) from exc
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/decisions/{decision_id}/audit")
def runtime_decision_audit(decision_id: str) -> dict[str, Any]:
    try:
        return runtime_decision_service.audit(decision_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc.args[0])) from exc
