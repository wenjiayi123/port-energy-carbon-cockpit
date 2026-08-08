from __future__ import annotations

from datetime import datetime, timezone
from collections import defaultdict, deque
import fcntl
import hashlib
import hmac
import json
import os
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


class RequestBodyLimitMiddleware:
    """Enforce the actual ASGI body size, including chunked requests."""

    def __init__(self, app, max_body_size: int) -> None:
        self.app = app
        self.max_body_size = max_body_size

    async def __call__(self, scope: dict, receive, send) -> None:
        if scope.get("type") != "http" or scope.get("method") in {"GET", "HEAD", "OPTIONS"}:
            await self.app(scope, receive, send)
            return
        received_bytes = 0
        buffered_messages: list[dict] = []
        while True:
            message = await receive()
            if message.get("type") == "http.request":
                received_bytes += len(message.get("body", b""))
                if received_bytes > self.max_body_size:
                    request_id = (scope.get("state") or {}).get("request_id")
                    response = JSONResponse(
                        status_code=413,
                        content={
                            "detail": "Request body exceeds configured limit",
                            "request_id": request_id,
                        },
                    )
                    await response(scope, receive, send)
                    return
                buffered_messages.append(message)
                if not message.get("more_body", False):
                    break
            elif message.get("type") == "http.disconnect":
                buffered_messages.append(message)
                break

        message_index = 0

        async def replay_receive() -> dict:
            nonlocal message_index
            if message_index < len(buffered_messages):
                message = buffered_messages[message_index]
                message_index += 1
                return message
            return await receive()

        await self.app(scope, replay_receive, send)


class SlidingWindowRateLimiter:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._events: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str, now: float, limit: int) -> bool:
        cutoff = now - 60.0
        with self._lock:
            events = self._events[key]
            while events and events[0] <= cutoff:
                events.popleft()
            if len(events) >= limit:
                return False
            events.append(now)
            if len(self._events) > 10_000:
                self._events = defaultdict(
                    deque,
                    {name: values for name, values in self._events.items() if values},
                )
            return True


rate_limiter = SlidingWindowRateLimiter()


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


def resolve_principal(request: Request, role: str) -> str:
    if role == "developer":
        return "local-development"
    if role == "anonymous":
        return "anonymous"
    provided = request.headers.get("x-api-key", "")
    fingerprint = hashlib.sha256(provided.encode("utf-8")).hexdigest()[:12]
    return f"api-key:{role}:{fingerprint}"


def required_role(request: Request) -> str:
    if request.url.path in PUBLIC_PATHS:
        return "anonymous"
    if request.method in {"GET", "HEAD", "OPTIONS"} or request.url.path in READ_ONLY_MUTATIONS:
        return "viewer"
    return "operator"


def _audit_event_hash(event: dict[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()


def _previous_audit_hash(path: Path) -> str:
    if not path.exists():
        return "GENESIS"
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not lines:
        return "GENESIS"
    last_line = lines[-1]
    try:
        value = json.loads(last_line)
    except ValueError:
        return "LEGACY:" + hashlib.sha256(last_line.encode("utf-8")).hexdigest()
    return str(value.get("event_hash") or "LEGACY:" + hashlib.sha256(last_line.encode("utf-8")).hexdigest())


def append_audit_event(event: dict[str, object]) -> dict[str, object]:
    path = Path(settings.audit_log_path)
    with AUDIT_LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a+", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            chained = {**event, "previous_event_hash": _previous_audit_hash(path)}
            chained["event_hash"] = _audit_event_hash(chained)
            handle.write(json.dumps(chained, ensure_ascii=False, separators=(",", ":")) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        return chained


def verify_audit_chain(path: str | Path | None = None) -> dict[str, object]:
    audit_path = Path(path or settings.audit_log_path)
    if not audit_path.exists():
        return {"ok": True, "events": 0, "hashed_events": 0, "legacy_prefix_events": 0}
    previous = "GENESIS"
    hashed_events = 0
    legacy_prefix_events = 0
    for line_number, line in enumerate(audit_path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except ValueError:
            return {"ok": False, "line": line_number, "reason": "invalid_json"}
        event_hash = event.pop("event_hash", None)
        if not event_hash:
            if hashed_events:
                return {"ok": False, "line": line_number, "reason": "unchained_event_after_chain"}
            previous = "LEGACY:" + hashlib.sha256(line.encode("utf-8")).hexdigest()
            legacy_prefix_events += 1
            continue
        if event.get("previous_event_hash") != previous:
            return {"ok": False, "line": line_number, "reason": "previous_hash_mismatch"}
        computed = _audit_event_hash(event)
        if not hmac.compare_digest(str(event_hash), computed):
            return {"ok": False, "line": line_number, "reason": "event_hash_mismatch"}
        previous = str(event_hash)
        hashed_events += 1
    return {
        "ok": True,
        "events": hashed_events + legacy_prefix_events,
        "hashed_events": hashed_events,
        "legacy_prefix_events": legacy_prefix_events,
        "head_hash": previous,
    }


class SecurityObservabilityMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        supplied_request_id = request.headers.get("x-request-id", "")
        request_id = supplied_request_id if REQUEST_ID_PATTERN.fullmatch(supplied_request_id) else str(uuid4())
        request.state.request_id = request_id
        role = resolve_role(request)
        request.state.role = role
        principal = resolve_principal(request, role)
        request.state.principal = principal
        required = required_role(request)
        started = time.perf_counter()

        content_length = request.headers.get("content-length")
        oversized = bool(
            content_length
            and content_length.isdigit()
            and int(content_length) > settings.max_request_body_bytes
        )
        client = request.client.host if request.client else "unknown"
        rate_key = f"{client}:{principal}"
        rate_allowed = rate_limiter.allow(
            rate_key,
            time.monotonic(),
            settings.rate_limit_requests_per_minute,
        )

        if oversized:
            response = JSONResponse(
                status_code=413,
                content={"detail": "Request body exceeds configured limit", "request_id": request_id},
            )
        elif not rate_allowed:
            response = JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded", "request_id": request_id},
                headers={"Retry-After": "60"},
            )
        elif settings.api_auth_mode == "api_key" and ROLE_RANK[role] < ROLE_RANK[required]:
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
            "principal": principal,
            "client": client,
        }
        log_access({"event": "http_request", **event})
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            append_audit_event({"event": "mutation_audit", **event})
        return response
