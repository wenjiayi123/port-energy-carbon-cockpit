from fastapi import APIRouter

from app.rl.scenarios import (
    deployment_contract,
    hybrid_rl_contract,
    operational_flex_contract,
    scenario_items,
)

router = APIRouter(tags=["scenarios"])


@router.get("")
def list_scenarios() -> list[dict[str, object]]:
    return scenario_items()


@router.get("/contract")
def get_deployment_contract() -> dict[str, object]:
    return deployment_contract()


@router.get("/operational-flex-contract")
def get_operational_flex_contract() -> dict[str, object]:
    return operational_flex_contract()


@router.get("/hybrid-rl-contract")
def get_hybrid_rl_contract() -> dict[str, object]:
    return hybrid_rl_contract()
