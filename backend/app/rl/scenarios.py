from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml

from app.rl.dataset import PROJECT_ROOT, PortDataset


SCENARIO_CONFIG = PROJECT_ROOT / "configs" / "ports.yaml"


def load_scenario_registry(path: Path = SCENARIO_CONFIG) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Port scenario registry must be a YAML object")
    contract = payload.get("deployment_contract")
    ports = payload.get("ports")
    if not isinstance(contract, dict) or not isinstance(ports, list):
        raise ValueError("Port scenario registry requires deployment_contract and ports")
    return payload


def deployment_contract() -> dict[str, Any]:
    return deepcopy(load_scenario_registry()["deployment_contract"])


def resolve_training_scenario(
    scenario_id: str | None,
    dataset_id: str,
) -> dict[str, str]:
    ports = load_scenario_registry()["ports"]
    requested = str(scenario_id or "").strip()
    if requested:
        matches = [item for item in ports if str(item.get("id")) == requested]
        if not matches:
            raise ValueError(f"Unknown port scenario: {requested}")
        scenario = matches[0]
    else:
        matches = [
            item
            for item in ports
            if item.get("mode") == "offline_public_benchmark"
            and str(item.get("dataset_id") or "") == dataset_id
        ]
        if len(matches) != 1:
            raise ValueError(
                f"Dataset {dataset_id} does not resolve to exactly one offline scenario"
            )
        scenario = matches[0]

    expected_dataset = str(scenario.get("dataset_id") or "").strip()
    if not expected_dataset:
        raise ValueError(
            f"Scenario {scenario['id']} is a connector template; attach a validated "
            "v3 dataset before training"
        )
    if expected_dataset != dataset_id:
        raise ValueError(
            f"Scenario {scenario['id']} expects dataset {expected_dataset}, got {dataset_id}"
        )

    dataset = PortDataset.load(dataset_id)
    expected_environment = str(scenario.get("environment_id") or "").strip()
    if expected_environment != dataset.environment_id:
        raise ValueError(
            f"Scenario {scenario['id']} expects environment {expected_environment}, "
            f"but dataset {dataset_id} declares {dataset.environment_id}"
        )
    return {
        "scenario": str(scenario["id"]),
        "scenario_mode": str(scenario["mode"]),
        "scenario_environment_id": expected_environment,
    }


def scenario_items() -> list[dict[str, Any]]:
    registry = load_scenario_registry()
    contract = registry["deployment_contract"]
    required_columns = sorted(
        {column for group in contract["observations"].values() for column in group}
    )
    required_adapters = list(contract["required_adapters"])
    results: list[dict[str, Any]] = []
    for source in registry["ports"]:
        item = deepcopy(source)
        dataset_id = item.get("dataset_id")
        dataset_evidence: dict[str, Any] | None = None
        missing_columns = required_columns
        if dataset_id:
            try:
                dataset = PortDataset.load(str(dataset_id))
                missing_columns = sorted(set(required_columns) - set(dataset.frame.columns))
                dataset_evidence = {
                    "id": dataset.dataset_id,
                    "environment_id": dataset.environment_id,
                    "rows": len(dataset.frame),
                    "train_rows": len(dataset.split("train")),
                    "validation_rows": len(dataset.split("validation")),
                    "test_rows": len(dataset.split("test")),
                    "package_sha256": dataset.package_sha256,
                    "quality": dataset.quality_report(),
                    "source_urls": dataset.metadata.get("source_urls", []),
                }
            except Exception as error:
                dataset_evidence = {
                    "id": str(dataset_id),
                    "valid": False,
                    "error": str(error),
                }
        adapters = item.get("adapters") or {}
        if item.get("mode") == "live_port_template":
            from app.core.config import settings
            from app.integration.gateway import integration_gateway

            if settings.live_port_id == item.get("id"):
                live_status = integration_gateway.status()
                adapters = {
                    evidence["adapter_id"]: bool(evidence["ready"])
                    for evidence in live_status["adapters"]
                }
                adapters["identity_and_audit"] = bool(
                    live_status["identity_and_audit_ready"]
                )
                item["live_adapter_evidence"] = live_status
        item["adapters"] = adapters
        missing_adapters = [name for name in required_adapters if not bool(adapters.get(name))]
        production_ready = bool(
            item.get("environment_id") == contract["environment_id"]
            and dataset_evidence
            and dataset_evidence.get("quality", {}).get("status") == "pass"
            and not missing_columns
            and not missing_adapters
            and item.get("production_dispatch_authorized")
        )
        offline_ready = bool(
            item.get("mode") == "offline_public_benchmark"
            and dataset_evidence
            and dataset_evidence.get("quality", {}).get("status") == "pass"
        )
        item["dataset"] = dataset_evidence
        item["readiness"] = {
            "status": (
                "production_ready"
                if production_ready
                else "offline_benchmark_ready"
                if offline_ready
                else "configuration_required"
            ),
            "offline_benchmark_ready": offline_ready,
            "production_ready": production_ready,
            "missing_observation_columns": missing_columns,
            "missing_adapters": missing_adapters,
            "production_dispatch_authorized": bool(item.get("production_dispatch_authorized")),
            "note": (
                "Production readiness is fail-closed and requires an approved v3 "
                "dataset, every live adapter, and explicit operator authorization."
            ),
        }
        results.append(item)
    return results
