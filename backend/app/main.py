from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes_dashboard import router as dashboard_router
from app.api.routes_evidence import router as evidence_router
from app.api.routes_health import router as health_router
from app.api.routes_integration import router as integration_router
from app.api.routes_linkage import router as linkage_router
from app.api.routes_optimization import router as optimization_router
from app.api.routes_rl import router as rl_router
from app.api.routes_runtime import router as runtime_router
from app.api.routes_scenarios import router as scenarios_router
from app.core.config import settings
from app.core.security import RequestBodyLimitMiddleware, SecurityObservabilityMiddleware


def create_app() -> FastAPI:
    app = FastAPI(
        title="Energy Carbon Dispatch Cockpit API",
        version="0.4.0",
        description=(
            "API for public-data-calibrated realtime simulation, causal forecasting, "
            "approval-gated simulation execution, offline RL training, and held-out evaluation."
        ),
    )
    app.add_middleware(
        RequestBodyLimitMiddleware,
        max_body_size=settings.max_request_body_bytes,
    )
    app.add_middleware(SecurityObservabilityMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "X-API-Key", "X-Request-ID"],
        expose_headers=["X-Request-ID"],
    )
    app.include_router(health_router, prefix="/api")
    app.include_router(evidence_router, prefix="/api")
    app.include_router(integration_router, prefix="/api")
    app.include_router(dashboard_router, prefix="/api/dashboard")
    app.include_router(optimization_router, prefix="/api/optimization")
    app.include_router(scenarios_router, prefix="/api/scenarios")
    # Register the real learner routes before the legacy assistant gateway so
    # duplicate historical paths cannot shadow measured training endpoints.
    app.include_router(rl_router, prefix="/api")
    app.include_router(runtime_router, prefix="/api")
    app.include_router(linkage_router, prefix="/api")
    return app


app = create_app()
