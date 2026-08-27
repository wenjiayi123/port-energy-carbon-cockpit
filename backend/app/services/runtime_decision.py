from __future__ import annotations

import hashlib
import json
from pathlib import Path
import threading
import time
from typing import Any, Callable

from app.core.config import settings
from app.core.security import append_audit_event
from app.services.runtime_forecast import RuntimeForecastModel, runtime_forecast_model
from app.services.runtime_simulator import (
    RealtimePortSimulator,
    canonical_sha256,
    iso_z,
    runtime_simulator,
    utc_now,
)


RUNTIME_STATE_DIR = Path(__file__).resolve().parents[1] / "data" / "runtime"
ALLOWED_ACTION_FIELDS = {
    "battery_power_kw",
    "hvac_setpoint_c",
    "shore_power_limit_kw",
    "agv_charging_limit_kw",
}
OBJECTIVE_WEIGHTS = {
    "balanced": {"cost": 0.26, "carbon": 0.24, "peak": 0.22, "service": 0.20, "life": 0.08},
    "cost": {"cost": 0.42, "carbon": 0.16, "peak": 0.20, "service": 0.16, "life": 0.06},
    "carbon": {"cost": 0.18, "carbon": 0.42, "peak": 0.18, "service": 0.16, "life": 0.06},
    "peak": {"cost": 0.18, "carbon": 0.16, "peak": 0.42, "service": 0.18, "life": 0.06},
    "service": {"cost": 0.16, "carbon": 0.16, "peak": 0.18, "service": 0.44, "life": 0.06},
}


