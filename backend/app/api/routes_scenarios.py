from fastapi import APIRouter

from app.rl.scenarios import deployment_contract, scenario_items

router = APIRouter(tags=["scenarios"])


@router.get("")
def list_scenarios() -> list[dict[str, object]]:
    return scenario_items()


@router.get("/contract")
def get_deployment_contract() -> dict[str, object]:
    return deployment_contract()
