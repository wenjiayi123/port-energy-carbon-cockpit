from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.api import routes_linkage as linkage
from app.main import app


@pytest.mark.parametrize("action", ["pause", "resume", "stop"])
def test_training_control_preview_never_changes_the_job(monkeypatch, action) -> None:
    calls = []
    monkeypatch.setattr(linkage, "_training_status", lambda: {"status": "running"})
    monkeypatch.setattr(
        linkage, "_control_training", lambda command: calls.append(command) or {"status": command}
    )
    client = TestClient(app)
    payload = {"action_id": f"{action}_rl_training", "dry_run": True}
    preview = client.post("/api/assistant/actions/execute", json=payload)
    assert preview.status_code == 200
    assert preview.json()["execution_result"]["executed"] is False
    assert preview.json()["execution_result"]["status"] == f"ready_to_{action}"
    assert calls == []

    result = client.post(
        "/api/assistant/actions/execute", json={**payload, "dry_run": False}
    )
    assert result.status_code == 200
    assert calls == [action]


@pytest.mark.parametrize("dry_run", [True, False])
@pytest.mark.parametrize("action", ["run_policy_test", "verify_policy_for_online"])
def test_policy_linkage_reads_registered_evidence_without_rerunning_evaluation(
    monkeypatch, action, dry_run
) -> None:
    policy = {
        "policy_id": "verified-policy",
        "stage": "verified_offline",
        "artifact_integrity": "verified",
        "dataset_status": "verified",
        "evaluation_status": "tested",
        "verification_status": "verified",
        "evaluation_metrics": {"safety_violations": 0, "carbon_reduction_pct": 8.5},
    }
    monkeypatch.setattr(linkage.training_service, "registry", lambda: {"policies": [policy]})

    def unexpected_evaluation(*args, **kwargs):
        pytest.fail("Reading the registered test must not rewrite evaluation or verification files")

    monkeypatch.setattr(linkage.training_service, "evaluate", unexpected_evaluation)
    monkeypatch.setattr(linkage.training_service, "record_verification", unexpected_evaluation)
    monkeypatch.setattr(
        linkage, "_dispatch_policy",
        lambda payload: {"status": "dry_run_ready", "dry_run": payload["dry_run"]},
    )
    result = linkage.assistant_execute({"action_id": action, "dry_run": dry_run})
    execution = result["execution_result"]["result"]
    if action == "run_policy_test":
        assert execution["metrics"]["carbon_reduction_pct"] == 8.5
    else:
        assert execution["verify"]["policy_id"] == "verified-policy"
        assert execution["dispatch"]["dry_run"] is True


def test_policy_linkage_without_admitted_evidence_returns_blocked(monkeypatch) -> None:
    monkeypatch.setattr(linkage.training_service, "registry", lambda: {"policies": []})
    result = linkage.assistant_execute(
        {"action_id": "verify_policy_for_online", "dry_run": True}
    )
    assert result["execution_result"]["status"] == "blocked"
    assert result["execution_result"]["result"]["verify"]["ok"] is False


def test_xiaoyi_uses_its_own_launcher_and_configured_port(monkeypatch, tmp_path) -> None:
    project = tmp_path / "xiaoyi project with spaces"
    project.mkdir()
    (project / "run.sh").write_text("#!/bin/bash\nexit 3\n", encoding="utf-8")
    calls = []

    def spawn(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(pid=123, poll=lambda: 3)

    monkeypatch.setattr(linkage, "XIAOYI_PROJECT", project)
    monkeypatch.setattr(linkage, "XIAOYI_BASE_URL", "http://127.0.0.1:18010")
    monkeypatch.setattr(linkage, "_xiaoyi_process", None)
    monkeypatch.setattr(linkage, "_probe_http", lambda *args: {"ok": False})
    monkeypatch.setattr(linkage.subprocess, "Popen", spawn)
    result = linkage.launch_xiaoyi()

    assert calls[0][0] == ["bash", str(project / "run.sh")]
    assert calls[0][1]["env"]["XIAOYI_PORT"] == "18010"
    assert result["status"] == "failed"
    assert result["error"] == "xiaoyi_process_exited"
    assert result["returncode"] == 3


def test_xiaoyi_reuses_a_starting_process(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(linkage, "XIAOYI_PROJECT", tmp_path)
    monkeypatch.setattr(linkage, "_xiaoyi_process", SimpleNamespace(pid=123, poll=lambda: None))
    monkeypatch.setattr(linkage, "_probe_http", lambda *args: {"ok": False})
    result = linkage.launch_xiaoyi()
    assert result["status"] == "starting"
    assert result["pid"] == 123


def test_xiaoyi_fallback_uses_target_virtualenv(monkeypatch, tmp_path) -> None:
    python = tmp_path / ".venv" / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.touch()
    monkeypatch.setattr(linkage, "XIAOYI_PROJECT", tmp_path)
    monkeypatch.setattr(linkage, "XIAOYI_BASE_URL", "http://127.0.0.1:18010")
    command = linkage._xiaoyi_start_command()
    assert command[0] == str(python)
    assert command[-2:] == ["--port", "18010"]


def test_sailing_does_not_report_a_dead_process_as_launched(monkeypatch) -> None:
    monkeypatch.setattr(linkage, "sailing_status", lambda: {"launchable": True})
    monkeypatch.setattr(linkage, "_sailing_process", None)
    monkeypatch.setattr(
        linkage.subprocess, "Popen",
        lambda *args, **kwargs: SimpleNamespace(pid=123, wait=lambda timeout: 1),
    )
    result = linkage.launch_sailing()
    assert result["status"] == "failed"
    assert result["error"] == "sailing_process_exited"


def test_sailing_smoke_preview_requires_the_actual_script(monkeypatch) -> None:
    monkeypatch.setattr(
        linkage, "sailing_status",
        lambda: {"launchable": True, "smoke_script": {"exists": False}},
    )
    result = linkage.run_sailing_smoke(dry_run=True)
    assert result["status"] == "failed"
    assert result["error"] == "sailing_smoke_script_missing"
