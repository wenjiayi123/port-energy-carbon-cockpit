import json

from fastapi.testclient import TestClient

from app.core.security import append_audit_event, verify_audit_chain
from app.main import create_app


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
