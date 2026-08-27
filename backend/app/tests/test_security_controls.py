import base64
import json
import time

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient
import pytest

from app.core.config import Settings
from app.core.security import append_audit_event, verify_audit_chain
from app.main import create_app


def _base64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _oidc_token(
    private_key: Ed25519PrivateKey,
    *,
    role: str = "operator",
    tenant_ids: list[str] | None = None,
    expires_in_seconds: int = 600,
) -> str:
    now = int(time.time())
    header = {"alg": "EdDSA", "kid": "test-oidc-key", "typ": "JWT"}
    claims = {
        "iss": "https://idp.port.test",
        "aud": "port-energy-api",
        "sub": "user-001",
        "iat": now,
        "nbf": now - 1,
        "exp": now + expires_in_seconds,
        "roles": [role],
        "tenant_ids": tenant_ids or ["tenant-a"],
        "amr": ["pwd", "mfa"],
    }
    header_part = _base64url(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    claims_part = _base64url(json.dumps(claims, separators=(",", ":")).encode("utf-8"))
    signing_input = f"{header_part}.{claims_part}".encode("ascii")
    return f"{header_part}.{claims_part}.{_base64url(private_key.sign(signing_input))}"


def _configure_oidc(monkeypatch) -> Ed25519PrivateKey:
    private_key = Ed25519PrivateKey.generate()
    public_key = base64.b64encode(
        private_key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
    ).decode("ascii")
    monkeypatch.setattr("app.core.security.settings.api_auth_mode", "oidc")
    monkeypatch.setattr("app.core.security.settings.oidc_issuer", "https://idp.port.test")
    monkeypatch.setattr("app.core.security.settings.oidc_audience", "port-energy-api")
    monkeypatch.setattr(
        "app.core.security.settings.oidc_public_keys_json",
        json.dumps({"test-oidc-key": public_key}),
    )
    monkeypatch.setattr(
        "app.core.security.settings.oidc_role_map_json",
        json.dumps({"viewer": "viewer", "operator": "operator", "admin": "admin"}),
    )
    monkeypatch.setattr("app.core.security.settings.oidc_role_claim", "roles")
    monkeypatch.setattr("app.core.security.settings.oidc_tenant_claim", "tenant_ids")
    monkeypatch.setattr("app.core.security.settings.oidc_require_mfa", True)
    monkeypatch.setattr("app.core.security.settings.oidc_clock_skew_seconds", 0)
    monkeypatch.setattr("app.core.security.settings.oidc_max_token_age_seconds", 3600)
    return private_key


def test_audit_log_hash_chain_detects_tampering(tmp_path, monkeypatch) -> None:
    path = tmp_path / "audit.jsonl"
    monkeypatch.setattr("app.core.security.settings.audit_log_path", str(path))
    append_audit_event({"event": "mutation_audit", "request_id": "one", "status": 200})
    append_audit_event({"event": "mutation_audit", "request_id": "two", "status": 200})

    verified = verify_audit_chain(path)
    assert verified["ok"] is True
    assert verified["hashed_events"] == 2

    lines = path.read_text(encoding="utf-8").splitlines()
    tampered = json.loads(lines[0])
    tampered["status"] = 500
    lines[0] = json.dumps(tampered)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert verify_audit_chain(path)["ok"] is False


def test_audit_chain_can_start_after_a_legacy_prefix(tmp_path, monkeypatch) -> None:
    path = tmp_path / "audit.jsonl"
    path.write_text('{"event":"legacy"}\n', encoding="utf-8")
    monkeypatch.setattr("app.core.security.settings.audit_log_path", str(path))
    append_audit_event({"event": "mutation_audit", "request_id": "new", "status": 200})

    result = verify_audit_chain(path)
    assert result["ok"] is True
    assert result["legacy_prefix_events"] == 1
    assert result["hashed_events"] == 1


def test_chunked_body_limit_cannot_bypass_content_length_check(monkeypatch) -> None:
    monkeypatch.setattr("app.core.security.settings.max_request_body_bytes", 1_024)

    def chunks():
        yield b'{"payload":"'
        yield b"x" * 2_048
        yield b'"}'

    response = TestClient(create_app()).post(
        "/api/integration/snapshots",
        content=chunks(),
        headers={"content-type": "application/json", "transfer-encoding": "chunked"},
    )
    assert response.status_code == 413


def test_oidc_context_exposes_named_subject_role_and_signed_tenant(monkeypatch) -> None:
    private_key = _configure_oidc(monkeypatch)
    token = _oidc_token(private_key, role="viewer", tenant_ids=["tenant-a", "tenant-b"])

    response = TestClient(create_app()).get(
        "/api/security/context",
        headers={"Authorization": f"Bearer {token}", "X-Tenant-ID": "tenant-b"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "principal": "oidc:https://idp.port.test:user-001",
        "role": "viewer",
        "tenant_id": "tenant-b",
        "tenant_ids": ["tenant-a", "tenant-b"],
        "auth_method": "oidc_eddsa",
        "production_authority": False,
    }
    assert response.headers["content-security-policy"] == "default-src 'none'; frame-ancestors 'none'"


def test_oidc_rejects_cross_tenant_selection(monkeypatch) -> None:
    private_key = _configure_oidc(monkeypatch)
    token = _oidc_token(private_key, role="viewer", tenant_ids=["tenant-a"])

    response = TestClient(create_app()).get(
        "/api/security/context",
        headers={"Authorization": f"Bearer {token}", "X-Tenant-ID": "tenant-b"},
    )

    assert response.status_code == 401


def test_oidc_requires_explicit_tenant_when_subject_has_multiple(monkeypatch) -> None:
    private_key = _configure_oidc(monkeypatch)
    token = _oidc_token(private_key, role="viewer", tenant_ids=["tenant-a", "tenant-b"])

    response = TestClient(create_app()).get(
        "/api/security/context",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 401


def test_oidc_rejects_expired_and_tampered_tokens(monkeypatch) -> None:
    private_key = _configure_oidc(monkeypatch)
    expired = _oidc_token(private_key, role="viewer", expires_in_seconds=-1)
    valid = _oidc_token(private_key, role="viewer")
    tampered = valid[:-1] + ("A" if valid[-1] != "A" else "B")
    client = TestClient(create_app())

    assert client.get(
        "/api/security/context", headers={"Authorization": f"Bearer {expired}"}
    ).status_code == 401
    assert client.get(
        "/api/security/context", headers={"Authorization": f"Bearer {tampered}"}
    ).status_code == 401


def test_oidc_operator_role_is_required_for_mutation(monkeypatch) -> None:
    private_key = _configure_oidc(monkeypatch)
    viewer = _oidc_token(private_key, role="viewer")
    operator = _oidc_token(private_key, role="operator")
    client = TestClient(create_app())

    assert client.post(
        "/api/dashboard/enterprise-security/evaluate",
        json={},
        headers={"Authorization": f"Bearer {viewer}"},
    ).status_code == 403
    assert client.post(
        "/api/dashboard/enterprise-security/evaluate",
        json={},
        headers={"Authorization": f"Bearer {operator}"},
    ).status_code == 422


def test_production_oidc_configuration_fails_closed_when_incomplete() -> None:
    with pytest.raises(ValueError, match="OIDC mode requires"):
        Settings(app_env="production", api_auth_mode="oidc", _env_file=None)


def test_production_oidc_configuration_accepts_rotatable_ed25519_key_set() -> None:
    public_key = base64.b64encode(
        Ed25519PrivateKey.generate().public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
    ).decode("ascii")
    configured = Settings(
        app_env="production",
        api_auth_mode="oidc",
        oidc_issuer="https://idp.port.test",
        oidc_audience="port-energy-api",
        oidc_public_keys_json=json.dumps({"active-key": public_key}),
        _env_file=None,
    )

    assert configured.oidc_public_keys == {"active-key": public_key}
