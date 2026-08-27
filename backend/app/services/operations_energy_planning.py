from __future__ import annotations

import base64
import binascii
from datetime import timedelta
import hashlib
from itertools import combinations
import json
import math
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from app.core.config import settings
from app.schemas.operations_energy_planning import (
    SOURCE_DOMAINS,
    OperationsEnergyPlanningReport,
    OperationsEnergyPlanningRequest,
)


REPORT_SCHEMA_VERSION = "operations-energy-joint-plan.v1"


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def source_domain_payload(
    request: OperationsEnergyPlanningRequest,
    domain: str,
) -> dict[str, Any]:
    """Return the exact domain payload bound by a source-system signature."""
    if domain == "ais_and_vessel_calls":
        payload: Any = [item.model_dump(mode="json") for item in request.vessel_calls]
    elif domain == "berth_plan":
        payload = [item.model_dump(mode="json") for item in request.berths]
    elif domain == "crane_work_orders":
        payload = [item.model_dump(mode="json") for item in request.cranes]
    elif domain == "yard_inventory":
        payload = [item.model_dump(mode="json") for item in request.yard_blocks]
    elif domain == "truck_appointments":
        payload = {
            "truck_gates": [item.model_dump(mode="json") for item in request.truck_gates],
            "appointments": [
                item.model_dump(mode="json") for item in request.truck_appointments
            ],
        }
    elif domain == "reefer_monitoring":
        payload = [item.model_dump(mode="json") for item in request.reefer_batches]
    elif domain == "shore_power_registry":
        payload = {
            "vessels": [
                {
                    "vessel_call_id": item.vessel_call_id,
                    "shore_power_compatible": item.shore_power_compatible,
                    "hotel_load_kw": item.hotel_load_kw,
                    "minimum_shore_energy_kwh": item.minimum_shore_energy_kwh,
                }
                for item in request.vessel_calls
            ],
            "berths": [
                {
                    "berth_id": item.berth_id,
                    "shore_power_available": item.shore_power_available,
                    "shore_power_capacity_kw": item.shore_power_capacity_kw,
                }
                for item in request.berths
            ],
        }
    elif domain == "energy_management_system":
        payload = {
            "energy_slots": [item.model_dump(mode="json") for item in request.energy_slots],
            "storage": request.storage.model_dump(mode="json"),
        }
    else:
        raise ValueError(f"unknown source domain: {domain}")
    return {"domain": domain, "payload": payload}


def _gate(
    gate_id: str,
    label_zh: str,
    passed: bool,
    evidence: Any,
) -> dict[str, Any]:
    return {
        "gate_id": gate_id,
        "label_zh": label_zh,
        "passed": passed,
        "evidence": evidence,
    }


