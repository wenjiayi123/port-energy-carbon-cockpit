from __future__ import annotations

import base64
import binascii
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timezone
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

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
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


@dataclass(frozen=True)
class IdentityContext:
    role: str
    principal: str
    tenant_id: str
    tenant_ids: tuple[str, ...]
    auth_method: str


ANONYMOUS_IDENTITY = IdentityContext(
    role="anonymous",
    principal="anonymous",
    tenant_id="",
    tenant_ids=(),
    auth_method="none",
)


def _constant_time_match(provided: str, configured: str) -> bool:
    return bool(provided and configured) and hmac.compare_digest(
        provided.encode("utf-8"),
        configured.encode("utf-8"),
    )


def _base64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def _oidc_identity(request: Request) -> IdentityContext:
    authorization = request.headers.get("authorization", "")
    scheme, separator, token = authorization.partition(" ")
    if not separator or scheme.lower() != "bearer" or not token:
        return ANONYMOUS_IDENTITY
    parts = token.split(".")
    if len(parts) != 3:
        return ANONYMOUS_IDENTITY
    try:
        header = json.loads(_base64url_decode(parts[0]))
        claims = json.loads(_base64url_decode(parts[1]))
        signature = _base64url_decode(parts[2])
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError, binascii.Error):
        return ANONYMOUS_IDENTITY
    if not isinstance(header, dict) or not isinstance(claims, dict):
        return ANONYMOUS_IDENTITY
    if header.get("alg") != "EdDSA" or not isinstance(header.get("kid"), str):
        return ANONYMOUS_IDENTITY
    public_key_b64 = settings.oidc_public_keys.get(header["kid"])
    if not public_key_b64:
        return ANONYMOUS_IDENTITY
    try:
        public_key = Ed25519PublicKey.from_public_bytes(
            base64.b64decode(public_key_b64, validate=True)
        )
        public_key.verify(signature, f"{parts[0]}.{parts[1]}".encode("ascii"))
    except (ValueError, InvalidSignature, binascii.Error):
        return ANONYMOUS_IDENTITY

    now = time.time()
    skew = settings.oidc_clock_skew_seconds
    issuer = claims.get("iss")
    audience = claims.get("aud")
    audiences = {audience} if isinstance(audience, str) else set(audience or [])
    subject = claims.get("sub")
    issued_at = claims.get("iat")
    expires_at = claims.get("exp")
    not_before = claims.get("nbf", issued_at)
    if not (
        issuer == settings.oidc_issuer
        and settings.oidc_audience in audiences
        and isinstance(subject, str)
        and subject.strip()
        and isinstance(issued_at, (int, float))
        and isinstance(expires_at, (int, float))
        and isinstance(not_before, (int, float))
        and issued_at <= now + skew
        and not_before <= now + skew
        and expires_at >= now - skew
        and now - issued_at <= settings.oidc_max_token_age_seconds + skew
    ):
        return ANONYMOUS_IDENTITY
    if settings.oidc_require_mfa:
        authentication_methods = claims.get("amr", [])
        if not isinstance(authentication_methods, list) or not {
            "mfa",
            "hwk",
            "otp",
        }.intersection(authentication_methods):
            return ANONYMOUS_IDENTITY

    external_roles = claims.get(settings.oidc_role_claim, [])
    if isinstance(external_roles, str):
        external_roles = [external_roles]
    if not isinstance(external_roles, list) or not all(
        isinstance(role, str) for role in external_roles
    ):
        return ANONYMOUS_IDENTITY
    mapped_roles = {
        settings.oidc_role_map[role]
        for role in external_roles
        if role in settings.oidc_role_map
    }
    if not mapped_roles:
        return ANONYMOUS_IDENTITY
    role = max(mapped_roles, key=lambda item: ROLE_RANK[item])

    tenant_claim = claims.get(settings.oidc_tenant_claim, [])
    if isinstance(tenant_claim, str):
        tenant_claim = [tenant_claim]
    if not isinstance(tenant_claim, list) or not tenant_claim or not all(
        isinstance(tenant_id, str) and tenant_id.strip() for tenant_id in tenant_claim
    ):
        return ANONYMOUS_IDENTITY
    tenant_ids = tuple(sorted(set(tenant_claim)))
    requested_tenant = request.headers.get("x-tenant-id", "").strip()
    if requested_tenant:
        if requested_tenant not in tenant_ids:
            return ANONYMOUS_IDENTITY
        tenant_id = requested_tenant
    elif len(tenant_ids) == 1:
        tenant_id = tenant_ids[0]
    else:
        return ANONYMOUS_IDENTITY
    return IdentityContext(
        role=role,
        principal=f"oidc:{issuer}:{subject}",
        tenant_id=tenant_id,
        tenant_ids=tenant_ids,
        auth_method="oidc_eddsa",
    )


def resolve_identity(request: Request) -> IdentityContext:
    if settings.api_auth_mode == "disabled":
        return IdentityContext(
            role="developer",
            principal="local-development",
            tenant_id="local-development",
            tenant_ids=("local-development",),
            auth_method="development",
        )
    if settings.api_auth_mode == "oidc":
        return _oidc_identity(request)
    provided = request.headers.get("x-api-key", "")
    for role, configured in (
        ("admin", settings.admin_api_key),
        ("operator", settings.operator_api_key),
        ("viewer", settings.viewer_api_key),
    ):
        if _constant_time_match(provided, configured):
            return IdentityContext(
                role=role,
                principal=f"api-key-role:{role}",
                tenant_id="legacy-single-tenant",
                tenant_ids=("legacy-single-tenant",),
                auth_method="api_key",
            )
    return ANONYMOUS_IDENTITY


def resolve_role(request: Request) -> str:
    return resolve_identity(request).role


def resolve_principal(request: Request, role: str) -> str:
    identity = resolve_identity(request)
    return identity.principal if identity.role == role else "anonymous"


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
        identity = resolve_identity(request)
        role = identity.role
        request.state.role = role
        principal = identity.principal
        request.state.principal = principal
        request.state.tenant_id = identity.tenant_id
        request.state.tenant_ids = identity.tenant_ids
        request.state.auth_method = identity.auth_method
        required = required_role(request)
        started = time.perf_counter()

        content_length = request.headers.get("content-length")
        oversized = bool(
            content_length
            and content_length.isdigit()
            and int(content_length) > settings.max_request_body_bytes
        )
        client = request.client.host if request.client else "unknown"
        rate_key = f"{client}:{principal}:{identity.tenant_id}"
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
        elif settings.api_auth_mode != "disabled" and ROLE_RANK[role] < ROLE_RANK[required]:
            request_metrics.observe_auth_denied()
            status_code = 401 if role == "anonymous" else 403
            response = JSONResponse(
                status_code=status_code,
                content={
                    "detail": "Operator role required" if required == "operator" else "Authentication and tenant context required",
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
        response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
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
            "tenant_id": identity.tenant_id or None,
            "auth_method": identity.auth_method,
            "client": client,
        }
        log_access({"event": "http_request", **event})
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            append_audit_event({"event": "mutation_audit", **event})
        return response
