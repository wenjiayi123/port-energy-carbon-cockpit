from fastapi import APIRouter, Request


router = APIRouter(tags=["security"])


@router.get("/security/context")
def get_security_context(request: Request) -> dict[str, object]:
    """Return the authenticated subject and selected tenant without token material."""
    return {
        "principal": request.state.principal,
        "role": request.state.role,
        "tenant_id": request.state.tenant_id,
        "tenant_ids": list(request.state.tenant_ids),
        "auth_method": request.state.auth_method,
        "production_authority": False,
    }