def _event_hash(event: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


class RuntimeDecisionService:
    """MPC recommendation, approval, simulation execution, receipt, and rollback."""

    def __init__(
        self,
        simulator: RealtimePortSimulator | None = None,
        forecast_model: RuntimeForecastModel | None = None,
        *,
        state_path: str | Path | None = None,
        audit_writer: Callable[[dict[str, object]], dict[str, object]] | None = append_audit_event,
    ) -> None:
        self.simulator = simulator or runtime_simulator
        self.forecast_model = forecast_model or runtime_forecast_model
        self.state_path = Path(state_path or (RUNTIME_STATE_DIR / "decisions.json"))
        self.audit_writer = audit_writer
        self._lock = threading.RLock()
        self._state: dict[str, Any] = {
            "schema_version": "runtime-decision-store.v1",
            "decisions": {},
            "request_idempotency": {},
        }
        self._load()

    def _load(self) -> None:
        if not self.state_path.exists():
            return
        try:
            value = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return
        if value.get("schema_version") == "runtime-decision-store.v1" and isinstance(
            value.get("decisions"), dict
        ):
            self._state = value

    def _persist(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.state_path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(self._state, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        temporary.replace(self.state_path)

    @staticmethod
    def _signal(snapshot: dict[str, Any], field_id: str) -> float:
        return float(snapshot["signals"][field_id]["value"])

    def _project_action(
        self,
        snapshot: dict[str, Any],
        requested: dict[str, float],
    ) -> tuple[dict[str, float], list[dict[str, Any]]]:
        unknown = set(requested) - ALLOWED_ACTION_FIELDS
        if unknown:
            raise ValueError("action_not_whitelisted:" + ",".join(sorted(unknown)))
        constraints: list[dict[str, Any]] = []

        def projected(
            name: str,
            value: float,
            minimum: float,
            maximum: float,
            constraint_id: str,
        ) -> float:
            safe = min(maximum, max(minimum, float(value)))
            if abs(safe - float(value)) > 1e-9:
                constraints.append(
                    {
                        "constraint_id": constraint_id,
                        "field": name,
                        "requested": float(value),
                        "projected": safe,
                    }
                )
            return safe

        soc = self._signal(snapshot, "battery.soc_pct")
        temperature = self._signal(snapshot, "battery.temperature_c")
        battery_min = -5_000.0 if soc < 89.0 else 0.0
        battery_max = 5_000.0 if soc > 11.0 else 0.0
        if temperature >= 46.0:
            battery_min = max(battery_min, -900.0)
            battery_max = min(battery_max, 900.0)
        battery = projected(
            "battery_power_kw",
            requested["battery_power_kw"],
            battery_min,
            battery_max,
            "BESS_SOC_THERMAL_ENVELOPE",
        )
        hvac = projected(
            "hvac_setpoint_c",
            requested["hvac_setpoint_c"],
            22.0,
            27.0,
            "BUILDING_COMFORT_ENVELOPE",
        )
        vessels = self._signal(snapshot, "operations.vessels_at_berth")
        shore_service_min = min(6_800.0, vessels * 650.0) * 0.35
        shore = projected(
            "shore_power_limit_kw",
            requested["shore_power_limit_kw"],
            shore_service_min,
            6_800.0,
            "SHORE_POWER_SERVICE_AND_RATING",
        )
        agv = projected(
            "agv_charging_limit_kw",
            requested["agv_charging_limit_kw"],
            400.0,
            1_800.0,
            "AGV_SERVICE_RESERVE",
        )
        current_import = self._signal(snapshot, "grid.import_power_kw")
        transformer_capacity = self._signal(snapshot, "transformer.capacity_kw")
        charging_kw = max(0.0, -battery)
        estimated_import = (
            current_import + charging_kw + (agv - self._signal(snapshot, "charging.agv_load_kw"))
        )
        if estimated_import > transformer_capacity * 0.94:
            available_charge = max(
                0.0,
                transformer_capacity * 0.94
                - current_import
                - (agv - self._signal(snapshot, "charging.agv_load_kw")),
            )
            safe_battery = -available_charge if battery < 0 else battery
            if abs(safe_battery - battery) > 1e-9:
                constraints.append(
                    {
                        "constraint_id": "TRANSFORMER_RESERVE_MARGIN",
                        "field": "battery_power_kw",
                        "requested": battery,
                        "projected": safe_battery,
                    }
                )
                battery = safe_battery
        return (
            {
                "battery_power_kw": round(battery, 6),
                "hvac_setpoint_c": round(hvac, 6),
                "shore_power_limit_kw": round(shore, 6),
                "agv_charging_limit_kw": round(agv, 6),
            },
            constraints,
        )

    def _recommend(
        self,
        snapshot: dict[str, Any],
        forecast: dict[str, Any],
        objective: str,
    ) -> tuple[dict[str, float], dict[str, float], list[dict[str, Any]], dict[str, float]]:
        weights = OBJECTIVE_WEIGHTS[objective]
        current_import = self._signal(snapshot, "grid.import_power_kw")
        current_agv = self._signal(snapshot, "charging.agv_load_kw")
        current_shore = self._signal(snapshot, "shore_power.load_kw")
        price = self._signal(snapshot, "grid.electricity_price_cny_per_kwh")
        carbon = self._signal(snapshot, "grid.carbon_factor_kg_per_kwh")
        capacity = self._signal(snapshot, "transformer.capacity_kw")
        forecast_load = float(forecast["points"][0]["predictions"]["terminal_load_kw"])

        def evaluate(action: dict[str, float], constraint_count: int = 0) -> dict[str, float]:
            shore_delta = action["shore_power_limit_kw"] - current_shore
            agv_delta = action["agv_charging_limit_kw"] - current_agv
            hvac_delta = (24.0 - action["hvac_setpoint_c"]) * 115.0
            predicted_import = max(
                0.0,
                0.55 * current_import
                + 0.45 * forecast_load
                + shore_delta
                + agv_delta
                + hvac_delta
                - action["battery_power_kw"],
            )
            peak_ratio = predicted_import / max(1.0, capacity)
            score_terms = {
                "cost": predicted_import * price / 17_000.0,
                "carbon": predicted_import * carbon / 8_000.0,
                "peak": max(0.0, peak_ratio - 0.72) ** 2 * 8.0 + peak_ratio**2,
                "service": (
                    max(0.0, 5_500.0 - action["shore_power_limit_kw"]) / 5_500.0
                    + max(0.0, 1_100.0 - action["agv_charging_limit_kw"]) / 1_100.0
                    + max(0.0, action["hvac_setpoint_c"] - 26.0) / 2.0
                ),
                "life": abs(action["battery_power_kw"]) / 5_000.0,
            }
            score = sum(weights[key] * score_terms[key] for key in weights)
            score += 0.01 * constraint_count
            return {
                "predicted_grid_import_kw": predicted_import,
                "predicted_grid_delta_kw": predicted_import - current_import,
                "predicted_step_cost_cny": predicted_import * 0.25 * price,
                "predicted_step_carbon_kg": predicted_import * 0.25 * carbon,
                "score": score,
            }

        best: (
            tuple[float, dict[str, float], dict[str, float], list[dict[str, Any]], dict[str, float]]
            | None
        ) = None
        for battery in (-3_200.0, -1_600.0, 0.0, 1_600.0, 3_200.0):
            for hvac in (23.0, 24.5, 26.0):
                for shore in (4_200.0, 5_500.0, 6_800.0):
                    for agv in (700.0, 1_200.0, 1_750.0):
                        requested = {
                            "battery_power_kw": battery,
                            "hvac_setpoint_c": hvac,
                            "shore_power_limit_kw": shore,
                            "agv_charging_limit_kw": agv,
                        }
                        safe, constraints = self._project_action(snapshot, requested)
                        impact = evaluate(safe, len(constraints))
                        score = impact["score"]
                        if best is None or score < best[0]:
                            best = (score, requested, safe, constraints, impact)
        assert best is not None
        _, requested, safe, constraints, impact = best
        baseline, _ = self._project_action(
            snapshot,
            {
                "battery_power_kw": 0.0,
                "hvac_setpoint_c": 24.0,
                "shore_power_limit_kw": current_shore,
                "agv_charging_limit_kw": current_agv,
            },
        )
        baseline_impact = evaluate(baseline)
        impact = {
            **impact,
            "sop_baseline_score": baseline_impact["score"],
            "score_improvement_vs_sop_pct": (
                (baseline_impact["score"] - impact["score"])
                / max(1e-9, abs(baseline_impact["score"]))
                * 100.0
            ),
            "predicted_cost_change_vs_sop_cny": (
                impact["predicted_step_cost_cny"] - baseline_impact["predicted_step_cost_cny"]
            ),
            "predicted_carbon_change_vs_sop_kg": (
                impact["predicted_step_carbon_kg"] - baseline_impact["predicted_step_carbon_kg"]
            ),
        }
        return requested, safe, constraints, impact

    def _append_record_event(
        self,
        record: dict[str, Any],
        event_type: str,
        detail: dict[str, Any],
    ) -> dict[str, Any]:
        events = record.setdefault("audit_events", [])
        event = {
            "event_type": event_type,
            "event_time": iso_z(utc_now()),
            "decision_id": record["decision_id"],
            "previous_event_hash": events[-1]["event_hash"] if events else "GENESIS",
            "detail": detail,
        }
        event["event_hash"] = _event_hash(event)
        events.append(event)
        if self.audit_writer is not None:
            self.audit_writer(
                {
                    "event": "runtime_decision_lifecycle",
                    "decision_id": record["decision_id"],
                    "lifecycle_event": event_type,
                    "record_event_hash": event["event_hash"],
                    "status": record.get("status"),
                }
            )
        return event

    @staticmethod
    def _record_hash(record: dict[str, Any]) -> str:
        value = {key: item for key, item in record.items() if key != "record_sha256"}
        return canonical_sha256(value)

    def create(self, *, objective: str, idempotency_key: str, requested_by: str) -> dict[str, Any]:
        decision_started = time.perf_counter()
        with self._lock:
            prior_id = self._state["request_idempotency"].get(idempotency_key)
            if prior_id:
                return json.loads(json.dumps(self._state["decisions"][prior_id]))
            snapshot = self.simulator.snapshot()
            if not snapshot["decision_allowed"]:
                raise RuntimeError("runtime_quality_gate_failed")
            forecast_started = time.perf_counter()
            forecast = self.forecast_model.predict(snapshot)
            forecast_ms = (time.perf_counter() - forecast_started) * 1000.0
            policy_started = time.perf_counter()
            requested, safe, constraints, predicted_impact = self._recommend(
                snapshot, forecast, objective
            )
            policy_and_safety_ms = (time.perf_counter() - policy_started) * 1000.0
            risk_level = (
                "high"
                if (
                    abs(safe["battery_power_kw"]) >= 3_000.0
                    or abs(
                        safe["agv_charging_limit_kw"]
                        - self._signal(snapshot, "charging.agv_load_kw")
                    )
                    > 1_200.0
                    or self._signal(snapshot, "transformer.loading_pct") > 90.0
                )
                else "standard"
            )
            required_approvals = 2 if risk_level == "high" else 1
            decision_id = (
                "decision-" + hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()[:24]
            )
            model_meta = self.forecast_model.metadata()
            record = {
                "schema_version": "runtime-decision.v1",
                "decision_id": decision_id,
                "status": "awaiting_approval",
                "objective": objective,
                "requested_by": requested_by,
                "request_idempotency_key": idempotency_key,
                "created_at": iso_z(utc_now()),
                "updated_at": iso_z(utc_now()),
                "risk_level": risk_level,
                "required_approvals": required_approvals,
                "approvals": [],
                "input_snapshot": {
                    "snapshot_id": snapshot["snapshot_id"],
                    "snapshot_sha256": snapshot["snapshot_sha256"],
                    "trace_id": snapshot["trace_id"],
                    "dataset_id": snapshot["dataset"]["dataset_id"],
                    "dataset_sha256": snapshot["dataset"]["dataset_sha256"],
                    "kpis": snapshot["kpis"]["current"],
                },
                "forecast": {
                    "forecast_sha256": canonical_sha256(forecast),
                    "model_id": forecast["model"]["model_id"],
                    "model_sha256": forecast["model"]["model_sha256"],
                    "points": forecast["points"],
                },
                "policy": {
                    "policy_id": "runtime-energy-mpc-v1",
                    "policy_family": "finite_candidate_model_predictive_control",
                    "policy_sha256": canonical_sha256(
                        {
                            "id": "runtime-energy-mpc-v1",
                            "objective_weights": OBJECTIVE_WEIGHTS,
                            "allowed_action_fields": sorted(ALLOWED_ACTION_FIELDS),
                            "forecast_model_sha256": model_meta["model_sha256"],
                        }
                    ),
                    "objective_weights": OBJECTIVE_WEIGHTS[objective],
                    "candidate_count": 135,
                    "strong_baseline": {
                        "id": "current-state-sop-v1",
                        "battery_power_kw": 0.0,
                        "hvac_setpoint_c": 24.0,
                        "shore_power_limit_kw": "hold_current",
                        "agv_charging_limit_kw": "hold_current",
                    },
                },
                "recommended_action": requested,
                "projected_action": safe,
                "safety_projection": {
                    "triggered_constraints": constraints,
                    "changed": requested != safe,
                    "software_safety_envelope": True,
                },
                "predicted_impact": {
                    key: round(float(value), 6) for key, value in predicted_impact.items()
                },
                "decision_explanation": {
                    "schema_version": "runtime-objective-decomposition.v1",
                    "method": "declared_objective_weight_decomposition",
                    "reason_codes": [
                        f"OPTIMIZE_{name.upper()}"
                        for name, _ in sorted(
                            OBJECTIVE_WEIGHTS[objective].items(),
                            key=lambda item: item[1],
                            reverse=True,
                        )[:2]
                    ],
                    "objective_weights": OBJECTIVE_WEIGHTS[objective],
                    "safety_constraint_ids": [item["constraint_id"] for item in constraints],
                    "counterfactual": {
                        "policy_id": "current-state-sop-v1",
                        "score": round(float(predicted_impact["sop_baseline_score"]), 6),
                    },
                    "local_feature_attribution_verified": False,
                    "production_fidelity_verified": False,
                },
                "decision_latency": {
                    "schema_version": "runtime-decision-latency.v1",
                    "clock": "monotonic",
                    "forecast_ms": round(forecast_ms, 6),
                    "policy_and_safety_projection_ms": round(policy_and_safety_ms, 6),
                    "end_to_end_ms": round((time.perf_counter() - decision_started) * 1000.0, 6),
                    "production_sla_verified": False,
                },
                "production_authority": False,
                "dispatch_allowed": False,
                "execution_receipt": None,
                "rollback": {"available": False, "status": "not_required"},
                "audit_events": [],
            }
            self._append_record_event(
                record,
                "recommendation_created",
                {
                    "input_snapshot_sha256": snapshot["snapshot_sha256"],
                    "model_sha256": forecast["model"]["model_sha256"],
                    "policy_sha256": record["policy"]["policy_sha256"],
                    "recommended_action": requested,
                    "projected_action": safe,
                },
            )
            record["record_sha256"] = self._record_hash(record)
            self._state["decisions"][decision_id] = record
            self._state["request_idempotency"][idempotency_key] = decision_id
            self._persist()
            return json.loads(json.dumps(record))

    def approve(
        self,
        decision_id: str,
        *,
        approver_id: str,
        decision: str,
        comment: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        with self._lock:
            record = self._state["decisions"].get(decision_id)
            if not record:
                raise KeyError("decision_not_found")
            for approval in record["approvals"]:
                if approval["idempotency_key"] == idempotency_key:
                    return json.loads(json.dumps(record))
            if record["status"] not in {"awaiting_approval", "approved"}:
                raise RuntimeError("decision_not_approvable")
            if approver_id == record["requested_by"]:
                raise ValueError("requester_cannot_self_approve")
            if any(item["approver_id"] == approver_id for item in record["approvals"]):
                raise ValueError("approver_must_be_distinct")
            approval = {
                "approver_id": approver_id,
                "decision": decision,
                "comment": comment,
                "idempotency_key": idempotency_key,
                "approved_at": iso_z(utc_now()),
            }
            record["approvals"].append(approval)
            if decision == "reject":
                record["status"] = "rejected"
            else:
                approved_count = sum(item["decision"] == "approve" for item in record["approvals"])
                record["status"] = (
                    "approved"
                    if approved_count >= record["required_approvals"]
                    else "awaiting_approval"
                )
            record["updated_at"] = iso_z(utc_now())
            self._append_record_event(
                record,
                "approval_recorded",
                {
                    "approver_id": approver_id,
                    "decision": decision,
                    "approval_count": len(record["approvals"]),
                    "required_approvals": record["required_approvals"],
                },
            )
            record["record_sha256"] = self._record_hash(record)
            self._persist()
            return json.loads(json.dumps(record))

    def execute(
        self,
        decision_id: str,
        *,
        idempotency_key: str,
        executor_id: str,
    ) -> dict[str, Any]:
        with self._lock:
            record = self._state["decisions"].get(decision_id)
            if not record:
                raise KeyError("decision_not_found")
            receipt = record.get("execution_receipt")
            if receipt and receipt.get("idempotency_key") == idempotency_key:
                return json.loads(json.dumps(record))
            if record["status"] != "approved":
                raise RuntimeError("decision_not_approved")
            current = self.simulator.snapshot()
            if not current["decision_allowed"]:
                record["status"] = "execution_blocked"
                record["execution_receipt"] = {
                    "status": "rejected",
                    "failure_reason": "runtime_quality_gate_failed",
                    "idempotency_key": idempotency_key,
                    "executed_at": iso_z(utc_now()),
                }
                self._append_record_event(
                    record,
                    "execution_rejected",
                    {"failure_reason": "runtime_quality_gate_failed"},
                )
                record["record_sha256"] = self._record_hash(record)
                self._persist()
                return json.loads(json.dumps(record))
            result = self.simulator.apply_action(record["projected_action"])
            before_kpi = result["before"]["kpis"]["current"]
            after_kpi = result["after"]["kpis"]["current"]
            kpi_delta = {
                key: round(float(after_kpi.get(key, 0.0)) - float(before_kpi.get(key, 0.0)), 6)
                for key in sorted(set(before_kpi) & set(after_kpi))
                if isinstance(before_kpi.get(key), (int, float))
            }
            rollback_action = {
                "battery_power_kw": self._signal(result["before"], "battery.power_kw"),
                "hvac_setpoint_c": self._signal(result["before"], "hvac.setpoint_c"),
                "shore_power_limit_kw": self._signal(result["before"], "shore_power.load_kw"),
                "agv_charging_limit_kw": self._signal(result["before"], "charging.agv_load_kw"),
            }
            record["status"] = "executed_simulation"
            record["updated_at"] = iso_z(utc_now())
            record["execution_receipt"] = {
                "schema_version": "simulation-execution-receipt.v1",
                "status": "acknowledged",
                "ack_id": "ack-"
                + hashlib.sha256(f"{decision_id}:{idempotency_key}".encode("utf-8")).hexdigest()[
                    :24
                ],
                "idempotency_key": idempotency_key,
                "executor_id": executor_id,
                "executed_at": iso_z(utc_now()),
                "mode": "simulation_only",
                "production_dispatch": False,
                "input_snapshot_sha256": current["snapshot_sha256"],
                "result_snapshot_sha256": result["after"]["snapshot_sha256"],
                "applied_action": record["projected_action"],
                "kpi_before": before_kpi,
                "kpi_after": after_kpi,
                "kpi_delta": kpi_delta,
                "failure_reason": None,
            }
            record["rollback"] = {
                "available": True,
                "status": "available",
                "rollback_action": rollback_action,
            }
            self._append_record_event(
                record,
                "simulation_execution_acknowledged",
                {
                    "ack_id": record["execution_receipt"]["ack_id"],
                    "result_snapshot_sha256": result["after"]["snapshot_sha256"],
                    "kpi_delta": kpi_delta,
                },
            )
            record["record_sha256"] = self._record_hash(record)
            self._persist()
            return json.loads(json.dumps(record))

    def rollback(
        self,
        decision_id: str,
        *,
        idempotency_key: str,
        requested_by: str,
        reason: str,
    ) -> dict[str, Any]:
        with self._lock:
            record = self._state["decisions"].get(decision_id)
            if not record:
                raise KeyError("decision_not_found")
            rollback = record.get("rollback") or {}
            if rollback.get("idempotency_key") == idempotency_key:
                return json.loads(json.dumps(record))
            if record["status"] != "executed_simulation" or not rollback.get("available"):
                raise RuntimeError("rollback_not_available")
            safe_action, constraints = self._project_action(
                self.simulator.snapshot(), rollback["rollback_action"]
            )
            result = self.simulator.apply_action(safe_action)
            record["status"] = "rolled_back_simulation"
            record["updated_at"] = iso_z(utc_now())
            record["rollback"] = {
                **rollback,
                "available": False,
                "status": "acknowledged",
                "idempotency_key": idempotency_key,
                "requested_by": requested_by,
                "reason": reason,
                "executed_at": iso_z(utc_now()),
                "applied_action": safe_action,
                "safety_projection": constraints,
                "result_snapshot_sha256": result["after"]["snapshot_sha256"],
            }
            self._append_record_event(
                record,
                "simulation_rollback_acknowledged",
                {
                    "reason": reason,
                    "result_snapshot_sha256": result["after"]["snapshot_sha256"],
                },
            )
            record["record_sha256"] = self._record_hash(record)
            self._persist()
            return json.loads(json.dumps(record))

    def get(self, decision_id: str) -> dict[str, Any]:
        with self._lock:
            record = self._state["decisions"].get(decision_id)
            if not record:
                raise KeyError("decision_not_found")
            return json.loads(json.dumps(record))

    def list(self, limit: int = 50) -> dict[str, Any]:
        with self._lock:
            records = sorted(
                self._state["decisions"].values(),
                key=lambda item: item.get("created_at", ""),
                reverse=True,
            )[: max(1, min(200, int(limit)))]
            return {
                "schema_version": "runtime-decision-list.v1",
                "count": len(records),
                "items": json.loads(json.dumps(records)),
                "production_authority": False,
            }

    def statistics(self) -> dict[str, Any]:
        """Aggregate local review, receipt and latency evidence without upgrading it."""
        with self._lock:
            records = list(self._state["decisions"].values())
            approvals = [approval for record in records for approval in record.get("approvals", [])]
            vetoes = [item for item in approvals if item.get("decision") == "reject"]
            latencies = sorted(
                float(record["decision_latency"]["end_to_end_ms"])
                for record in records
                if record.get("decision_latency", {}).get("end_to_end_ms") is not None
            )

            def percentile(probability: float) -> float | None:
                if not latencies:
                    return None
                index = max(
                    0,
                    min(
                        len(latencies) - 1,
                        int((probability * len(latencies) + 0.999999)) - 1,
                    ),
                )
                return round(latencies[index], 6)

            return {
                "schema_version": "runtime-decision-statistics.v1",
                "decision_count": len(records),
                "review_count": len(approvals),
                "veto_count": len(vetoes),
                "veto_rate": round(len(vetoes) / max(1, len(approvals)), 6),
                "review_reason_complete_rate": round(
                    sum(bool(item.get("comment", "").strip()) for item in approvals)
                    / max(1, len(approvals)),
                    6,
                ),
                "distinct_reviewer_count": len({item.get("approver_id") for item in approvals}),
                "simulation_receipt_count": sum(
                    bool(record.get("execution_receipt")) for record in records
                ),
                "latency_sample_count": len(latencies),
                "latency_p50_ms": percentile(0.50),
                "latency_p95_ms": percentile(0.95),
                "latency_p99_ms": percentile(0.99),
                "evidence_class": "local_simulation_observation",
                "production_qualification_evidence": False,
                "production_authority": False,
            }

    def audit(self, decision_id: str) -> dict[str, Any]:
        record = self.get(decision_id)
        previous = "GENESIS"
        valid = True
        failed_index: int | None = None
        for index, event in enumerate(record["audit_events"]):
            stored = event.get("event_hash")
            bare = {key: value for key, value in event.items() if key != "event_hash"}
            if bare.get("previous_event_hash") != previous or stored != _event_hash(bare):
                valid = False
                failed_index = index
                break
            previous = str(stored)
        return {
            "schema_version": "runtime-decision-audit.v1",
            "decision_id": decision_id,
            "chain_valid": valid,
            "failed_index": failed_index,
            "event_count": len(record["audit_events"]),
            "head_hash": previous,
            "record_sha256_valid": record.get("record_sha256") == self._record_hash(record),
            "events": record["audit_events"],
        }


runtime_decision_service = RuntimeDecisionService(state_path=settings.runtime_state_path)
