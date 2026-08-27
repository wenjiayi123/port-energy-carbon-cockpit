from __future__ import annotations

import base64
import binascii
import hashlib
from itertools import combinations
import json
import math
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from app.core.config import settings
from app.schemas.electrical_network import (
    SOURCE_DOMAINS,
    ElectricalNetworkAssessmentReport,
    ElectricalNetworkAssessmentRequest,
)


REPORT_SCHEMA_VERSION = "port-electrical-network-assessment.v1"


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
    request: ElectricalNetworkAssessmentRequest,
    domain: str,
) -> dict[str, Any]:
    """Return the exact source-owned payload covered by one Ed25519 signature."""
    if domain == "single_line_topology":
        payload: Any = {
            "buses": [item.model_dump(mode="json") for item in request.buses],
            "branches": [item.model_dump(mode="json") for item in request.branches],
            "sources": [item.model_dump(mode="json") for item in request.sources],
            "n_minus_one_scenarios": [
                item.model_dump(mode="json") for item in request.n_minus_one_scenarios
            ],
            "island_scenarios": [
                item.model_dump(mode="json") for item in request.island_scenarios
            ],
        }
    elif domain == "scada_switchgear":
        payload = [item.model_dump(mode="json") for item in request.switches]
    elif domain == "power_quality_meters":
        payload = [
            item.model_dump(mode="json")
            for item in request.power_quality_measurements
        ]
    elif domain == "transformer_monitoring":
        payload = [
            item.model_dump(mode="json")
            for item in request.transformer_thermal_measurements
        ]
    elif domain == "charging_management":
        payload = [item.model_dump(mode="json") for item in request.charging_pools]
    elif domain == "battery_management_system":
        payload = [
            item.model_dump(mode="json") for item in request.storage_warranties
        ]
    else:
        raise ValueError(f"unknown electrical source domain: {domain}")
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
        "passed": bool(passed),
        "evidence": evidence,
    }


