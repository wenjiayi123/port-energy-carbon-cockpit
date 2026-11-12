"""Separate local evidence service; does not replace the accepted cockpit app."""

from fastapi import FastAPI

from app.api.routes_expert_comparisons import router
from app.core.config import settings
from app.core.security import RequestBodyLimitMiddleware, SecurityObservabilityMiddleware

app = FastAPI(title="Expert offline energy comparison evidence", version="1.0")
app.add_middleware(RequestBodyLimitMiddleware, max_body_size=settings.max_request_body_bytes)
app.add_middleware(SecurityObservabilityMiddleware)
app.include_router(router, prefix="/api")


@app.get("/api/health")
def health():
    return {
        "service": "expert-energy-evidence",
        "production_authority": False,
        "language_models_loaded": 0,
    }
