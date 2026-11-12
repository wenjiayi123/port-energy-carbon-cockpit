from concurrent.futures import ThreadPoolExecutor
import json
import sqlite3
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.api import routes_agent_comparisons as api
from app.services import agent_comparisons as service


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setattr(service.settings, "runtime_state_path", str(tmp_path / "runtime.json"))
    monkeypatch.setattr(service.DispatchSimulator, "_policy_source_signature", lambda: "a" * 64)
    calls = []

    def build(self, green_preference, carbon_price):
        calls.append((green_preference, carbon_price))
        raw = {
            "green_preference": green_preference,
            "carbon_market": {"carbon_price_cny_per_ton": carbon_price},
            "rl_environment": {"dataset_sha256": "b" * 64},
            "governance": {"production_dispatch_enabled": False},
        }
        return SimpleNamespace(model_dump=lambda **kwargs: raw)

    monkeypatch.setattr(service.KpiEngine, "build_snapshot", build)
    payload = api.ComparisonRequest(
        request_id="compare-001", expected_source_version="a" * 64
    ).model_dump()
    return payload, calls


def test_response_loss_recovers_across_store_instances_without_recalculation(setup):
    payload, calls = setup
    first = service.ComparisonStore().compare("owner", payload)
    # Client loses POST response, then only GETs the same persisted request.
    recovered = service.ComparisonStore().get("owner", payload["request_id"])
    assert recovered == first["receipt"]
    assert len(calls) == 2
    repeated = service.ComparisonStore().compare("owner", payload)
    assert repeated["duplicate"] and repeated["receipt"] == recovered
    assert len(calls) == 2


def test_same_request_id_cannot_change_parameters_and_owners_are_isolated(setup):
    payload, _ = setup
    store = service.ComparisonStore()
    store.compare("owner", payload)
    with pytest.raises(service.ComparisonConflict, match="different"):
        store.compare("owner", {**payload, "green_preference": 0.4})
    assert store.get("other-owner", payload["request_id"]) is None


def test_stale_source_rejected_before_calculation(setup):
    payload, calls = setup
    with pytest.raises(service.ComparisonConflict, match="version changed"):
        service.ComparisonStore().compare("owner", {**payload, "expected_source_version": "c" * 64})
    assert not calls


def test_source_changes_during_calculation_do_not_publish_receipt(setup, monkeypatch):
    payload, _ = setup
    versions = iter(["a" * 64, "c" * 64])
    monkeypatch.setattr(
        service.DispatchSimulator, "_policy_source_signature", lambda: next(versions)
    )
    store = service.ComparisonStore()
    with pytest.raises(service.ComparisonConflict, match="during"):
        store.compare("owner", payload)
    assert store.get("owner", payload["request_id"]) is None


def test_concurrent_duplicate_requests_compute_once(setup):
    payload, calls = setup
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(lambda _: service.ComparisonStore().compare("owner", payload), range(2))
        )
    assert sorted(r["duplicate"] for r in results) == [False, True]
    assert len(calls) == 2


def test_tampered_receipt_is_not_delivered(setup):
    payload, _ = setup
    store = service.ComparisonStore()
    store.compare("owner", payload)
    with sqlite3.connect(store.path) as db:
        raw = json.loads(db.execute("SELECT receipt_json FROM comparisons").fetchone()[0])
        raw["dataset_sha256"] = "tampered"
        db.execute("UPDATE comparisons SET receipt_json=?", (json.dumps(raw),))
    with pytest.raises(ValueError, match="checksum"):
        store.get("owner", payload["request_id"])


def test_http_contract_recovery_conflict_and_owner_isolation(setup):
    payload, calls = setup
    app = FastAPI()

    @app.middleware("http")
    async def identity(request, call_next):
        request.state.principal = request.headers.get("x-test-owner", "owner")
        request.state.tenant_id = "test"
        return await call_next(request)

    app.include_router(api.router, prefix="/api")
    client = TestClient(app)
    base = "/api/optimization/agent-comparisons"
    assert client.get(base + "/source-context").json()["source_version"] == "a" * 64
    result = client.post(base, json=payload)
    assert result.status_code == 200
    readback = client.get(base + "/" + payload["request_id"])
    assert readback.json()["receipt"] == result.json()["receipt"]
    assert (
        client.get(
            base + "/" + payload["request_id"], headers={"x-test-owner": "different"}
        ).status_code
        == 404
    )
    assert client.post(base, json={**payload, "carbon_price_cny_per_ton": 120}).status_code == 409
    assert client.post(base, json={**payload, "green_preference": 2}).status_code == 422
    assert len(calls) == 2