class OperationsEnergyPlanningService:
    """Build a time-indexed business and energy advisory plan.

    Vessel calls, berth windows, named cranes, yard inventory, truck
    appointments, reefer obligations, shore power, grid limits and storage are
    solved on one clock. Source signatures and hard constraints fail closed.
    The resulting plan has no PLC, TOS or equipment execution authority.
    """

    def __init__(self, *, source_public_keys: dict[str, str] | None = None) -> None:
        self.source_public_keys = dict(
            settings.operations_source_public_keys
            if source_public_keys is None
            else source_public_keys
        )

    def build_default(self) -> OperationsEnergyPlanningReport:
        gate_definitions = [
            ("source_domain_coverage", "八域具名数据覆盖", "未接入具名船舶、泊位、岸桥、堆场、集卡、冷藏箱、岸电和能源数据"),
            ("source_signatures", "逐源签名与防篡改", "未配置八个源系统的可信 Ed25519 公钥"),
            ("source_freshness_alignment", "时间新鲜度与跨源对齐", "当前公开聚合数据不能证明现场跨源时间对齐"),
            ("vessel_schedule", "船舶到港与离港窗口", "没有具名船舶预计到港时间和要求离港时间"),
            ("berth_compatibility", "泊位兼容与互斥", "没有船长、泊位窗口和占用互斥证据"),
            ("crane_task_capacity", "具名岸桥任务与能力", "当前只有岸桥资源比例，没有具名任务和作业率"),
            ("yard_inventory_capacity", "堆场库存守恒与容量", "未接入箱位和堆场库存台账"),
            ("truck_appointments", "外集卡预约与闸口能力", "未接入预约窗口、方向、箱量和闸口能力"),
            ("reefer_safety", "冷藏箱连续供电与插座容量", "未接入具名冷藏箱批次和插座状态"),
            ("shore_power_service", "船岸兼容与岸电服务量", "未接入逐船兼容、泊位容量和最小岸电服务量"),
            ("energy_balance_and_grid", "逐时段能量平衡与电网限额", "未建立业务任务负荷到电网时段的可复算平衡"),
            ("storage_soc_and_terminal", "储能荷电状态与期末约束", "未接入现场储能状态、效率和期末荷电要求"),
        ]
        payload: dict[str, Any] = {
            "schema_version": REPORT_SCHEMA_VERSION,
            "report_id": "operations-energy:aggregate-public-data-incomplete",
            "mode": "aggregate_public_scenario",
            "status": "blocked",
            "source_readiness": {
                "required_domains": sorted(SOURCE_DOMAINS),
                "received_domains": [],
                "signed_domains": [],
                "live_verified_domains": [],
                "domain_count": 0,
                "required_domain_count": len(SOURCE_DOMAINS),
                "maximum_observation_skew_seconds": None,
            },
            "horizon": {
                "start_at": None,
                "end_at": None,
                "interval_minutes": None,
                "slot_count": 0,
            },
            "vessel_assignments": [],
            "crane_tasks": [],
            "truck_schedule": [],
            "slot_plan": [],
            "constraint_summary": {
                "unscheduled_vessel_calls": None,
                "unscheduled_truck_appointments": None,
                "yard_capacity_violations": None,
                "reefer_capacity_violations": None,
                "grid_limit_violations": None,
                "storage_soc_violations": None,
            },
            "kpis": {
                "service_coverage_pct": 0.0,
                "truck_appointment_coverage_pct": 0.0,
                "planned_moves_teu": None,
                "shore_energy_kwh": None,
                "grid_energy_kwh": None,
                "renewable_energy_kwh": None,
                "carbon_kg": None,
                "energy_cost_cny": None,
                "peak_grid_import_kw": None,
                "terminal_storage_soc_pct": None,
            },
            "gates": [
                _gate(gate_id, label, False, evidence)
                for gate_id, label, evidence in gate_definitions
            ],
            "assurance": {
                "solver_executed": False,
                "source_authenticity_accepted": False,
                "hard_constraints_passed": False,
                "advisory_plan_release_allowed": False,
                "software_is_terminal_operating_system": False,
                "blocker_codes": [item[0] for item in gate_definitions],
            },
            "production_boundary": {
                "simulation_mode": True,
                "live_site_data_verified": False,
                "advisory_only": True,
                "tos_writeback_allowed": False,
                "equipment_dispatch_allowed": False,
                "production_authority": False,
            },
            "input_evidence_sha256": None,
        }
        payload["evidence_sha256"] = canonical_sha256(payload)
        return OperationsEnergyPlanningReport(**payload)

    def evaluate(
        self,
        request: OperationsEnergyPlanningRequest,
    ) -> OperationsEnergyPlanningReport:
        request_payload = request.model_dump(mode="json")
        input_evidence_sha256 = canonical_sha256(request_payload)
        slot_seconds = request.horizon.interval_minutes * 60
        horizon_end = request.horizon.start_at + timedelta(
            seconds=slot_seconds * request.horizon.slot_count
        )

        identifiers_ready, reference_evidence = self._reference_integrity(request)
        attestations_by_domain = {
            item.domain: item for item in request.source_attestations
        }
        domains_received = set(attestations_by_domain)
        domain_coverage_ready = bool(
            len(request.source_attestations) == len(attestations_by_domain)
            and domains_received == SOURCE_DOMAINS
            and identifiers_ready
        )
        signature_results = {
            domain: self._source_signature_valid(
                request,
                attestations_by_domain.get(domain),
            )
            for domain in sorted(SOURCE_DOMAINS)
        }
        signatures_ready = bool(
            domain_coverage_ready and all(signature_results.values())
        )
        observed_times = [
            item.observed_at for item in request.source_attestations
        ]
        source_ages = [
            (request.requested_at - item.observed_at).total_seconds()
            for item in request.source_attestations
        ]
        observation_skew_seconds = (
            max((max(observed_times) - min(observed_times)).total_seconds(), 0.0)
            if observed_times
            else math.inf
        )
        freshness_ready = bool(
            domain_coverage_ready
            and all(item.live_data_verified for item in request.source_attestations)
            and all(
                0 <= age <= request.policy.maximum_source_age_seconds
                for age in source_ages
            )
            and observation_skew_seconds
            <= request.policy.maximum_source_alignment_seconds
        )
        source_ready = domain_coverage_ready and signatures_ready and freshness_ready

        assignments, unscheduled_calls = self._schedule_vessels(request)
        total_moves = sum(item.total_moves_teu for item in request.vessel_calls)
        planned_moves = sum(item["planned_moves_teu"] for item in assignments)
        service_coverage_pct = round(
            planned_moves / max(total_moves, 1e-9) * 100.0,
            3,
        )
        vessel_schedule_ready = bool(
            not unscheduled_calls
            and service_coverage_pct >= request.policy.minimum_service_coverage_pct
            and all(
                item["start_at"] >= self._iso(request.horizon.start_at)
                and item["completed_at"] <= self._iso(horizon_end)
                for item in assignments
            )
        )

        berth_by_id = {item.berth_id: item for item in request.berths}
        berth_compatibility_ready = bool(
            len(assignments) == len(request.vessel_calls)
            and all(
                berth_by_id[item["berth_id"]].maximum_vessel_length_m
                >= self._vessel_by_id(request, item["vessel_call_id"]).vessel_length_m
                for item in assignments
            )
            and self._no_assignment_overlap(assignments, "berth_id")
        )

        crane_tasks = self._build_crane_tasks(request, assignments)
        crane_capacity_ready = bool(
            len(assignments) == len(request.vessel_calls)
            and self._no_crane_overlap(crane_tasks)
            and math.isclose(
                sum(item["planned_moves_teu"] for item in crane_tasks),
                planned_moves,
                rel_tol=1e-8,
                abs_tol=1e-6,
            )
        )

        truck_schedule, unscheduled_appointments = self._schedule_trucks(
            request,
            assignments,
        )
        truck_total_teu = sum(item.teu for item in request.truck_appointments)
        truck_planned_teu = sum(item["teu"] for item in truck_schedule)
        truck_coverage_pct = round(
            truck_planned_teu / max(truck_total_teu, 1e-9) * 100.0,
            3,
        )
        truck_ready = bool(
            not unscheduled_appointments
            and truck_coverage_pct
            >= request.policy.minimum_truck_appointment_coverage_pct
            and all(item["sequence_valid"] for item in truck_schedule)
        )

        yard_result = self._yard_plan(
            request,
            assignments,
            truck_schedule,
        )
        yard_ready = not yard_result["violations"]

        reefer_result = self._reefer_plan(request)
        reefer_ready = not reefer_result["violations"]

        shore_result = self._shore_plan(request, assignments)
        shore_ready = not shore_result["violations"]

        slot_components = self._slot_components(
            request,
            crane_tasks,
            truck_schedule,
            yard_result,
            reefer_result,
            shore_result,
        )
        storage_result = self._optimize_storage(request, slot_components)
        slot_plan = storage_result["slot_plan"]
        energy_balance_ready = bool(
            len(slot_plan) == request.horizon.slot_count
            and all(abs(item["energy_balance_error_kw"]) <= 1e-6 for item in slot_plan)
            and not storage_result["grid_limit_violations"]
        )
        storage_ready = bool(
            not storage_result["soc_violations"]
            and storage_result["terminal_soc_ready"]
        )

        gates = [
            _gate(
                "source_domain_coverage",
                "八域具名数据覆盖",
                domain_coverage_ready,
                {
                    "received_domains": sorted(domains_received),
                    "required_domains": sorted(SOURCE_DOMAINS),
                    "reference_integrity": reference_evidence,
                },
            ),
            _gate(
                "source_signatures",
                "逐源签名与防篡改",
                signatures_ready,
                signature_results,
            ),
            _gate(
                "source_freshness_alignment",
                "时间新鲜度与跨源对齐",
                freshness_ready,
                {
                    "maximum_age_seconds": max(source_ages, default=None),
                    "observation_skew_seconds": observation_skew_seconds,
                    "all_live_data_verified": all(
                        item.live_data_verified for item in request.source_attestations
                    ),
                },
            ),
            _gate(
                "vessel_schedule",
                "船舶到港与离港窗口",
                vessel_schedule_ready,
                {
                    "service_coverage_pct": service_coverage_pct,
                    "unscheduled_calls": unscheduled_calls,
                },
            ),
            _gate(
                "berth_compatibility",
                "泊位兼容与互斥",
                berth_compatibility_ready,
                [item["berth_id"] for item in assignments],
            ),
            _gate(
                "crane_task_capacity",
                "具名岸桥任务与能力",
                crane_capacity_ready,
                {
                    "task_count": len(crane_tasks),
                    "planned_moves_teu": round(
                        sum(item["planned_moves_teu"] for item in crane_tasks),
                        6,
                    ),
                },
            ),
            _gate(
                "yard_inventory_capacity",
                "堆场库存守恒与容量",
                yard_ready,
                {
                    "violations": yard_result["violations"],
                    "terminal_occupancy_teu": yard_result["terminal_occupancy_teu"],
                },
            ),
            _gate(
                "truck_appointments",
                "外集卡预约与闸口能力",
                truck_ready,
                {
                    "coverage_pct": truck_coverage_pct,
                    "unscheduled_appointments": unscheduled_appointments,
                },
            ),
            _gate(
                "reefer_safety",
                "冷藏箱连续供电与插座容量",
                reefer_ready,
                {"violations": reefer_result["violations"]},
            ),
            _gate(
                "shore_power_service",
                "船岸兼容与岸电服务量",
                shore_ready,
                {
                    "shore_energy_kwh": round(shore_result["total_energy_kwh"], 6),
                    "violations": shore_result["violations"],
                },
            ),
            _gate(
                "energy_balance_and_grid",
                "逐时段能量平衡与电网限额",
                energy_balance_ready,
                {
                    "grid_limit_violations": storage_result["grid_limit_violations"],
                    "maximum_balance_error_kw": max(
                        (abs(item["energy_balance_error_kw"]) for item in slot_plan),
                        default=None,
                    ),
                },
            ),
            _gate(
                "storage_soc_and_terminal",
                "储能荷电状态与期末约束",
                storage_ready,
                {
                    "terminal_soc_pct": storage_result["terminal_soc_pct"],
                    "terminal_minimum_soc_pct": request.storage.terminal_minimum_soc_pct,
                    "violations": storage_result["soc_violations"],
                },
            ),
        ]
        hard_constraints_ready = all(item["passed"] for item in gates[3:])
        plan_ready = source_ready and hard_constraints_ready
        status = (
            "advisory_plan_ready"
            if plan_ready
            else "infeasible"
            if source_ready and not hard_constraints_ready
            else "blocked"
        )
        total_grid_energy = sum(item["grid_energy_kwh"] for item in slot_plan)
        total_renewable_energy = sum(item["renewable_used_kwh"] for item in slot_plan)
        total_carbon = sum(item["carbon_kg"] for item in slot_plan)
        total_cost = sum(item["energy_cost_cny"] for item in slot_plan)

        payload: dict[str, Any] = {
            "schema_version": REPORT_SCHEMA_VERSION,
            "report_id": f"operations-energy:{input_evidence_sha256[:24]}",
            "mode": "signed_site_advisory_evaluation",
            "status": status,
            "source_readiness": {
                "required_domains": sorted(SOURCE_DOMAINS),
                "received_domains": sorted(domains_received),
                "signed_domains": sorted(
                    domain for domain, valid in signature_results.items() if valid
                ),
                "live_verified_domains": sorted(
                    item.domain
                    for item in request.source_attestations
                    if item.live_data_verified
                ),
                "domain_count": len(domains_received),
                "required_domain_count": len(SOURCE_DOMAINS),
                "maximum_observation_skew_seconds": observation_skew_seconds,
            },
            "horizon": {
                "start_at": self._iso(request.horizon.start_at),
                "end_at": self._iso(horizon_end),
                "interval_minutes": request.horizon.interval_minutes,
                "slot_count": request.horizon.slot_count,
            },
            "vessel_assignments": assignments,
            "crane_tasks": crane_tasks,
            "truck_schedule": truck_schedule,
            "slot_plan": slot_plan,
            "constraint_summary": {
                "unscheduled_vessel_calls": unscheduled_calls,
                "unscheduled_truck_appointments": unscheduled_appointments,
                "yard_capacity_violations": yard_result["violations"],
                "reefer_capacity_violations": reefer_result["violations"],
                "shore_power_violations": shore_result["violations"],
                "grid_limit_violations": storage_result["grid_limit_violations"],
                "storage_soc_violations": storage_result["soc_violations"],
            },
            "kpis": {
                "service_coverage_pct": service_coverage_pct,
                "truck_appointment_coverage_pct": truck_coverage_pct,
                "planned_moves_teu": round(planned_moves, 6),
                "shore_energy_kwh": round(shore_result["total_energy_kwh"], 6),
                "grid_energy_kwh": round(total_grid_energy, 6),
                "renewable_energy_kwh": round(total_renewable_energy, 6),
                "carbon_kg": round(total_carbon, 6),
                "energy_cost_cny": round(total_cost, 6),
                "peak_grid_import_kw": round(
                    max((item["grid_import_kw"] for item in slot_plan), default=0.0),
                    6,
                ),
                "terminal_storage_soc_pct": storage_result["terminal_soc_pct"],
            },
            "gates": gates,
            "assurance": {
                "solver_executed": True,
                "source_authenticity_accepted": source_ready,
                "hard_constraints_passed": hard_constraints_ready,
                "advisory_plan_release_allowed": plan_ready,
                "software_is_terminal_operating_system": False,
                "blocker_codes": [
                    item["gate_id"] for item in gates if not item["passed"]
                ],
            },
            "production_boundary": {
                "simulation_mode": False,
                "live_site_data_verified": source_ready,
                "advisory_only": True,
                "tos_writeback_allowed": False,
                "equipment_dispatch_allowed": False,
                "production_authority": False,
            },
            "input_evidence_sha256": input_evidence_sha256,
        }
        payload["evidence_sha256"] = canonical_sha256(payload)
        return OperationsEnergyPlanningReport(**payload)

    @staticmethod
    def _iso(value: Any) -> str:
        return value.isoformat().replace("+00:00", "Z")

    @staticmethod
    def _vessel_by_id(request: OperationsEnergyPlanningRequest, vessel_call_id: str) -> Any:
        return next(
            item for item in request.vessel_calls if item.vessel_call_id == vessel_call_id
        )

    @staticmethod
    def _unique_ids(items: list[Any], attribute: str) -> bool:
        values = [getattr(item, attribute) for item in items]
        return len(values) == len(set(values))

    def _reference_integrity(
        self,
        request: OperationsEnergyPlanningRequest,
    ) -> tuple[bool, dict[str, Any]]:
        vessel_ids = {item.vessel_call_id for item in request.vessel_calls}
        berth_ids = {item.berth_id for item in request.berths}
        yard_ids = {item.yard_block_id for item in request.yard_blocks}
        gate_ids = {item.gate_id for item in request.truck_gates}
        checks = {
            "unique_vessel_calls": self._unique_ids(request.vessel_calls, "vessel_call_id"),
            "unique_berths": self._unique_ids(request.berths, "berth_id"),
            "unique_cranes": self._unique_ids(request.cranes, "crane_id"),
            "unique_yard_blocks": self._unique_ids(request.yard_blocks, "yard_block_id"),
            "unique_truck_gates": self._unique_ids(request.truck_gates, "gate_id"),
            "unique_appointments": self._unique_ids(
                request.truck_appointments, "appointment_id"
            ),
            "unique_reefer_batches": self._unique_ids(request.reefer_batches, "batch_id"),
            "vessel_berth_references": all(
                set(item.candidate_berth_ids) <= berth_ids for item in request.vessel_calls
            ),
            "vessel_yard_references": all(
                set(item.candidate_yard_block_ids) <= yard_ids
                for item in request.vessel_calls
            ),
            "crane_berth_references": all(
                set(item.compatible_berth_ids) <= berth_ids for item in request.cranes
            ),
            "truck_references": all(
                item.vessel_call_id in vessel_ids
                and item.yard_block_id in yard_ids
                and set(item.candidate_gate_ids) <= gate_ids
                for item in request.truck_appointments
            ),
            "reefer_references": all(
                item.vessel_call_id in vessel_ids and item.yard_block_id in yard_ids
                for item in request.reefer_batches
            ),
            "energy_slot_indices": (
                len(request.energy_slots) == request.horizon.slot_count
                and {item.slot_index for item in request.energy_slots}
                == set(range(request.horizon.slot_count))
                and all(
                    item.start_at
                    == request.horizon.start_at
                    + timedelta(
                        minutes=request.horizon.interval_minutes * item.slot_index
                    )
                    for item in request.energy_slots
                )
            ),
        }
        return all(checks.values()), checks

    def _source_signature_valid(
        self,
        request: OperationsEnergyPlanningRequest,
        evidence: Any,
    ) -> bool:
        if evidence is None:
            return False
        public_key_text = self.source_public_keys.get(evidence.key_id, "")
        if not public_key_text:
            return False
        payload_sha256 = canonical_sha256(source_domain_payload(request, evidence.domain))
        if payload_sha256 != evidence.signed_payload_sha256:
            return False
        try:
            public_key_bytes = base64.b64decode(public_key_text, validate=True)
            signature = base64.b64decode(evidence.signature, validate=True)
            Ed25519PublicKey.from_public_bytes(public_key_bytes).verify(
                signature,
                bytes.fromhex(payload_sha256),
            )
        except (ValueError, binascii.Error, InvalidSignature):
            return False
        return True

    def _slot_ceil(self, request: OperationsEnergyPlanningRequest, value: Any) -> int:
        seconds = (value - request.horizon.start_at).total_seconds()
        return math.ceil(seconds / (request.horizon.interval_minutes * 60) - 1e-12)

    def _slot_floor(self, request: OperationsEnergyPlanningRequest, value: Any) -> int:
        seconds = (value - request.horizon.start_at).total_seconds()
        return math.floor(seconds / (request.horizon.interval_minutes * 60) + 1e-12)

    def _schedule_vessels(
        self,
        request: OperationsEnergyPlanningRequest,
    ) -> tuple[list[dict[str, Any]], list[str]]:
        berth_by_id = {item.berth_id: item for item in request.berths}
        yard_by_id = {item.yard_block_id: item for item in request.yard_blocks}
        slot_hours = request.horizon.interval_minutes / 60.0
        states: list[dict[str, Any]] = [
            {
                "score": 0.0,
                "assignments": [],
                "berth_busy": set(),
                "crane_busy": set(),
                "unscheduled": [],
            }
        ]
        vessels = sorted(
            request.vessel_calls,
            key=lambda item: (item.required_departure_at, -item.priority, item.vessel_call_id),
        )
        for vessel in vessels:
            expanded: list[dict[str, Any]] = []
            eta_slot = max(0, self._slot_ceil(request, vessel.eta))
            departure_slot = min(
                request.horizon.slot_count,
                self._slot_floor(request, vessel.required_departure_at),
            )
            for state in states:
                vessel_candidates: list[dict[str, Any]] = []
                for berth_id in vessel.candidate_berth_ids:
                    berth = berth_by_id.get(berth_id)
                    if berth is None or vessel.vessel_length_m > berth.maximum_vessel_length_m:
                        continue
                    berth_start = max(eta_slot, self._slot_ceil(request, berth.available_from))
                    berth_end = min(
                        departure_slot,
                        self._slot_floor(request, berth.available_until),
                    )
                    eligible_cranes = [
                        crane
                        for crane in request.cranes
                        if berth_id in crane.compatible_berth_ids
                    ]
                    maximum_cranes = min(
                        vessel.maximum_cranes,
                        berth.maximum_simultaneous_cranes,
                        len(eligible_cranes),
                    )
                    for crane_count in range(maximum_cranes, vessel.minimum_cranes - 1, -1):
                        for crane_set in combinations(eligible_cranes, crane_count):
                            capacity_per_slot = (
                                sum(item.moves_per_hour for item in crane_set) * slot_hours
                            )
                            duration_slots = math.ceil(
                                vessel.total_moves_teu / max(capacity_per_slot, 1e-9)
                            )
                            for start_slot in range(
                                berth_start,
                                max(berth_start, berth_end - duration_slots) + 1,
                            ):
                                end_slot = start_slot + duration_slots
                                if end_slot > berth_end or end_slot > request.horizon.slot_count:
                                    continue
                                slots = range(start_slot, end_slot)
                                if any((berth_id, slot) in state["berth_busy"] for slot in slots):
                                    continue
                                if any(
                                    (crane.crane_id, slot) in state["crane_busy"]
                                    for crane in crane_set
                                    for slot in slots
                                ):
                                    continue
                                if any(
                                    crane.available_from
                                    > request.horizon.start_at
                                    + timedelta(
                                        minutes=request.horizon.interval_minutes * start_slot
                                    )
                                    or crane.available_until
                                    < request.horizon.start_at
                                    + timedelta(
                                        minutes=request.horizon.interval_minutes * end_slot
                                    )
                                    for crane in crane_set
                                ):
                                    continue
                                remaining = vessel.total_moves_teu
                                slot_moves = []
                                for _slot in slots:
                                    moved = min(remaining, capacity_per_slot)
                                    slot_moves.append(round(moved, 6))
                                    remaining -= moved
                                for yard_block_id in sorted(
                                    vessel.candidate_yard_block_ids,
                                    key=lambda item: (
                                        yard_by_id[item].initial_occupancy_teu
                                        / yard_by_id[item].capacity_teu,
                                        item,
                                    ),
                                ):
                                    wait_minutes = max(
                                        0.0,
                                        (
                                            request.horizon.start_at
                                            + timedelta(
                                                minutes=request.horizon.interval_minutes
                                                * start_slot
                                            )
                                            - vessel.eta
                                        ).total_seconds()
                                        / 60.0,
                                    )
                                    score = (
                                        state["score"]
                                        + wait_minutes
                                        * vessel.priority
                                        * request.policy.delay_weight
                                        + duration_slots
                                        + yard_by_id[yard_block_id].initial_occupancy_teu
                                        / yard_by_id[yard_block_id].capacity_teu
                                    )
                                    assignment = {
                                        "vessel_call_id": vessel.vessel_call_id,
                                        "imo_number": vessel.imo_number,
                                        "berth_id": berth_id,
                                        "yard_block_id": yard_block_id,
                                        "crane_ids": sorted(item.crane_id for item in crane_set),
                                        "start_slot": start_slot,
                                        "end_slot_exclusive": end_slot,
                                        "start_at": self._iso(
                                            request.horizon.start_at
                                            + timedelta(
                                                minutes=request.horizon.interval_minutes
                                                * start_slot
                                            )
                                        ),
                                        "completed_at": self._iso(
                                            request.horizon.start_at
                                            + timedelta(
                                                minutes=request.horizon.interval_minutes
                                                * end_slot
                                            )
                                        ),
                                        "wait_minutes": round(wait_minutes, 3),
                                        "planned_moves_teu": vessel.total_moves_teu,
                                        "import_teu": vessel.import_teu,
                                        "export_teu": vessel.export_teu,
                                        "slot_moves_teu": slot_moves,
                                    }
                                    vessel_candidates.append(
                                        {
                                            "score": score,
                                            "assignments": state["assignments"] + [assignment],
                                            "berth_busy": state["berth_busy"]
                                            | {(berth_id, slot) for slot in slots},
                                            "crane_busy": state["crane_busy"]
                                            | {
                                                (crane.crane_id, slot)
                                                for crane in crane_set
                                                for slot in slots
                                            },
                                            "unscheduled": list(state["unscheduled"]),
                                        }
                                    )
                expanded.extend(vessel_candidates)
            if not expanded:
                states = [
                    {
                        **state,
                        "score": state["score"] + 1_000_000_000.0,
                        "unscheduled": state["unscheduled"] + [vessel.vessel_call_id],
                    }
                    for state in states
                ]
            else:
                states = sorted(
                    expanded,
                    key=lambda item: (
                        len(item["unscheduled"]),
                        item["score"],
                        canonical_sha256(item["assignments"]),
                    ),
                )[: request.policy.berth_beam_width]
        best = min(
            states,
            key=lambda item: (
                len(item["unscheduled"]),
                item["score"],
                canonical_sha256(item["assignments"]),
            ),
        )
        assignments = sorted(best["assignments"], key=lambda item: item["start_slot"])
        return assignments, sorted(best["unscheduled"])

    @staticmethod
    def _no_assignment_overlap(
        assignments: list[dict[str, Any]],
        resource_field: str,
    ) -> bool:
        occupied: set[tuple[str, int]] = set()
        for assignment in assignments:
            for slot in range(
                assignment["start_slot"], assignment["end_slot_exclusive"]
            ):
                key = (assignment[resource_field], slot)
                if key in occupied:
                    return False
                occupied.add(key)
        return True

    def _build_crane_tasks(
        self,
        request: OperationsEnergyPlanningRequest,
        assignments: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        crane_by_id = {item.crane_id: item for item in request.cranes}
        tasks: list[dict[str, Any]] = []
        for assignment in assignments:
            cranes = [crane_by_id[item] for item in assignment["crane_ids"]]
            total_rate = sum(item.moves_per_hour for item in cranes)
            for offset, moves in enumerate(assignment["slot_moves_teu"]):
                slot = assignment["start_slot"] + offset
                allocated = 0.0
                for index, crane in enumerate(cranes):
                    crane_moves = (
                        moves - allocated
                        if index == len(cranes) - 1
                        else moves * crane.moves_per_hour / total_rate
                    )
                    allocated += crane_moves
                    tasks.append(
                        {
                            "task_id": (
                                f"{assignment['vessel_call_id']}:{crane.crane_id}:{slot}"
                            ),
                            "vessel_call_id": assignment["vessel_call_id"],
                            "berth_id": assignment["berth_id"],
                            "crane_id": crane.crane_id,
                            "slot_index": slot,
                            "planned_moves_teu": round(crane_moves, 6),
                            "active_power_kw": crane.active_power_kw,
                        }
                    )
        return tasks

    @staticmethod
    def _no_crane_overlap(tasks: list[dict[str, Any]]) -> bool:
        keys = [(item["crane_id"], item["slot_index"]) for item in tasks]
        return len(keys) == len(set(keys))

    def _schedule_trucks(
        self,
        request: OperationsEnergyPlanningRequest,
        assignments: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], list[str]]:
        assignment_by_call = {item["vessel_call_id"]: item for item in assignments}
        gate_by_id = {item.gate_id: item for item in request.truck_gates}
        used: dict[tuple[str, int], float] = {}
        schedule: list[dict[str, Any]] = []
        unscheduled: list[str] = []
        appointments = sorted(
            request.truck_appointments,
            key=lambda item: (item.window_end, item.appointment_id),
        )
        for appointment in appointments:
            assignment = assignment_by_call.get(appointment.vessel_call_id)
            if assignment is None:
                unscheduled.append(appointment.appointment_id)
                continue
            first_slot = max(0, self._slot_ceil(request, appointment.window_start))
            last_slot = min(
                request.horizon.slot_count - 1,
                self._slot_floor(request, appointment.window_end) - 1,
            )
            slots = list(range(first_slot, last_slot + 1))
            if appointment.direction == "export_dropoff":
                valid_slots = [slot for slot in slots if slot <= assignment["start_slot"]]
                valid_slots.reverse()
            else:
                valid_slots = [
                    slot for slot in slots if slot >= assignment["end_slot_exclusive"]
                ]
            selected: tuple[str, int] | None = None
            for slot in valid_slots:
                for gate_id in appointment.candidate_gate_ids:
                    gate = gate_by_id[gate_id]
                    if used.get((gate_id, slot), 0.0) + appointment.teu <= (
                        gate.maximum_teu_per_slot + 1e-9
                    ):
                        selected = (gate_id, slot)
                        break
                if selected:
                    break
            if selected is None:
                unscheduled.append(appointment.appointment_id)
                continue
            gate_id, slot = selected
            used[(gate_id, slot)] = used.get((gate_id, slot), 0.0) + appointment.teu
            schedule.append(
                {
                    "appointment_id": appointment.appointment_id,
                    "vessel_call_id": appointment.vessel_call_id,
                    "direction": appointment.direction,
                    "yard_block_id": appointment.yard_block_id,
                    "gate_id": gate_id,
                    "slot_index": slot,
                    "scheduled_at": self._iso(
                        request.horizon.start_at
                        + timedelta(
                            minutes=request.horizon.interval_minutes * slot
                        )
                    ),
                    "teu": appointment.teu,
                    "sequence_valid": True,
                    "service_energy_kwh": round(
                        appointment.teu * gate_by_id[gate_id].service_energy_kwh_per_teu,
                        6,
                    ),
                }
            )
        return sorted(schedule, key=lambda item: (item["slot_index"], item["gate_id"])), sorted(unscheduled)

    def _yard_plan(
        self,
        request: OperationsEnergyPlanningRequest,
        assignments: list[dict[str, Any]],
        truck_schedule: list[dict[str, Any]],
    ) -> dict[str, Any]:
        slot_count = request.horizon.slot_count
        delta_by_block = {
            item.yard_block_id: [0.0] * slot_count for item in request.yard_blocks
        }
        handling_by_slot = [0.0] * slot_count
        block_by_id = {item.yard_block_id: item for item in request.yard_blocks}
        for assignment in assignments:
            total = max(assignment["planned_moves_teu"], 1e-9)
            import_ratio = assignment["import_teu"] / total
            export_ratio = assignment["export_teu"] / total
            block = block_by_id[assignment["yard_block_id"]]
            for offset, moves in enumerate(assignment["slot_moves_teu"]):
                slot = assignment["start_slot"] + offset
                delta_by_block[block.yard_block_id][slot] += (
                    moves * import_ratio - moves * export_ratio
                )
                handling_by_slot[slot] += moves * block.handling_energy_kwh_per_teu
        for appointment in truck_schedule:
            direction_factor = 1.0 if appointment["direction"] == "export_dropoff" else -1.0
            delta_by_block[appointment["yard_block_id"]][appointment["slot_index"]] += (
                direction_factor * appointment["teu"]
            )
        violations: list[dict[str, Any]] = []
        occupancy_by_slot: list[dict[str, float]] = [dict() for _ in range(slot_count)]
        terminal: dict[str, float] = {}
        for block in request.yard_blocks:
            occupancy = block.initial_occupancy_teu
            for slot, delta in enumerate(delta_by_block[block.yard_block_id]):
                occupancy += delta
                occupancy_by_slot[slot][block.yard_block_id] = round(occupancy, 6)
                if occupancy < -1e-6 or occupancy > block.capacity_teu + 1e-6:
                    violations.append(
                        {
                            "yard_block_id": block.yard_block_id,
                            "slot_index": slot,
                            "occupancy_teu": round(occupancy, 6),
                            "capacity_teu": block.capacity_teu,
                        }
                    )
            terminal[block.yard_block_id] = round(occupancy, 6)
        return {
            "violations": violations,
            "occupancy_by_slot": occupancy_by_slot,
            "terminal_occupancy_teu": terminal,
            "handling_energy_kwh_by_slot": handling_by_slot,
        }

    def _reefer_plan(self, request: OperationsEnergyPlanningRequest) -> dict[str, Any]:
        block_by_id = {item.yard_block_id: item for item in request.yard_blocks}
        plug_count_by_slot = [dict() for _ in range(request.horizon.slot_count)]
        load_kw_by_slot = [0.0] * request.horizon.slot_count
        violations: list[dict[str, Any]] = []
        for batch in request.reefer_batches:
            start_slot = self._slot_ceil(request, batch.connected_from)
            end_slot = self._slot_floor(request, batch.connected_until)
            if (
                not batch.uninterrupted_service_required
                or start_slot < 0
                or end_slot > request.horizon.slot_count
                or end_slot <= start_slot
            ):
                violations.append(
                    {"batch_id": batch.batch_id, "reason": "invalid_service_window"}
                )
                continue
            for slot in range(start_slot, end_slot):
                current = plug_count_by_slot[slot].get(batch.yard_block_id, 0)
                new_count = current + batch.container_count
                plug_count_by_slot[slot][batch.yard_block_id] = new_count
                load_kw_by_slot[slot] += (
                    batch.container_count * batch.power_kw_per_container
                )
                capacity = block_by_id[batch.yard_block_id].reefer_plug_capacity
                if new_count > capacity:
                    violations.append(
                        {
                            "batch_id": batch.batch_id,
                            "yard_block_id": batch.yard_block_id,
                            "slot_index": slot,
                            "plug_count": new_count,
                            "plug_capacity": capacity,
                        }
                    )
        return {
            "violations": violations,
            "plug_count_by_slot": plug_count_by_slot,
            "load_kw_by_slot": load_kw_by_slot,
        }

    def _shore_plan(
        self,
        request: OperationsEnergyPlanningRequest,
        assignments: list[dict[str, Any]],
    ) -> dict[str, Any]:
        vessel_by_id = {item.vessel_call_id: item for item in request.vessel_calls}
        berth_by_id = {item.berth_id: item for item in request.berths}
        load_kw_by_slot = [0.0] * request.horizon.slot_count
        energy_by_vessel: dict[str, float] = {}
        violations: list[dict[str, Any]] = []
        slot_hours = request.horizon.interval_minutes / 60.0
        for assignment in assignments:
            vessel = vessel_by_id[assignment["vessel_call_id"]]
            berth = berth_by_id[assignment["berth_id"]]
            load_kw = (
                min(vessel.hotel_load_kw, berth.shore_power_capacity_kw)
                if vessel.shore_power_compatible and berth.shore_power_available
                else 0.0
            )
            energy_kwh = (
                load_kw
                * (assignment["end_slot_exclusive"] - assignment["start_slot"])
                * slot_hours
            )
            energy_by_vessel[vessel.vessel_call_id] = round(energy_kwh, 6)
            if energy_kwh + 1e-6 < vessel.minimum_shore_energy_kwh:
                violations.append(
                    {
                        "vessel_call_id": vessel.vessel_call_id,
                        "delivered_energy_kwh": round(energy_kwh, 6),
                        "minimum_energy_kwh": vessel.minimum_shore_energy_kwh,
                    }
                )
            for slot in range(
                assignment["start_slot"], assignment["end_slot_exclusive"]
            ):
                load_kw_by_slot[slot] += load_kw
        return {
            "violations": violations,
            "load_kw_by_slot": load_kw_by_slot,
            "energy_by_vessel": energy_by_vessel,
            "total_energy_kwh": sum(energy_by_vessel.values()),
        }

    def _slot_components(
        self,
        request: OperationsEnergyPlanningRequest,
        crane_tasks: list[dict[str, Any]],
        truck_schedule: list[dict[str, Any]],
        yard_result: dict[str, Any],
        reefer_result: dict[str, Any],
        shore_result: dict[str, Any],
    ) -> list[dict[str, float]]:
        slot_hours = request.horizon.interval_minutes / 60.0
        crane_kw = [0.0] * request.horizon.slot_count
        truck_kw = [0.0] * request.horizon.slot_count
        for task in crane_tasks:
            crane_kw[task["slot_index"]] += task["active_power_kw"]
        for appointment in truck_schedule:
            truck_kw[appointment["slot_index"]] += (
                appointment["service_energy_kwh"] / slot_hours
            )
        components = []
        energy_by_slot = {item.slot_index: item for item in request.energy_slots}
        for slot in range(request.horizon.slot_count):
            yard_kw = yard_result["handling_energy_kwh_by_slot"][slot] / slot_hours
            energy = energy_by_slot[slot]
            components.append(
                {
                    "base_load_kw": energy.base_terminal_load_kw,
                    "crane_load_kw": crane_kw[slot],
                    "yard_load_kw": yard_kw,
                    "truck_gate_load_kw": truck_kw[slot],
                    "reefer_load_kw": reefer_result["load_kw_by_slot"][slot],
                    "shore_power_load_kw": shore_result["load_kw_by_slot"][slot],
                }
            )
        return components

    def _optimize_storage(
        self,
        request: OperationsEnergyPlanningRequest,
        components: list[dict[str, float]],
    ) -> dict[str, Any]:
        storage = request.storage
        slot_hours = request.horizon.interval_minutes / 60.0
        minimum_energy = storage.usable_capacity_kwh * storage.minimum_soc_pct / 100.0
        maximum_energy = storage.usable_capacity_kwh * storage.maximum_soc_pct / 100.0
        initial_energy = storage.usable_capacity_kwh * storage.initial_soc_pct / 100.0
        terminal_minimum_energy = (
            storage.usable_capacity_kwh * storage.terminal_minimum_soc_pct / 100.0
        )
        energy_by_slot = {item.slot_index: item for item in request.energy_slots}
        states: dict[float, tuple[float, list[dict[str, Any]]]] = {
            round(initial_energy, 3): (0.0, [])
        }
        for slot in range(request.horizon.slot_count):
            energy = energy_by_slot[slot]
            operational_load_kw = sum(components[slot].values())
            effective_grid_limit = energy.grid_import_limit_kw * (
                1.0 - request.policy.grid_reserve_margin_pct / 100.0
            )
            required_discharge = max(
                0.0,
                operational_load_kw
                - energy.renewable_available_kw
                - effective_grid_limit,
            )
            powers = {
                -storage.maximum_charge_kw,
                -storage.maximum_charge_kw / 2.0,
                0.0,
                storage.maximum_discharge_kw / 2.0,
                storage.maximum_discharge_kw,
                min(storage.maximum_discharge_kw, required_discharge),
            }
            next_states: dict[float, tuple[float, list[dict[str, Any]]]] = {}
            for stored_energy, (score, path) in states.items():
                for power_kw in powers:
                    if power_kw >= 0:
                        next_energy = stored_energy - (
                            power_kw * slot_hours / storage.discharge_efficiency
                        )
                    else:
                        next_energy = stored_energy + (
                            -power_kw * slot_hours * storage.charge_efficiency
                        )
                    if next_energy < minimum_energy - 1e-9 or next_energy > maximum_energy + 1e-9:
                        continue
                    renewable_used_kw = min(
                        energy.renewable_available_kw,
                        max(0.0, operational_load_kw - power_kw),
                    )
                    grid_import_kw = max(
                        0.0,
                        operational_load_kw - renewable_used_kw - power_kw,
                    )
                    grid_energy_kwh = grid_import_kw * slot_hours
                    carbon_kg = grid_energy_kwh * energy.grid_carbon_kg_per_kwh
                    energy_cost_cny = (
                        grid_energy_kwh * energy.electricity_price_cny_per_kwh
                        + abs(power_kw)
                        * slot_hours
                        * request.policy.battery_degradation_cny_per_kwh
                    )
                    overload_kw = max(0.0, grid_import_kw - effective_grid_limit)
                    next_score = (
                        score
                        + request.policy.cost_weight * energy_cost_cny
                        + request.policy.carbon_weight * carbon_kg
                        + overload_kw * 1_000_000.0
                    )
                    item = {
                        "slot_index": slot,
                        "start_at": self._iso(energy.start_at),
                        **{key: round(value, 6) for key, value in components[slot].items()},
                        "operational_load_kw": round(operational_load_kw, 6),
                        "renewable_available_kw": energy.renewable_available_kw,
                        "renewable_used_kw": round(renewable_used_kw, 6),
                        "storage_power_kw": round(power_kw, 6),
                        "storage_soc_pct": round(
                            next_energy / storage.usable_capacity_kwh * 100.0,
                            6,
                        ),
                        "grid_import_kw": round(grid_import_kw, 6),
                        "effective_grid_limit_kw": round(effective_grid_limit, 6),
                        "grid_energy_kwh": round(grid_energy_kwh, 6),
                        "renewable_used_kwh": round(renewable_used_kw * slot_hours, 6),
                        "carbon_kg": round(carbon_kg, 6),
                        "energy_cost_cny": round(energy_cost_cny, 6),
                        "energy_balance_error_kw": round(
                            grid_import_kw
                            + renewable_used_kw
                            + power_kw
                            - operational_load_kw,
                            9,
                        ),
                    }
                    key = round(next_energy, 3)
                    prior = next_states.get(key)
                    if prior is None or next_score < prior[0]:
                        next_states[key] = (next_score, path + [item])
            states = dict(
                sorted(next_states.items(), key=lambda item: item[1][0])[:800]
            )
        terminal_candidates = [
            (energy, state)
            for energy, state in states.items()
            if energy >= terminal_minimum_energy - 1e-6
        ]
        terminal_ready = bool(terminal_candidates)
        if terminal_candidates:
            terminal_energy, (_, slot_plan) = min(
                terminal_candidates,
                key=lambda item: item[1][0],
            )
        elif states:
            terminal_energy, (_, slot_plan) = max(states.items(), key=lambda item: item[0])
        else:
            terminal_energy, slot_plan = initial_energy, []
        grid_violations = [
            {
                "slot_index": item["slot_index"],
                "grid_import_kw": item["grid_import_kw"],
                "effective_grid_limit_kw": item["effective_grid_limit_kw"],
            }
            for item in slot_plan
            if item["grid_import_kw"] > item["effective_grid_limit_kw"] + 1e-6
        ]
        soc_violations = [
            {"slot_index": item["slot_index"], "storage_soc_pct": item["storage_soc_pct"]}
            for item in slot_plan
            if item["storage_soc_pct"] < storage.minimum_soc_pct - 1e-6
            or item["storage_soc_pct"] > storage.maximum_soc_pct + 1e-6
        ]
        return {
            "slot_plan": slot_plan,
            "grid_limit_violations": grid_violations,
            "soc_violations": soc_violations,
            "terminal_soc_ready": terminal_ready,
            "terminal_soc_pct": round(
                terminal_energy / storage.usable_capacity_kwh * 100.0,
                6,
            ),
        }


operations_energy_planning_service = OperationsEnergyPlanningService(
    source_public_keys=settings.operations_source_public_keys
)
