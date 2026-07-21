from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import hmac
import json
from pathlib import Path
import re
import threading
import time
from uuid import uuid4

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import JSONResponse, Response

from app.core.config import settings
from app.core.observability import log_access, request_metrics


REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,80}$")
READ_ONLY_MUTATIONS = {"/api/optimization/recompute"}
PUBLIC_PATHS = {
    "/api/health",
    "/api/health/live",
    "/api/health/ready",
    "/api/metrics",
    "/docs",
    "/openapi.json",
    "/redoc",
}
ROLE_RANK = {"anonymous": 0, "viewer": 1, "operator": 2, "admin": 3, "developer": 3}
AUDIT_LOCK = threading.Lock()


def _constant_time_match(provided: str, configured: str) -> bool:
    return bool(provided and configured) and hmac.compare_digest(
        hashlib.sha256(provided.encode("utf-8")).digest(),
        hashlib.sha256(configured.encode("utf-8")).digest(),
    )


def resolve_role(request: Request) -> str:
    if settings.api_auth_mode == "disabled":
        return "developer"
    provided = request.headers.get("x-api-key", "")
    if _constant_time_match(provided, settings.admin_api_key):
        return "admin"
    if _constant_time_match(provided, settings.operator_api_key):
        return "operator"
    if _constant_time_match(provided, settings.viewer_api_key):
        return "viewer"
    return "anonymous"


def required_role(request: Request) -> str:
    if request.url.path in PUBLIC_PATHS:
        return "anonymous"
    if request.method in {"GET", "HEAD", "OPTIONS"} or request.url.path in READ_ONLY_MUTATIONS:
        return "viewer"
    return "operator"


def append_audit_event(event: dict[str, object]) -> None:
    path = Path(settings.audit_log_path)
    with AUDIT_LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")


class SecurityObservabilityMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        supplied_request_id = request.headers.get("x-request-id", "")
        request_id = supplied_request_id if REQUEST_ID_PATTERN.fullmatch(supplied_request_id) else str(uuid4())
        request.state.request_id = request_id
        role = resolve_role(request)
        request.state.role = role
        required = required_role(request)
        started = time.perf_counter()

        if settings.api_auth_mode == "api_key" and ROLE_RANK[role] < ROLE_RANK[required]:
            request_metrics.observe_auth_denied()
            status_code = 401 if role == "anonymous" else 403
            response = JSONResponse(
                status_code=status_code,
                content={
                    "detail": "Valid operator API key required" if required == "operator" else "Authentication required",
                    "request_id": request_id,
                },
            )
        else:
            response = await call_next(request)

        duration = time.perf_counter() - started
        request_metrics.observe(request.method, response.status_code, duration)
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Cache-Control"] = "no-store" if request.url.path.startswith("/api/") else "no-cache"
        if settings.production:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"

        now = datetime.now(timezone.utc).isoformat()
        event = {
            "timestamp": now,
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
            "status": response.status_code,
            "duration_ms": round(duration * 1000, 3),
            "role": role,
            "client": request.client.host if request.client else "unknown",
        }
        log_access({"event": "http_request", **event})
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            append_audit_event({"event": "mutation_audit", **event})
        return response