class ElectricalNetworkAssessmentService:
    """Evaluate a signed, named electrical network without issuing field commands.

    The calculation uses a deterministic radial LinDistFlow approximation,
    measured harmonic evidence, a first-order transformer thermal model,
    explicit contingency/island studies, Erlang-C charger queues and battery
    warranty envelopes. It is an engineering screening model, not a relay
    coordination, short-circuit or protection-setting tool.
    """

    def __init__(self, *, source_public_keys: dict[str, str] | None = None) -> None:
        self.source_public_keys = dict(
            settings.electrical_source_public_keys
            if source_public_keys is None
            else source_public_keys
        )

    def build_default(self) -> ElectricalNetworkAssessmentReport:
        gate_definitions = [
            ("source_domain_coverage", "六域具名数据覆盖", "未接入单线图、开关柜、电能质量、变压器、充电和电池管理数据"),
            ("source_signatures", "逐源签名与防篡改", "未配置六个现场源系统的可信 Ed25519 公钥"),
            ("source_freshness_alignment", "时间新鲜度与跨源对齐", "公开聚合数据不能证明现场六源时钟对齐"),
            ("topology_reference_integrity", "单线拓扑引用完整性", "没有具名母线、馈线、变压器、开关和电源引用"),
            ("switch_interlock_and_radiality", "开关联锁与辐射运行", "没有开关遥信、保护健康、联锁许可和环网状态"),
            ("bus_voltage_limits", "母线电压约束", "没有现场母线电压或可复算潮流"),
            ("feeder_transformer_loading", "馈线与变压器载荷", "没有支路阻抗、容量与电流方向"),
            ("reactive_power_and_power_factor", "无功与功率因数", "没有现场无功功率和电源无功能力"),
            ("harmonic_distortion", "谐波畸变", "没有分次谐波或总谐波畸变测量"),
            ("transformer_thermal_aging", "变压器热点与热老化", "没有环境温度、油温、绕组温升和热时间常数"),
            ("n_minus_one_resilience", "N-1 故障转供", "没有故障元件和经批准联络开关方案"),
            ("island_operation", "孤岛运行能力", "没有并网点、构网电源、黑启动和能量储备证据"),
            ("charging_queue_service", "充电排队服务", "没有充电枪可用数、到达率和服务时间"),
            ("storage_warranty", "储能质保约束", "没有电池管理系统的荷电、健康、温度、吞吐和循环边界"),
        ]
        payload: dict[str, Any] = {
            "schema_version": REPORT_SCHEMA_VERSION,
            "report_id": "electrical-network:aggregate-public-data-incomplete",
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
            "network_summary": {
                "bus_count": 0,
                "branch_count": 0,
                "switch_count": 0,
                "energized_bus_count": None,
                "minimum_voltage_pu": None,
                "maximum_voltage_pu": None,
                "maximum_branch_loading_pct": None,
                "power_factor": None,
                "maximum_voltage_thd_pct": None,
                "maximum_transformer_hot_spot_c": None,
                "total_loss_of_life_hours": None,
                "n_minus_one_passed": None,
                "island_scenarios_passed": None,
                "maximum_expected_charging_wait_minutes": None,
                "storage_warranty_ready": None,
            },
            "bus_results": [],
            "branch_results": [],
            "harmonic_results": [],
            "transformer_thermal_results": [],
            "n_minus_one_results": [],
            "island_results": [],
            "charging_queue_results": [],
            "storage_warranty_results": [],
            "gates": [
                _gate(gate_id, label, False, evidence)
                for gate_id, label, evidence in gate_definitions
            ],
            "assurance": {
                "calculation_executed": False,
                "source_authenticity_accepted": False,
                "electrical_constraints_passed": False,
                "advisory_assessment_release_allowed": False,
                "protection_study_completed": False,
                "short_circuit_study_completed": False,
                "blocker_codes": [item[0] for item in gate_definitions],
            },
            "production_boundary": self._production_boundary(False),
            "input_evidence_sha256": None,
        }
        payload["evidence_sha256"] = canonical_sha256(payload)
        return ElectricalNetworkAssessmentReport(**payload)

    def evaluate(
        self,
        request: ElectricalNetworkAssessmentRequest,
    ) -> ElectricalNetworkAssessmentReport:
        input_evidence_sha256 = canonical_sha256(request.model_dump(mode="json"))
        reference_ready, reference_evidence = self._reference_integrity(request)

        attestations_by_domain = {item.domain: item for item in request.source_attestations}
        received_domains = set(attestations_by_domain)
        domain_coverage_ready = bool(
            len(request.source_attestations) == len(attestations_by_domain)
            and received_domains == SOURCE_DOMAINS
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
        observed_times = [item.observed_at for item in request.source_attestations]
        source_ages = [
            (request.evaluated_at - item.observed_at).total_seconds()
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

        base_state = self._network_state(request)
        switch_ready = bool(
            reference_ready
            and base_state["switch_states_coherent"]
            and base_state["radial"]
            and base_state["required_buses_energized"]
        )
        measured_voltages = [
            item.measured_voltage_pu for item in request.power_quality_measurements
        ]
        all_voltages = [
            item["voltage_pu"]
            for item in base_state["bus_results"]
            if item["energized"] and item["voltage_pu"] is not None
        ] + measured_voltages
        voltage_ready = bool(
            all_voltages
            and min(all_voltages) >= request.policy.minimum_voltage_pu
            and max(all_voltages) <= request.policy.maximum_voltage_pu
            and base_state["required_buses_energized"]
        )
        loading_ready = bool(
            base_state["maximum_branch_loading_pct"]
            <= request.policy.maximum_branch_loading_pct
            and base_state["source_capacity_ready"]
        )
        reactive_ready = bool(
            base_state["power_factor"] >= request.policy.minimum_power_factor
            and base_state["reactive_capacity_ready"]
        )

        harmonic_results = self._harmonic_results(request)
        harmonic_ready = bool(
            harmonic_results
            and all(item["within_limit"] for item in harmonic_results)
        )
        transformer_results = self._transformer_thermal_results(
            request,
            base_state["branch_results"],
        )
        thermal_ready = bool(
            transformer_results
            and all(item["within_thermal_envelope"] for item in transformer_results)
        )
        n_minus_one_results = self._n_minus_one_results(request)
        n_minus_one_ready = bool(
            n_minus_one_results and all(item["passed"] for item in n_minus_one_results)
        )
        island_results = self._island_results(request)
        island_ready = bool(
            island_results and all(item["passed"] for item in island_results)
        )
        charging_results = self._charging_queue_results(request)
        charging_ready = bool(
            charging_results and all(item["within_service_level"] for item in charging_results)
        )
        storage_results = self._storage_warranty_results(request)
        storage_ready = bool(
            storage_results and all(item["within_warranty"] for item in storage_results)
        )

        gates = [
            _gate(
                "source_domain_coverage",
                "六域具名数据覆盖",
                domain_coverage_ready,
                {
                    "received_domains": sorted(received_domains),
                    "required_domains": sorted(SOURCE_DOMAINS),
                },
            ),
            _gate("source_signatures", "逐源签名与防篡改", signatures_ready, signature_results),
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
                "topology_reference_integrity",
                "单线拓扑引用完整性",
                reference_ready,
                reference_evidence,
            ),
            _gate(
                "switch_interlock_and_radiality",
                "开关联锁与辐射运行",
                switch_ready,
                {
                    "radial": base_state["radial"],
                    "required_buses_energized": base_state["required_buses_energized"],
                    "closed_switches_healthy": base_state["switch_states_coherent"],
                    "cycle_branch_ids": base_state["cycle_branch_ids"],
                },
            ),
            _gate(
                "bus_voltage_limits",
                "母线电压约束",
                voltage_ready,
                {
                    "minimum_voltage_pu": min(all_voltages, default=None),
                    "maximum_voltage_pu": max(all_voltages, default=None),
                    "policy_band_pu": [
                        request.policy.minimum_voltage_pu,
                        request.policy.maximum_voltage_pu,
                    ],
                },
            ),
            _gate(
                "feeder_transformer_loading",
                "馈线与变压器载荷",
                loading_ready,
                {
                    "maximum_loading_pct": base_state["maximum_branch_loading_pct"],
                    "limit_pct": request.policy.maximum_branch_loading_pct,
                    "source_capacity_ready": base_state["source_capacity_ready"],
                },
            ),
            _gate(
                "reactive_power_and_power_factor",
                "无功与功率因数",
                reactive_ready,
                {
                    "power_factor": base_state["power_factor"],
                    "minimum_power_factor": request.policy.minimum_power_factor,
                    "reactive_capacity_ready": base_state["reactive_capacity_ready"],
                },
            ),
            _gate(
                "harmonic_distortion",
                "谐波畸变",
                harmonic_ready,
                {
                    "maximum_voltage_thd_pct": max(
                        (item["accepted_voltage_thd_pct"] for item in harmonic_results),
                        default=None,
                    ),
                    "limit_pct": request.policy.maximum_voltage_thd_pct,
                },
            ),
            _gate(
                "transformer_thermal_aging",
                "变压器热点与热老化",
                thermal_ready,
                {
                    "maximum_hot_spot_c": max(
                        (item["hot_spot_temperature_c"] for item in transformer_results),
                        default=None,
                    ),
                    "loss_of_life_hours": round(
                        sum(item["loss_of_life_hours"] for item in transformer_results),
                        6,
                    ),
                },
            ),
            _gate(
                "n_minus_one_resilience",
                "N-1 故障转供",
                n_minus_one_ready,
                n_minus_one_results,
            ),
            _gate("island_operation", "孤岛运行能力", island_ready, island_results),
            _gate(
                "charging_queue_service",
                "充电排队服务",
                charging_ready,
                charging_results,
            ),
            _gate("storage_warranty", "储能质保约束", storage_ready, storage_results),
        ]
        all_constraints_ready = all(item["passed"] for item in gates[3:])
        status = (
            "blocked"
            if not source_ready
            else "assessment_ready"
            if all_constraints_ready
            else "infeasible"
        )
        blocker_codes = [item["gate_id"] for item in gates if not item["passed"]]
        report_payload: dict[str, Any] = {
            "schema_version": REPORT_SCHEMA_VERSION,
            "report_id": f"electrical-network:{request.assessment_id}",
            "mode": "signed_site_assessment",
            "status": status,
            "source_readiness": {
                "required_domains": sorted(SOURCE_DOMAINS),
                "received_domains": sorted(received_domains),
                "signed_domains": sorted(
                    domain for domain, passed in signature_results.items() if passed
                ),
                "live_verified_domains": sorted(
                    item.domain
                    for item in request.source_attestations
                    if item.live_data_verified
                ),
                "domain_count": len(received_domains),
                "required_domain_count": len(SOURCE_DOMAINS),
                "maximum_observation_skew_seconds": observation_skew_seconds,
            },
            "network_summary": {
                "bus_count": len(request.buses),
                "branch_count": len(request.branches),
                "switch_count": len(request.switches),
                "energized_bus_count": sum(
                    item["energized"] for item in base_state["bus_results"]
                ),
                "minimum_voltage_pu": min(all_voltages, default=None),
                "maximum_voltage_pu": max(all_voltages, default=None),
                "maximum_branch_loading_pct": base_state["maximum_branch_loading_pct"],
                "power_factor": base_state["power_factor"],
                "maximum_voltage_thd_pct": max(
                    (item["accepted_voltage_thd_pct"] for item in harmonic_results),
                    default=None,
                ),
                "maximum_transformer_hot_spot_c": max(
                    (item["hot_spot_temperature_c"] for item in transformer_results),
                    default=None,
                ),
                "total_loss_of_life_hours": round(
                    sum(item["loss_of_life_hours"] for item in transformer_results),
                    6,
                ),
                "n_minus_one_passed": sum(item["passed"] for item in n_minus_one_results),
                "island_scenarios_passed": sum(item["passed"] for item in island_results),
                "maximum_expected_charging_wait_minutes": max(
                    (
                        item["expected_wait_minutes"]
                        for item in charging_results
                        if item["expected_wait_minutes"] is not None
                    ),
                    default=None,
                ),
                "storage_warranty_ready": storage_ready,
            },
            "bus_results": base_state["bus_results"],
            "branch_results": base_state["branch_results"],
            "harmonic_results": harmonic_results,
            "transformer_thermal_results": transformer_results,
            "n_minus_one_results": n_minus_one_results,
            "island_results": island_results,
            "charging_queue_results": charging_results,
            "storage_warranty_results": storage_results,
            "gates": gates,
            "assurance": {
                "calculation_executed": True,
                "calculation_method": "radial_lindistflow_thermal_erlang_c_v1",
                "source_authenticity_accepted": source_ready,
                "electrical_constraints_passed": all_constraints_ready,
                "advisory_assessment_release_allowed": status == "assessment_ready",
                "protection_study_completed": False,
                "short_circuit_study_completed": False,
                "blocker_codes": blocker_codes,
            },
            "production_boundary": self._production_boundary(source_ready),
            "input_evidence_sha256": input_evidence_sha256,
        }
        report_payload["evidence_sha256"] = canonical_sha256(report_payload)
        return ElectricalNetworkAssessmentReport(**report_payload)

    def _reference_integrity(
        self,
        request: ElectricalNetworkAssessmentRequest,
    ) -> tuple[bool, dict[str, Any]]:
        collections = {
            "bus_ids": [item.bus_id for item in request.buses],
            "branch_ids": [item.branch_id for item in request.branches],
            "switch_ids": [item.switch_id for item in request.switches],
            "source_ids": [item.source_id for item in request.sources],
            "meter_ids": [item.meter_id for item in request.power_quality_measurements],
            "transformer_ids": [
                item.transformer_id for item in request.transformer_thermal_measurements
            ],
            "pool_ids": [item.pool_id for item in request.charging_pools],
            "storage_ids": [item.storage_id for item in request.storage_warranties],
            "n_minus_one_ids": [item.scenario_id for item in request.n_minus_one_scenarios],
            "island_ids": [item.scenario_id for item in request.island_scenarios],
        }
        duplicate_ids = {
            name: sorted({value for value in values if values.count(value) > 1})
            for name, values in collections.items()
            if len(values) != len(set(values))
        }
        bus_ids = set(collections["bus_ids"])
        branch_by_id = {item.branch_id: item for item in request.branches}
        switch_ids = set(collections["switch_ids"])
        source_by_id = {item.source_id: item for item in request.sources}
        invalid_references: list[str] = []
        for branch in request.branches:
            if branch.from_bus_id not in bus_ids or branch.to_bus_id not in bus_ids:
                invalid_references.append(f"branch_bus:{branch.branch_id}")
            if branch.switch_id not in switch_ids:
                invalid_references.append(f"branch_switch:{branch.branch_id}")
        for source in request.sources:
            if source.bus_id not in bus_ids:
                invalid_references.append(f"source_bus:{source.source_id}")
        for meter in request.power_quality_measurements:
            if meter.bus_id not in bus_ids:
                invalid_references.append(f"meter_bus:{meter.meter_id}")
        for thermal in request.transformer_thermal_measurements:
            branch = branch_by_id.get(thermal.branch_id)
            if branch is None or branch.branch_type != "transformer":
                invalid_references.append(f"thermal_branch:{thermal.transformer_id}")
        for pool in request.charging_pools:
            if pool.bus_id not in bus_ids:
                invalid_references.append(f"charging_bus:{pool.pool_id}")
        for storage in request.storage_warranties:
            source = source_by_id.get(storage.source_id)
            if (
                storage.bus_id not in bus_ids
                or source is None
                or source.source_type != "storage"
                or source.bus_id != storage.bus_id
            ):
                invalid_references.append(f"storage_source:{storage.storage_id}")
        for scenario in request.n_minus_one_scenarios:
            if scenario.contingency_branch_id not in branch_by_id:
                invalid_references.append(f"n_minus_one_branch:{scenario.scenario_id}")
            if any(item not in switch_ids for item in scenario.approved_tie_switch_ids):
                invalid_references.append(f"n_minus_one_tie:{scenario.scenario_id}")
        for scenario in request.island_scenarios:
            if any(item not in switch_ids for item in scenario.pcc_switch_ids):
                invalid_references.append(f"island_pcc:{scenario.scenario_id}")
        ready = not duplicate_ids and not invalid_references
        return ready, {
            "duplicate_ids": duplicate_ids,
            "invalid_references": sorted(invalid_references),
            "named_asset_counts": {
                "buses": len(request.buses),
                "branches": len(request.branches),
                "switches": len(request.switches),
                "sources": len(request.sources),
            },
        }

    def _network_state(
        self,
        request: ElectricalNetworkAssessmentRequest,
        *,
        switch_overrides: dict[str, bool] | None = None,
        excluded_branch_ids: set[str] | None = None,
        allow_grid_sources: bool = True,
    ) -> dict[str, Any]:
        switch_overrides = switch_overrides or {}
        excluded_branch_ids = excluded_branch_ids or set()
        buses = {item.bus_id: item for item in request.buses}
        switch_map = {item.switch_id: item for item in request.switches}
        active_branches = []
        switch_states_coherent = True
        for branch in request.branches:
            switch = switch_map.get(branch.switch_id)
            if switch is None:
                switch_states_coherent = False
                continue
            closed = switch_overrides.get(switch.switch_id, switch.closed)
            if closed and (not switch.protection_healthy or not switch.interlock_permissive):
                switch_states_coherent = False
            if closed and branch.branch_id not in excluded_branch_ids:
                active_branches.append(branch)

        parent = {bus_id: bus_id for bus_id in buses}

        def find(value: str) -> str:
            while parent[value] != value:
                parent[value] = parent[parent[value]]
                value = parent[value]
            return value

        cycle_branch_ids: list[str] = []
        for branch in active_branches:
            if branch.from_bus_id not in parent or branch.to_bus_id not in parent:
                continue
            left = find(branch.from_bus_id)
            right = find(branch.to_bus_id)
            if left == right:
                cycle_branch_ids.append(branch.branch_id)
            else:
                parent[right] = left

        adjacency: dict[str, list[tuple[str, Any]]] = {bus_id: [] for bus_id in buses}
        for branch in active_branches:
            if branch.from_bus_id in buses and branch.to_bus_id in buses:
                adjacency[branch.from_bus_id].append((branch.to_bus_id, branch))
                adjacency[branch.to_bus_id].append((branch.from_bus_id, branch))

        available_sources = [
            item
            for item in request.sources
            if item.available and (allow_grid_sources or item.source_type != "grid")
        ]
        source_by_bus: dict[str, list[Any]] = {}
        for source in available_sources:
            source_by_bus.setdefault(source.bus_id, []).append(source)
        root_capable_buses = {
            item.bus_id
            for item in available_sources
            if item.source_type == "grid" or item.grid_forming
        }

        visited: set[str] = set()
        bus_results: dict[str, dict[str, Any]] = {}
        branch_results: dict[str, dict[str, Any]] = {}
        source_capacity_ready = True
        reactive_capacity_ready = True
        component_power: list[tuple[float, float]] = []
        for start_bus in sorted(buses):
            if start_bus in visited:
                continue
            component: set[str] = set()
            stack = [start_bus]
            while stack:
                current = stack.pop()
                if current in component:
                    continue
                component.add(current)
                stack.extend(neighbor for neighbor, _ in adjacency[current])
            visited.update(component)
            roots = sorted(component & root_capable_buses)
            if not roots:
                for bus_id in component:
                    bus = buses[bus_id]
                    bus_results[bus_id] = {
                        "bus_id": bus_id,
                        "energized": False,
                        "voltage_pu": None,
                        "active_load_kw": bus.active_load_kw,
                        "reactive_load_kvar": bus.reactive_load_kvar,
                        "critical_active_load_kw": bus.critical_active_load_kw,
                    }
                continue
            grid_roots = [
                source.bus_id
                for source in available_sources
                if source.bus_id in component and source.source_type == "grid"
            ]
            root = sorted(grid_roots or roots)[0]
            tree_parent: dict[str, str | None] = {root: None}
            parent_branch: dict[str, Any] = {}
            order = [root]
            for current in order:
                for neighbor, branch in adjacency[current]:
                    if neighbor in tree_parent:
                        continue
                    tree_parent[neighbor] = current
                    parent_branch[neighbor] = branch
                    order.append(neighbor)
            downstream_p = {
                bus_id: buses[bus_id].active_load_kw for bus_id in component
            }
            downstream_q = {
                bus_id: buses[bus_id].reactive_load_kvar for bus_id in component
            }
            for bus_id in component:
                for source in source_by_bus.get(bus_id, []):
                    if source.source_type != "grid":
                        downstream_p[bus_id] -= source.active_power_kw
                        downstream_q[bus_id] -= source.reactive_power_kvar
            for bus_id in reversed(order[1:]):
                upstream = tree_parent[bus_id]
                if upstream is not None:
                    downstream_p[upstream] += downstream_p[bus_id]
                    downstream_q[upstream] += downstream_q[bus_id]
            required_p = max(downstream_p[root], 0.0)
            required_q = abs(downstream_q[root])
            capacity_p = sum(
                source.maximum_active_power_kw
                for source in available_sources
                if source.bus_id in component
            )
            capacity_q = sum(
                source.maximum_reactive_power_kvar
                for source in available_sources
                if source.bus_id in component
            )
            source_capacity_ready = source_capacity_ready and required_p <= capacity_p + 1e-6
            reactive_capacity_ready = reactive_capacity_ready and required_q <= capacity_q + 1e-6
            component_power.append((required_p, downstream_q[root]))

            voltages = {root: 1.0}
            for bus_id in order:
                bus = buses[bus_id]
                bus_results[bus_id] = {
                    "bus_id": bus_id,
                    "energized": True,
                    "voltage_pu": round(voltages[bus_id], 6),
                    "active_load_kw": bus.active_load_kw,
                    "reactive_load_kvar": bus.reactive_load_kvar,
                    "critical_active_load_kw": bus.critical_active_load_kw,
                }
                for child, branch in adjacency[bus_id]:
                    if tree_parent.get(child) != bus_id:
                        continue
                    p_flow = downstream_p[child]
                    q_flow = downstream_q[child]
                    apparent = math.hypot(p_flow, q_flow)
                    loading_pct = apparent / branch.rating_kva * 100.0
                    voltage_drop = (
                        branch.resistance_pu * p_flow / branch.rating_kva
                        + branch.reactance_pu * q_flow / branch.rating_kva
                    )
                    voltages[child] = voltages[bus_id] - voltage_drop
                    branch_results[branch.branch_id] = {
                        "branch_id": branch.branch_id,
                        "branch_type": branch.branch_type,
                        "from_bus_id": bus_id,
                        "to_bus_id": child,
                        "active_power_kw": round(p_flow, 6),
                        "reactive_power_kvar": round(q_flow, 6),
                        "apparent_power_kva": round(apparent, 6),
                        "loading_pct": round(loading_pct, 6),
                        "energized": True,
                    }

        active_ids = {item.branch_id for item in active_branches}
        for branch in request.branches:
            if branch.branch_id not in branch_results:
                branch_results[branch.branch_id] = {
                    "branch_id": branch.branch_id,
                    "branch_type": branch.branch_type,
                    "from_bus_id": branch.from_bus_id,
                    "to_bus_id": branch.to_bus_id,
                    "active_power_kw": None,
                    "reactive_power_kvar": None,
                    "apparent_power_kva": None,
                    "loading_pct": 0.0,
                    "energized": branch.branch_id in active_ids
                    and bus_results.get(branch.from_bus_id, {}).get("energized", False)
                    and bus_results.get(branch.to_bus_id, {}).get("energized", False),
                }
        total_p = sum(value[0] for value in component_power)
        total_q = sum(value[1] for value in component_power)
        apparent_total = math.hypot(total_p, total_q)
        power_factor = total_p / apparent_total if apparent_total > 1e-9 else 1.0
        required_buses_energized = all(
            not bus.energized_required
            or bus_results.get(bus.bus_id, {}).get("energized", False)
            for bus in request.buses
        )
        total_load = sum(item.active_load_kw for item in request.buses)
        total_critical = sum(item.critical_active_load_kw for item in request.buses)
        energized_load = sum(
            item.active_load_kw
            for item in request.buses
            if bus_results.get(item.bus_id, {}).get("energized", False)
        )
        energized_critical = sum(
            item.critical_active_load_kw
            for item in request.buses
            if bus_results.get(item.bus_id, {}).get("energized", False)
        )
        return {
            "radial": not cycle_branch_ids,
            "cycle_branch_ids": sorted(cycle_branch_ids),
            "switch_states_coherent": switch_states_coherent,
            "required_buses_energized": required_buses_energized,
            "source_capacity_ready": source_capacity_ready,
            "reactive_capacity_ready": reactive_capacity_ready,
            "power_factor": round(power_factor, 6),
            "maximum_branch_loading_pct": max(
                (item["loading_pct"] for item in branch_results.values()),
                default=0.0,
            ),
            "load_coverage_pct": round(energized_load / max(total_load, 1e-9) * 100, 6),
            "critical_load_coverage_pct": round(
                energized_critical / max(total_critical, 1e-9) * 100,
                6,
            ),
            "bus_results": [bus_results[key] for key in sorted(bus_results)],
            "branch_results": [branch_results[key] for key in sorted(branch_results)],
        }

    def _harmonic_results(
        self,
        request: ElectricalNetworkAssessmentRequest,
    ) -> list[dict[str, Any]]:
        results = []
        for meter in request.power_quality_measurements:
            calculated = math.sqrt(sum(value**2 for value in meter.voltage_harmonics_pct.values()))
            accepted = max(calculated, meter.measured_voltage_thd_pct or 0.0)
            results.append(
                {
                    "meter_id": meter.meter_id,
                    "bus_id": meter.bus_id,
                    "harmonic_orders": sorted(meter.voltage_harmonics_pct),
                    "calculated_voltage_thd_pct": round(calculated, 6),
                    "measured_voltage_thd_pct": meter.measured_voltage_thd_pct,
                    "accepted_voltage_thd_pct": round(accepted, 6),
                    "limit_pct": request.policy.maximum_voltage_thd_pct,
                    "within_limit": accepted <= request.policy.maximum_voltage_thd_pct,
                }
            )
        return results

    def _transformer_thermal_results(
        self,
        request: ElectricalNetworkAssessmentRequest,
        branch_results: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        loading = {item["branch_id"]: item["loading_pct"] for item in branch_results}
        interval_hours = request.interval_minutes / 60.0
        results = []
        for item in request.transformer_thermal_measurements:
            load_ratio = max(loading.get(item.branch_id, 0.0) / 100.0, 0.0)
            ultimate_oil_rise = item.rated_top_oil_rise_c * (
                (load_ratio**2 * item.load_loss_ratio + 1)
                / (item.load_loss_ratio + 1)
            ) ** item.oil_exponent
            ultimate_winding_rise = (
                item.rated_winding_hot_spot_rise_c
                * load_ratio ** (2 * item.winding_exponent)
            )
            oil_rise = ultimate_oil_rise + (
                item.initial_top_oil_rise_c - ultimate_oil_rise
            ) * math.exp(-request.interval_minutes / item.top_oil_time_constant_minutes)
            winding_rise = ultimate_winding_rise + (
                item.initial_winding_hot_spot_rise_c - ultimate_winding_rise
            ) * math.exp(-request.interval_minutes / item.winding_time_constant_minutes)
            hot_spot = item.ambient_temperature_c + oil_rise + winding_rise
            aging_factor = 2 ** ((hot_spot - 110.0) / 6.0)
            loss_of_life = aging_factor * interval_hours
            within = bool(
                hot_spot <= request.policy.maximum_transformer_hot_spot_c
                and aging_factor <= request.policy.maximum_aging_acceleration_factor
            )
            results.append(
                {
                    "transformer_id": item.transformer_id,
                    "branch_id": item.branch_id,
                    "load_ratio": round(load_ratio, 6),
                    "top_oil_rise_c": round(oil_rise, 6),
                    "winding_hot_spot_rise_c": round(winding_rise, 6),
                    "hot_spot_temperature_c": round(hot_spot, 6),
                    "aging_acceleration_factor": round(aging_factor, 6),
                    "loss_of_life_hours": round(loss_of_life, 6),
                    "within_thermal_envelope": within,
                }
            )
        return results

    def _n_minus_one_results(
        self,
        request: ElectricalNetworkAssessmentRequest,
    ) -> list[dict[str, Any]]:
        results = []
        switch_by_id = {item.switch_id: item for item in request.switches}
        for scenario in request.n_minus_one_scenarios:
            candidates: list[tuple[str, ...]] = [()]
            ties = scenario.approved_tie_switch_ids
            for size in range(1, min(len(ties), 3) + 1):
                candidates.extend(combinations(ties, size))
            attempts = []
            selected: dict[str, Any] | None = None
            for closed_ties in candidates:
                overrides = {switch_id: True for switch_id in closed_ties}
                state = self._network_state(
                    request,
                    switch_overrides=overrides,
                    excluded_branch_ids={scenario.contingency_branch_id},
                )
                minimum_coverage = max(
                    scenario.minimum_critical_load_coverage_pct,
                    request.policy.minimum_n_minus_one_critical_load_coverage_pct,
                )
                voltages = [
                    item["voltage_pu"]
                    for item in state["bus_results"]
                    if item["energized"] and item["voltage_pu"] is not None
                ]
                feasible = bool(
                    state["radial"]
                    and state["switch_states_coherent"]
                    and state["critical_load_coverage_pct"] >= minimum_coverage
                    and min(voltages, default=0) >= request.policy.minimum_voltage_pu
                    and max(voltages, default=2) <= request.policy.maximum_voltage_pu
                    and state["maximum_branch_loading_pct"]
                    <= request.policy.maximum_branch_loading_pct
                    and state["source_capacity_ready"]
                    and state["reactive_capacity_ready"]
                )
                attempt = {
                    "closed_tie_switch_ids": list(closed_ties),
                    "critical_load_coverage_pct": state["critical_load_coverage_pct"],
                    "maximum_branch_loading_pct": state["maximum_branch_loading_pct"],
                    "minimum_voltage_pu": min(voltages, default=None),
                    "radial": state["radial"],
                    "feasible": feasible,
                }
                attempts.append(attempt)
                if feasible:
                    selected = attempt
                    break
            invalid_ties = [item for item in ties if item not in switch_by_id]
            passed = selected is not None and not invalid_ties
            results.append(
                {
                    "scenario_id": scenario.scenario_id,
                    "contingency_branch_id": scenario.contingency_branch_id,
                    "approved_tie_switch_ids": ties,
                    "selected_restoration": selected,
                    "attempts": attempts,
                    "passed": passed,
                }
            )
        return results

    def _island_results(
        self,
        request: ElectricalNetworkAssessmentRequest,
    ) -> list[dict[str, Any]]:
        results = []
        storage_by_source = {item.source_id: item for item in request.storage_warranties}
        for scenario in request.island_scenarios:
            state = self._network_state(
                request,
                switch_overrides={switch_id: False for switch_id in scenario.pcc_switch_ids},
                allow_grid_sources=False,
            )
            island_sources = [
                source
                for source in request.sources
                if source.available
                and source.source_type != "grid"
                and source.grid_forming
                and source.black_start_capable
            ]
            duration_hours = scenario.duration_minutes / 60.0
            minimum_coverage = max(
                scenario.minimum_critical_load_coverage_pct,
                request.policy.minimum_island_critical_load_coverage_pct,
            )
            generator_energy = sum(
                source.maximum_active_power_kw * duration_hours
                for source in island_sources
                if source.source_type == "generator"
            )
            storage_energy = 0.0
            for source in island_sources:
                warranty = storage_by_source.get(source.source_id)
                if warranty is None:
                    continue
                available_above_minimum = warranty.usable_capacity_kwh * max(
                    warranty.state_of_charge_pct - warranty.minimum_state_of_charge_pct,
                    0,
                ) / 100.0
                storage_energy += max(
                    available_above_minimum - warranty.minimum_island_reserve_kwh,
                    0,
                )
            critical_energy_required = sum(
                bus.critical_active_load_kw for bus in request.buses
            ) * duration_hours * minimum_coverage / 100.0
            voltages = [
                item["voltage_pu"]
                for item in state["bus_results"]
                if item["energized"] and item["voltage_pu"] is not None
            ]
            passed = bool(
                island_sources
                and state["radial"]
                and state["switch_states_coherent"]
                and state["critical_load_coverage_pct"] >= minimum_coverage
                and generator_energy + storage_energy >= critical_energy_required
                and state["source_capacity_ready"]
                and state["reactive_capacity_ready"]
                and min(voltages, default=0) >= request.policy.minimum_voltage_pu
                and max(voltages, default=2) <= request.policy.maximum_voltage_pu
                and state["maximum_branch_loading_pct"]
                <= request.policy.maximum_branch_loading_pct
            )
            results.append(
                {
                    "scenario_id": scenario.scenario_id,
                    "pcc_switch_ids": scenario.pcc_switch_ids,
                    "duration_minutes": scenario.duration_minutes,
                    "grid_forming_black_start_source_ids": [
                        item.source_id for item in island_sources
                    ],
                    "critical_load_coverage_pct": state["critical_load_coverage_pct"],
                    "critical_energy_required_kwh": round(critical_energy_required, 6),
                    "available_island_energy_kwh": round(
                        generator_energy + storage_energy,
                        6,
                    ),
                    "maximum_branch_loading_pct": state["maximum_branch_loading_pct"],
                    "minimum_voltage_pu": min(voltages, default=None),
                    "passed": passed,
                }
            )
        return results

    def _charging_queue_results(
        self,
        request: ElectricalNetworkAssessmentRequest,
    ) -> list[dict[str, Any]]:
        results = []
        for pool in request.charging_pools:
            servers = pool.available_charger_count
            service_rate = 60.0 / pool.mean_service_minutes
            offered_load = pool.arrival_rate_per_hour / service_rate
            utilization = offered_load / servers
            stable = utilization < 1.0
            probability_wait = 1.0
            expected_wait_hours = math.inf
            expected_queue = math.inf
            if stable:
                term = 1.0
                finite_sum = 1.0
                for index in range(1, servers):
                    term *= offered_load / index
                    finite_sum += term
                final_term = term * offered_load / servers / (1.0 - utilization)
                probability_wait = final_term / (finite_sum + final_term)
                expected_wait_hours = probability_wait / (
                    servers * service_rate - pool.arrival_rate_per_hour
                )
                expected_queue = pool.arrival_rate_per_hour * expected_wait_hours
            expected_wait_minutes = expected_wait_hours * 60.0
            within = bool(
                stable
                and utilization * 100 <= request.policy.maximum_charger_utilization_pct
                and expected_wait_minutes
                <= request.policy.maximum_expected_charging_wait_minutes
            )
            results.append(
                {
                    "pool_id": pool.pool_id,
                    "bus_id": pool.bus_id,
                    "installed_chargers": pool.charger_count,
                    "available_chargers": servers,
                    "connected_capacity_kw": round(servers * pool.charger_power_kw, 6),
                    "utilization_pct": round(utilization * 100, 6),
                    "probability_of_wait": round(probability_wait, 6),
                    "expected_wait_minutes": (
                        round(expected_wait_minutes, 6) if math.isfinite(expected_wait_minutes) else None
                    ),
                    "expected_queue_vehicles": (
                        round(expected_queue, 6) if math.isfinite(expected_queue) else None
                    ),
                    "observed_queue_vehicles": pool.observed_queue_vehicles,
                    "stable": stable,
                    "within_service_level": within,
                }
            )
        return results

    def _storage_warranty_results(
        self,
        request: ElectricalNetworkAssessmentRequest,
    ) -> list[dict[str, Any]]:
        interval_hours = request.interval_minutes / 60.0
        results = []
        for item in request.storage_warranties:
            active_power = item.requested_active_power_kw
            throughput = abs(active_power) * interval_hours
            if active_power >= 0:
                soc_delta = -(
                    active_power
                    * interval_hours
                    / item.discharge_efficiency
                    / item.usable_capacity_kwh
                    * 100
                )
            else:
                soc_delta = (
                    -active_power
                    * interval_hours
                    * item.charge_efficiency
                    / item.usable_capacity_kwh
                    * 100
                )
            projected_soc = item.state_of_charge_pct + soc_delta
            projected_daily = item.daily_throughput_kwh + throughput
            projected_cumulative = item.cumulative_throughput_kwh + throughput
            projected_cycles = item.equivalent_full_cycles + throughput / (
                2 * item.usable_capacity_kwh
            )
            active_power_ready = (
                -item.maximum_charge_power_kw
                <= active_power
                <= item.maximum_discharge_power_kw
            )
            reactive_power_ready = (
                abs(item.requested_reactive_power_kvar)
                <= item.maximum_reactive_power_kvar
            )
            available_reserve = item.usable_capacity_kwh * max(
                projected_soc - item.minimum_state_of_charge_pct,
                0,
            ) / 100.0
            checks = {
                "active_power": active_power_ready,
                "reactive_power": reactive_power_ready,
                "state_of_charge": item.minimum_state_of_charge_pct
                <= projected_soc
                <= item.maximum_state_of_charge_pct,
                "state_of_health": item.state_of_health_pct
                >= item.minimum_state_of_health_pct,
                "cell_temperature": item.cell_temperature_c
                <= item.maximum_cell_temperature_c,
                "daily_throughput": projected_daily
                <= item.maximum_daily_throughput_kwh,
                "warranty_throughput": projected_cumulative
                <= item.warranty_throughput_limit_kwh,
                "warranty_cycles": projected_cycles <= item.warranty_cycle_limit,
                "island_reserve": available_reserve
                >= item.minimum_island_reserve_kwh,
            }
            results.append(
                {
                    "storage_id": item.storage_id,
                    "source_id": item.source_id,
                    "projected_state_of_charge_pct": round(projected_soc, 6),
                    "projected_daily_throughput_kwh": round(projected_daily, 6),
                    "projected_cumulative_throughput_kwh": round(projected_cumulative, 6),
                    "projected_equivalent_full_cycles": round(projected_cycles, 6),
                    "available_island_reserve_kwh": round(available_reserve, 6),
                    "checks": checks,
                    "within_warranty": all(checks.values()),
                }
            )
        return results

    def _source_signature_valid(
        self,
        request: ElectricalNetworkAssessmentRequest,
        attestation: Any,
    ) -> bool:
        if attestation is None:
            return False
        expected_hash = canonical_sha256(source_domain_payload(request, attestation.domain))
        if attestation.signed_payload_sha256 != expected_hash:
            return False
        public_key_b64 = self.source_public_keys.get(attestation.key_id)
        if not public_key_b64:
            return False
        try:
            public_key_raw = base64.b64decode(public_key_b64, validate=True)
            signature_raw = base64.b64decode(attestation.signature, validate=True)
            Ed25519PublicKey.from_public_bytes(public_key_raw).verify(
                signature_raw,
                bytes.fromhex(expected_hash),
            )
        except (ValueError, binascii.Error, InvalidSignature):
            return False
        return True

    @staticmethod
    def _production_boundary(live_site_data_verified: bool) -> dict[str, bool]:
        return {
            "simulation_mode": True,
            "live_site_data_verified": live_site_data_verified,
            "advisory_only": True,
            "switching_command_allowed": False,
            "protection_setting_change_allowed": False,
            "islanding_command_allowed": False,
            "equipment_dispatch_allowed": False,
            "production_authority": False,
        }


electrical_network_assessment_service = ElectricalNetworkAssessmentService()
