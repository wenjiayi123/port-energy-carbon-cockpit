from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
import sqlite3

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.api import routes_expert_comparisons as api
from app.services import expert_comparisons as service
from app.services.agent_comparisons import ComparisonConflict


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setattr(service.settings, "runtime_state_path", str(tmp_path / "runtime.json"))
    monkeypatch.setattr(
        service,
        "source_context",
        lambda: {"source_version": "a" * 64, "legacy_context": {"source_version": "b" * 64}},
    )
    calls = []

    def compare(self, owner, payload):
        calls.append(deepcopy(payload))
        return {
            "receipt": {
                "alternatives": [
                    {"parameters": {}, "raw": {"rl_environment": {"dataset_path": "fixture"}}}
                ]
                * 2
            }
        }

    monkeypatch.setattr(service.ComparisonStore, "compare", compare)
    monkeypatch.setattr(service.PortDataset, "load", lambda path: "dataset")
    monkeypatch.setattr(
        service, "project_trial", lambda raw, ds: {"status": "needs_evidence", "service_pct": None}
    )
    payload = {
        "request_id": "expert-test-001",
        "baseline_green_preference": 0.5,
        "green_preference": 0.8,
        "carbon_price_cny_per_ton": 85.0,
        "expected_source_version": "a" * 64,
    }
    return payload, calls


def test_durable_duplicate_and_owner_isolation(setup):
    payload, calls = setup
    store = service.ExpertComparisonStore()
    receipt = store.compare("one", payload)["receipt"]
    assert service.ExpertComparisonStore().get("one", payload["request_id"]) == receipt
    assert store.get("two", payload["request_id"]) is None
    assert store.compare("one", payload)["duplicate"]
    assert len(calls) == 1
    with pytest.raises(ComparisonConflict):
        store.compare("one", {**payload, "green_preference": 0.2})


def test_stale_before_or_during_calculation_is_not_published(setup, monkeypatch):
    payload, calls = setup
    store = service.ExpertComparisonStore()
    with pytest.raises(ComparisonConflict):
        store.compare("one", {**payload, "expected_source_version": "c" * 64})
    assert not calls
    counter = iter(["a" * 64, "c" * 64])
    monkeypatch.setattr(
        service,
        "source_context",
        lambda: {"source_version": next(counter), "legacy_context": {"source_version": "b" * 64}},
    )
    with pytest.raises(ComparisonConflict):
        store.compare("one", payload)
    assert store.get("one", payload["request_id"]) is None


def test_concurrent_duplicate_computes_once(setup):
    payload, calls = setup
    with ThreadPoolExecutor(2) as pool:
        results = list(
            pool.map(lambda _: service.ExpertComparisonStore().compare("one", payload), range(2))
        )
    assert sorted(r["duplicate"] for r in results) == [False, True]
    assert len(calls) == 1


def test_corrupted_stored_result_rejected(setup):
    payload, _ = setup
    store = service.ExpertComparisonStore()
    store.compare("one", payload)
    with sqlite3.connect(store.path) as db:
        db.execute("UPDATE receipts SET body=replace(body,'needs_evidence','ready')")
    with pytest.raises(ValueError, match="checksum"):
        store.get("one", payload["request_id"])


def test_http_explicit_parameters_and_owner_required(setup):
    payload, _ = setup
    app = FastAPI()

    @app.middleware("http")
    async def identity(request, call_next):
        request.state.principal = request.headers.get("x-test-owner")
        request.state.tenant_id = "test"
        return await call_next(request)

    app.include_router(api.router, prefix="/api")
    client = TestClient(app)
    path = "/api/optimization/expert-comparisons"
    assert client.get(path + "/source-context").status_code == 401
    headers = {"x-test-owner": "one"}
    assert client.post(path, json=payload, headers=headers).status_code == 200
    for key in ("green_preference", "baseline_green_preference", "carbon_price_cny_per_ton"):
        bad = {k: v for k, v in payload.items() if k != key}
        assert client.post(path, json=bad, headers=headers).status_code == 422
    assert (
        client.post(path, json={**payload, "green_preference": True}, headers=headers).status_code
        == 422
    )
    assert (
        client.get(path + "/" + payload["request_id"], headers={"x-test-owner": "two"}).status_code
        == 404
    )
