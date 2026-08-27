from __future__ import annotations

import base64
import binascii
import hashlib
import json
import math
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from app.core.config import settings
from app.schemas.port_collaboration import (
    SOURCE_DOMAINS,
    PortCollaborationReport,
    PortCollaborationRequest,
)


REPORT_SCHEMA_VERSION = "port-call-collaboration.v1"


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
    request: PortCollaborationRequest,
    domain: str,
) -> dict[str, Any]:
    """Return the exact source-owned payload covered by one Ed25519 signature."""
    if domain == "vessel_operator_plan":
        payload: Any = [item.model_dump(mode="json") for item in request.vessel_calls]
    elif domain == "port_call_platform":
        payload = [item.model_dump(mode="json") for item in request.milestones]
    elif domain == "terminal_berth_operations":
        payload = [item.model_dump(mode="json") for item in request.berth_assignments]
    elif domain == "shore_power_operator":
        payload = [
            item.model_dump(mode="json") for item in request.shore_power_reservations
        ]
    elif domain == "alternative_fuel_facility":
        payload = [
            item.model_dump(mode="json") for item in request.alternative_fuel_services
        ]
    elif domain == "port_tariff_authority":
        payload = [item.model_dump(mode="json") for item in request.port_fee_incentives]
    elif domain == "corridor_governance_ledger":
        payload = {
            "policy": request.policy.model_dump(mode="json"),
            "emission_benefit_claims": [
                item.model_dump(mode="json") for item in request.emission_benefit_claims
            ],
            "benefit_sharing": [
                item.model_dump(mode="json") for item in request.benefit_sharing
            ],
            "approvals": [item.model_dump(mode="json") for item in request.approvals],
        }
    else:
        raise ValueError(f"unknown port collaboration source domain: {domain}")
    return {"domain": domain, "payload": payload}


def _gate(gate_id: str, label_zh: str, passed: bool, evidence: Any) -> dict[str, Any]:
    return {
        "gate_id": gate_id,
        "label_zh": label_zh,
        "passed": bool(passed),
        "evidence": evidence,
    }


def _variance_pct(actual: float, expected: float) -> float:
    return abs(actual - expected) / max(abs(actual), abs(expected), 1.0) * 100.0


class PortCollaborationService:
    """Validate ship-port collaboration evidence without issuing operational commands."""

    def __init__(self, source_public_keys: dict[str, str] | None = None) -> None:
        self.source_public_keys = (
            settings.port_collaboration_public_keys
            if source_public_keys is None
            else source_public_keys
        )

    def build_default(
        self,
        *,
        scenario_shore_power_usage_rate: float,
        scenario_vessel_activity_source: str,
    ) -> PortCollaborationReport:
        definitions = [
            ("source_domain_coverage", "七类港航来源齐备", "未接入船公司、港口和走廊治理七类来源"),
            ("source_signatures", "逐源数字签名", "未配置独立来源公钥与签名"),
            ("source_time_and_live", "来源时效、对齐与实数标记", "当前船舶活动是公开日报扩展而非现场协同记录"),
            ("corridor_charter", "绿色航运走廊章程", "未提供获批走廊参与方、规则和分配比例"),
            ("call_identity_and_linkage", "船舶身份与港口调用链", "未提供具名船舶、船公司和全链路记录"),
            ("jit_consent_and_notice", "准时到港协商与接受", "未提供船公司接受和提前通知回执"),
            ("jit_arrival_and_fuel", "到港偏差与航行节能核证", "没有实际到港、航速和燃油证据"),
            ("berth_milestones", "泊位就绪与作业里程碑", "没有港口调用平台和码头时间戳"),
            ("green_berth_priority", "绿色泊位优先级", "未提供透明计分、同组排序和审批证据"),
            ("shore_power_reservation", "岸电预约与兼容", "未提供逐船逐泊位岸电预约"),
            ("shore_power_meter_billing", "岸电计量与结算", "未提供岸电电表、账单和结算回执"),
            ("alternative_fuel_readiness", "替代燃料安全准备度", "未提供许可、库存、设备、人员和应急演练"),
            ("port_fee_incentive", "绿色港口费激励", "未提供正式规则、账单与付款回执"),
            ("benefit_sharing", "船港减排收益分配", "未提供独立核证减排主张和双边结算"),
            ("dual_approval_audit", "港方与船公司双边批准", "未提供职责分离的双方批准记录"),
        ]
        gates = [_gate(gate_id, label, False, reason) for gate_id, label, reason in definitions]
        payload: dict[str, Any] = {
            "schema_version": REPORT_SCHEMA_VERSION,
            "report_id": "port-collaboration:offline-evidence-incomplete",
            "mode": "public_activity_scenario_only",
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
            "corridor": {
                "corridor_id": None,
                "port_id": None,
                "charter_verified": False,
                "participants_accepted": False,
            },
            "port_calls": [],
            "jit_arrival": {
                "scenario_vessel_activity_source": scenario_vessel_activity_source,
                "verified_call_count": None,
                "verified_on_time_rate_pct": None,
                "verified_fuel_savings_tonnes": None,
                "verified_reduction_tco2e": None,
            },
            "green_berth": {
                "verified_assignment_count": None,
                "priority_rule_verified": False,
            },
            "shore_power": {
                "scenario_usage_rate_pct": scenario_shore_power_usage_rate,
                "verified_reservation_count": None,
                "verified_energy_kwh": None,
                "verified_settlement_amount": None,
            },
            "alternative_fuel": {
                "verified_ready_service_count": None,
                "verified_served_quantity_tonnes": None,
            },
            "incentives": {
                "verified_invoice_count": None,
                "verified_discount_amount": None,
            },
            "benefit_sharing": {
                "verified_reduction_tco2e": None,
                "verified_total_benefit_value": None,
                "verified_port_benefit_amount": None,
                "verified_vessel_operator_benefit_amount": None,
            },
            "gates": gates,
            "assurance": {
                "status": "blocked",
                "passed_gate_count": 0,
                "required_gate_count": len(gates),
                "collaboration_verified": False,
                "claim": "public activity scenario retained; no ship-port agreement verified",
            },
            "production_boundary": {
                "advisory_only": True,
                "vessel_speed_instruction_allowed": False,
                "berth_plan_writeback_allowed": False,
                "shore_power_switching_allowed": False,
                "fuel_bunkering_authorization_allowed": False,
                "port_invoice_issue_allowed": False,
                "financial_transfer_allowed": False,
                "production_authority": False,
                "human_acceptance_required": True,
            },
            "input_evidence_sha256": None,
        }
        payload["evidence_sha256"] = canonical_sha256(payload)
        return PortCollaborationReport(**payload)

    def _verify_signatures(
        self,
        request: PortCollaborationRequest,
    ) -> dict[str, bool]:
        results: dict[str, bool] = {}
        for attestation in request.source_attestations:
            digest = canonical_sha256(source_domain_payload(request, attestation.domain))
            public_key_b64 = self.source_public_keys.get(attestation.key_id)
            verified = False
            if public_key_b64 and digest == attestation.signed_payload_sha256:
                try:
                    public_key = Ed25519PublicKey.from_public_bytes(
                        base64.b64decode(public_key_b64, validate=True)
                    )
                    signature = base64.b64decode(attestation.signature, validate=True)
                    public_key.verify(signature, bytes.fromhex(digest))
                    verified = True
                except (ValueError, binascii.Error, InvalidSignature):
                    verified = False
            results[attestation.domain] = verified
        return results

    def evaluate(self, request: PortCollaborationRequest) -> PortCollaborationReport:
        policy = request.policy
        call_ids = [item.vessel_call_id for item in request.vessel_calls]
        call_id_set = set(call_ids)
        received_domains = [item.domain for item in request.source_attestations]
        unique_domains = set(received_domains)
        coverage_ready = unique_domains == SOURCE_DOMAINS and len(received_domains) == len(
            SOURCE_DOMAINS
        )
        signature_results = self._verify_signatures(request)
        signature_ready = coverage_ready and all(
            signature_results.get(domain, False) for domain in SOURCE_DOMAINS
        )
        ages = [
            (request.evaluated_at - item.observed_at).total_seconds()
            for item in request.source_attestations
        ]
        observed = [item.observed_at.timestamp() for item in request.source_attestations]
        skew = max(observed) - min(observed) if observed else math.inf
        time_live_ready = bool(ages) and all(
            0 <= age <= policy.maximum_source_age_seconds for age in ages
        ) and skew <= policy.maximum_source_alignment_seconds and all(
            item.live_data_verified for item in request.source_attestations
        )

        charter_ready = bool(
            policy.window.start_at < policy.window.end_at
            and policy.port_benefit_share_pct + policy.vessel_operator_benefit_share_pct == 100
            and policy.eligible_alternative_fuels
        )
        reference_sets = {
            "milestones": {item.vessel_call_id for item in request.milestones},
            "berth_assignments": {
                item.vessel_call_id for item in request.berth_assignments
            },
            "shore_power": {
                item.vessel_call_id for item in request.shore_power_reservations
            },
            "alternative_fuel": {
                item.vessel_call_id for item in request.alternative_fuel_services
            },
            "port_fee": {item.vessel_call_id for item in request.port_fee_incentives},
            "benefit_sharing": {item.vessel_call_id for item in request.benefit_sharing},
        }
        identity_ready = bool(
            len(call_ids) == len(call_id_set)
            and len({item.imo_number for item in request.vessel_calls}) == len(call_ids)
            and all(values == call_id_set for values in reference_sets.values())
            and all(
                item.destination_port_id == policy.port_id for item in request.vessel_calls
            )
        )

        call_by_id = {item.vessel_call_id: item for item in request.vessel_calls}
        milestone_by_call = {item.vessel_call_id: item for item in request.milestones}
        assignment_by_call = {
            item.vessel_call_id: item for item in request.berth_assignments
        }
        shore_by_call = {
            item.vessel_call_id: item for item in request.shore_power_reservations
        }
        fuel_by_call = {
            item.vessel_call_id: item for item in request.alternative_fuel_services
        }
        jit_rows: list[dict[str, Any]] = []
        jit_consent_ready = True
        jit_performance_ready = True
        for call in request.vessel_calls:
            lead_hours = (call.agreed_arrival_at - call.advice_issued_at).total_seconds() / 3600
            arrival_deviation_minutes = abs(
                (call.actual_arrival_at - call.agreed_arrival_at).total_seconds()
            ) / 60
            planned_hours = lead_hours
            predicted_hours = call.distance_to_go_nm / call.advised_speed_knots
            travel_coherent = abs(predicted_hours - planned_hours) <= max(
                0.5, policy.maximum_arrival_deviation_minutes / 60
            )
            fuel_savings = call.baseline_fuel_tonnes - call.actual_fuel_tonnes
            reduction_tco2e = (
                fuel_savings * policy.marine_fuel_emission_factor_kg_per_tonne / 1000
            )
            consent_ok = bool(
                call.operator_accepted
                and call.advice_issued_at < call.agreed_arrival_at
                and lead_hours >= policy.minimum_advice_lead_hours
            )
            performance_ok = bool(
                arrival_deviation_minutes <= policy.maximum_arrival_deviation_minutes
                and call.advised_speed_knots <= call.baseline_speed_knots
                and call.actual_fuel_tonnes <= call.baseline_fuel_tonnes
                and travel_coherent
                and reduction_tco2e >= 0
            )
            jit_consent_ready = jit_consent_ready and consent_ok
            jit_performance_ready = jit_performance_ready and performance_ok
            jit_rows.append(
                {
                    "vessel_call_id": call.vessel_call_id,
                    "imo_number": call.imo_number,
                    "operator_id": call.vessel_operator_id,
                    "lead_hours": round(lead_hours, 6),
                    "arrival_deviation_minutes": round(arrival_deviation_minutes, 6),
                    "fuel_savings_tonnes": round(fuel_savings, 6),
                    "jit_reduction_tco2e": round(reduction_tco2e, 6),
                    "consent_ready": consent_ok,
                    "performance_ready": performance_ok,
                }
            )

        milestone_rows: list[dict[str, Any]] = []
        milestone_ready = identity_ready
        for call_id in call_id_set:
            call = call_by_id[call_id]
            milestone = milestone_by_call.get(call_id)
            assignment = assignment_by_call.get(call_id)
            row_ready = bool(
                milestone
                and assignment
                and milestone.berth_id == assignment.berth_id
                and policy.window.start_at <= milestone.terminal_ready_at
                and milestone.departure_at <= policy.window.end_at
                and milestone.terminal_ready_at <= call.agreed_arrival_at
                and milestone.berth_window_start_at
                <= milestone.all_fast_at
                <= milestone.berth_window_end_at
                and call.actual_arrival_at <= milestone.all_fast_at
                and milestone.all_fast_at
                <= milestone.cargo_operations_start_at
                <= milestone.cargo_operations_end_at
                <= milestone.departure_at
            )
            milestone_ready = milestone_ready and row_ready
            milestone_rows.append(
                {
                    "vessel_call_id": call_id,
                    "berth_id": milestone.berth_id if milestone else None,
                    "ready": row_ready,
                }
            )

        scores: dict[str, float] = {}
        green_berth_ready = identity_ready
        for item in request.berth_assignments:
            expected_score = (
                policy.jit_priority_points * int(item.jit_eligible)
                + policy.shore_power_priority_points * int(item.shore_power_eligible)
                + policy.alternative_fuel_priority_points
                * int(item.alternative_fuel_eligible)
            )
            scores[item.vessel_call_id] = expected_score
            call = call_by_id.get(item.vessel_call_id)
            shore = shore_by_call.get(item.vessel_call_id)
            fuel = fuel_by_call.get(item.vessel_call_id)
            green_berth_ready = green_berth_ready and bool(
                call
                and shore
                and fuel
                and item.approved
                and item.jit_eligible == call.operator_accepted
                and item.shore_power_eligible
                == (shore.vessel_compatible and shore.berth_compatible)
                and item.alternative_fuel_eligible == (fuel.status in {"ready", "served"})
                and abs(item.declared_priority_score - expected_score) <= 1e-9
                and item.allocation_rule_sha256 == policy.allocation_rule_sha256
            )
        for item in request.berth_assignments:
            cohort = [
                other
                for other in request.berth_assignments
                if other.fairness_cohort_id == item.fairness_cohort_id
            ]
            expected_rank = 1 + sum(
                scores.get(other.vessel_call_id, 0) > scores.get(item.vessel_call_id, 0)
                for other in cohort
            )
            green_berth_ready = green_berth_ready and item.assigned_priority_rank == expected_rank

        shore_rows: list[dict[str, Any]] = []
        shore_reservation_ready = identity_ready
        shore_billing_ready = identity_ready
        for item in request.shore_power_reservations:
            milestone = milestone_by_call.get(item.vessel_call_id)
            duration_hours = (item.service_end_at - item.service_start_at).total_seconds() / 3600
            expected_amount = item.metered_energy_kwh * item.energy_rate_per_kwh + item.connection_fee
            amount_variance = _variance_pct(item.stated_invoice_amount, expected_amount)
            reservation_ok = bool(
                milestone
                and item.berth_id == milestone.berth_id
                and item.vessel_compatible
                and item.berth_compatible
                and item.reserved_capacity_kw <= item.berth_capacity_kw
                and milestone.all_fast_at <= item.service_start_at
                and item.service_end_at <= milestone.departure_at
                and item.metered_energy_kwh
                <= item.reserved_capacity_kw * duration_hours * 1.05
            )
            billing_ok = bool(
                item.currency == policy.currency
                and item.status in {"settled", "paid"}
                and item.settlement_receipt_sha256
                and amount_variance <= policy.maximum_amount_variance_pct
            )
            shore_reservation_ready = shore_reservation_ready and reservation_ok
            shore_billing_ready = shore_billing_ready and billing_ok
            shore_rows.append(
                {
                    "reservation_id": item.reservation_id,
                    "vessel_call_id": item.vessel_call_id,
                    "metered_energy_kwh": item.metered_energy_kwh,
                    "calculated_amount": round(expected_amount, 6),
                    "stated_amount": item.stated_invoice_amount,
                    "amount_variance_pct": round(amount_variance, 6),
                    "reservation_ready": reservation_ok,
                    "billing_ready": billing_ok,
                }
            )

        fuel_rows: list[dict[str, Any]] = []
        alternative_fuel_ready = identity_ready
        for item in request.alternative_fuel_services:
            capacity = item.maximum_transfer_rate_tonnes_per_hour * item.service_hours
            row_ready = bool(
                item.fuel_type in policy.eligible_alternative_fuels
                and item.requested_quantity_tonnes <= item.available_inventory_tonnes
                and item.requested_quantity_tonnes <= capacity
                and item.permit_valid_through >= request.evaluated_at
                and item.compatible_transfer_equipment
                and item.trained_staff_available
                and item.safety_case_approved
                and item.emergency_drill_passed
                and item.risk_assessment_accepted
                and item.status == "served"
                and item.service_receipt_sha256
            )
            alternative_fuel_ready = alternative_fuel_ready and row_ready
            fuel_rows.append(
                {
                    "service_id": item.service_id,
                    "vessel_call_id": item.vessel_call_id,
                    "fuel_type": item.fuel_type,
                    "requested_quantity_tonnes": item.requested_quantity_tonnes,
                    "transfer_capacity_tonnes": round(capacity, 6),
                    "ready": row_ready,
                }
            )

        fee_rows: list[dict[str, Any]] = []
        fee_ready = identity_ready
        for item in request.port_fee_incentives:
            assignment = assignment_by_call.get(item.vessel_call_id)
            eligible_discount = (
                policy.jit_fee_discount_pct * int(bool(assignment and assignment.jit_eligible))
                + policy.shore_power_fee_discount_pct
                * int(bool(assignment and assignment.shore_power_eligible))
                + policy.alternative_fuel_fee_discount_pct
                * int(bool(assignment and assignment.alternative_fuel_eligible))
            )
            expected_discount = min(eligible_discount, policy.maximum_total_fee_discount_pct)
            expected_payable = item.base_port_fee * (1 - expected_discount / 100)
            amount_variance = _variance_pct(item.stated_payable_amount, expected_payable)
            row_ready = bool(
                item.currency == policy.currency
                and item.incentive_rule_sha256 == policy.allocation_rule_sha256
                and abs(item.declared_discount_pct - expected_discount) <= 1e-9
                and amount_variance <= policy.maximum_amount_variance_pct
                and item.status == "paid"
                and item.payment_receipt_sha256
            )
            fee_ready = fee_ready and row_ready
            fee_rows.append(
                {
                    "invoice_id": item.invoice_id,
                    "vessel_call_id": item.vessel_call_id,
                    "base_port_fee": item.base_port_fee,
                    "calculated_discount_pct": round(expected_discount, 6),
                    "calculated_payable_amount": round(expected_payable, 6),
                    "stated_payable_amount": item.stated_payable_amount,
                    "discount_amount": round(item.base_port_fee - expected_payable, 6),
                    "ready": row_ready,
                }
            )

        claim_ids = [item.claim_id for item in request.emission_benefit_claims]
        benefit_rows: list[dict[str, Any]] = []
        benefit_ready = bool(
            len(claim_ids) == len(set(claim_ids))
            and all(
                item.vessel_call_id in call_id_set
                and item.verification_status == "independently_verified"
                for item in request.emission_benefit_claims
            )
        )
        for call_id in call_id_set:
            call_claims = [
                item for item in request.emission_benefit_claims if item.vessel_call_id == call_id
            ]
            categories = [item.category for item in call_claims]
            sharing = next(
                (item for item in request.benefit_sharing if item.vessel_call_id == call_id),
                None,
            )
            jit_row = next(item for item in jit_rows if item["vessel_call_id"] == call_id)
            claimed_reduction = sum(item.verified_reduction_tco2e for item in call_claims)
            jit_claim = next(
                (item for item in call_claims if item.category == "jit_arrival"),
                None,
            )
            expected_total_value = (
                claimed_reduction * sharing.value_per_tco2e if sharing else 0.0
            )
            row_ready = bool(
                sharing
                and set(categories)
                == {"jit_arrival", "shore_power", "alternative_fuel"}
                and len(categories) == len(set(categories))
                and jit_claim
                and _variance_pct(
                    jit_claim.verified_reduction_tco2e,
                    jit_row["jit_reduction_tco2e"],
                )
                <= policy.maximum_amount_variance_pct
                and _variance_pct(sharing.verified_reduction_tco2e, claimed_reduction)
                <= policy.maximum_amount_variance_pct
                and _variance_pct(sharing.total_benefit_value, expected_total_value)
                <= policy.maximum_amount_variance_pct
                and _variance_pct(
                    sharing.port_benefit_amount,
                    expected_total_value * policy.port_benefit_share_pct / 100,
                )
                <= policy.maximum_amount_variance_pct
                and _variance_pct(
                    sharing.vessel_operator_benefit_amount,
                    expected_total_value * policy.vessel_operator_benefit_share_pct / 100,
                )
                <= policy.maximum_amount_variance_pct
                and _variance_pct(
                    sharing.total_benefit_value,
                    sharing.port_benefit_amount + sharing.vessel_operator_benefit_amount,
                )
                <= policy.maximum_amount_variance_pct
                and sharing.currency == policy.currency
                and sharing.status == "settled"
                and sharing.settlement_receipt_sha256
            )
            benefit_ready = benefit_ready and row_ready
            benefit_rows.append(
                {
                    "vessel_call_id": call_id,
                    "claim_ids": [item.claim_id for item in call_claims],
                    "verified_reduction_tco2e": round(claimed_reduction, 6),
                    "calculated_total_benefit_value": round(expected_total_value, 6),
                    "stated_total_benefit_value": sharing.total_benefit_value
                    if sharing
                    else None,
                    "ready": row_ready,
                }
            )

        approval_roles = {item.role for item in request.approvals if item.decision == "approved"}
        approvers = [item.approver_id for item in request.approvals]
        dual_approval_ready = bool(
            len(request.approvals) == 2
            and approval_roles == {"port_authority", "vessel_operator"}
            and len(approvers) == len(set(approvers))
            and all(item.charter_sha256 == policy.charter_sha256 for item in request.approvals)
        )

        gates = [
            _gate(
                "source_domain_coverage",
                "七类港航来源齐备",
                coverage_ready,
                {"received": sorted(unique_domains), "required": sorted(SOURCE_DOMAINS)},
            ),
            _gate("source_signatures", "逐源数字签名", signature_ready, signature_results),
            _gate(
                "source_time_and_live",
                "来源时效、对齐与实数标记",
                time_live_ready,
                {
                    "ages_seconds": [round(value, 3) for value in ages],
                    "observation_skew_seconds": round(skew, 3)
                    if math.isfinite(skew)
                    else None,
                },
            ),
            _gate("corridor_charter", "绿色航运走廊章程", charter_ready, policy.corridor_id),
            _gate(
                "call_identity_and_linkage",
                "船舶身份与港口调用链",
                identity_ready,
                {
                    "call_ids": sorted(call_id_set),
                    "reference_sets": {
                        name: sorted(values) for name, values in reference_sets.items()
                    },
                },
            ),
            _gate(
                "jit_consent_and_notice",
                "准时到港协商与接受",
                jit_consent_ready,
                jit_rows,
            ),
            _gate(
                "jit_arrival_and_fuel",
                "到港偏差与航行节能核证",
                jit_performance_ready,
                jit_rows,
            ),
            _gate("berth_milestones", "泊位就绪与作业里程碑", milestone_ready, milestone_rows),
            _gate(
                "green_berth_priority",
                "绿色泊位优先级",
                green_berth_ready,
                {"scores": scores},
            ),
            _gate(
                "shore_power_reservation",
                "岸电预约与兼容",
                shore_reservation_ready,
                shore_rows,
            ),
            _gate(
                "shore_power_meter_billing",
                "岸电计量与结算",
                shore_billing_ready,
                shore_rows,
            ),
            _gate(
                "alternative_fuel_readiness",
                "替代燃料安全准备度",
                alternative_fuel_ready,
                fuel_rows,
            ),
            _gate("port_fee_incentive", "绿色港口费激励", fee_ready, fee_rows),
            _gate("benefit_sharing", "船港减排收益分配", benefit_ready, benefit_rows),
            _gate(
                "dual_approval_audit",
                "港方与船公司双边批准",
                dual_approval_ready,
                {"roles": sorted(approval_roles), "approvers": approvers},
            ),
        ]
        all_ready = all(item["passed"] for item in gates)
        calculation_ready = all(item["passed"] for item in gates[3:])
        if all_ready:
            status = "evidence_package_passed"
        elif calculation_ready:
            status = "reconciled_pending_source_attestation"
        else:
            status = "blocked"

        input_evidence_sha256 = canonical_sha256(request.model_dump(mode="json"))
        total_fuel_savings = sum(item["fuel_savings_tonnes"] for item in jit_rows)
        total_jit_reduction = sum(item["jit_reduction_tco2e"] for item in jit_rows)
        total_shore_energy = sum(item.metered_energy_kwh for item in request.shore_power_reservations)
        total_shore_amount = sum(
            item.stated_invoice_amount for item in request.shore_power_reservations
        )
        total_fuel_quantity = sum(
            item.requested_quantity_tonnes for item in request.alternative_fuel_services
        )
        total_discount = sum(item["discount_amount"] for item in fee_rows)
        total_benefit_reduction = sum(
            item.verified_reduction_tco2e for item in request.benefit_sharing
        )
        total_benefit_value = sum(item.total_benefit_value for item in request.benefit_sharing)
        total_port_benefit = sum(item.port_benefit_amount for item in request.benefit_sharing)
        total_vessel_benefit = sum(
            item.vessel_operator_benefit_amount for item in request.benefit_sharing
        )

        payload: dict[str, Any] = {
            "schema_version": REPORT_SCHEMA_VERSION,
            "report_id": f"port-collaboration:{request.case_id}:{input_evidence_sha256[:16]}",
            "mode": "signed_ship_port_collaboration_evidence",
            "status": status,
            "source_readiness": {
                "required_domains": sorted(SOURCE_DOMAINS),
                "received_domains": sorted(unique_domains),
                "signed_domains": sorted(
                    domain for domain, verified in signature_results.items() if verified
                ),
                "live_verified_domains": sorted(
                    item.domain for item in request.source_attestations if item.live_data_verified
                ),
                "domain_count": len(unique_domains),
                "required_domain_count": len(SOURCE_DOMAINS),
                "maximum_observation_skew_seconds": round(skew, 6)
                if math.isfinite(skew)
                else None,
            },
            "corridor": {
                "corridor_id": policy.corridor_id,
                "port_id": policy.port_id,
                "window_id": policy.window.window_id,
                "charter_sha256": policy.charter_sha256,
                "charter_verified": all_ready,
                "participants_accepted": bool(all_ready and dual_approval_ready),
            },
            "port_calls": [
                {**row, "verified": all_ready} for row in jit_rows
            ],
            "jit_arrival": {
                "calculated_call_count": len(jit_rows),
                "calculated_on_time_rate_pct": round(
                    sum(
                        row["arrival_deviation_minutes"]
                        <= policy.maximum_arrival_deviation_minutes
                        for row in jit_rows
                    )
                    / len(jit_rows)
                    * 100,
                    6,
                ),
                "calculated_fuel_savings_tonnes": round(total_fuel_savings, 6),
                "calculated_reduction_tco2e": round(total_jit_reduction, 6),
                "verified_call_count": len(jit_rows) if all_ready else None,
                "verified_on_time_rate_pct": 100.0 if all_ready else None,
                "verified_fuel_savings_tonnes": round(total_fuel_savings, 6)
                if all_ready
                else None,
                "verified_reduction_tco2e": round(total_jit_reduction, 6)
                if all_ready
                else None,
            },
            "green_berth": {
                "calculated_assignment_count": len(request.berth_assignments),
                "scores": scores,
                "verified_assignment_count": len(request.berth_assignments)
                if all_ready
                else None,
                "priority_rule_verified": bool(all_ready and green_berth_ready),
            },
            "shore_power": {
                "reservations": shore_rows,
                "calculated_reservation_count": len(shore_rows),
                "calculated_energy_kwh": round(total_shore_energy, 6),
                "calculated_settlement_amount": round(total_shore_amount, 6),
                "verified_reservation_count": len(shore_rows) if all_ready else None,
                "verified_energy_kwh": round(total_shore_energy, 6) if all_ready else None,
                "verified_settlement_amount": round(total_shore_amount, 6)
                if all_ready
                else None,
                "currency": policy.currency,
            },
            "alternative_fuel": {
                "services": fuel_rows,
                "calculated_ready_service_count": sum(item["ready"] for item in fuel_rows),
                "calculated_served_quantity_tonnes": round(total_fuel_quantity, 6),
                "verified_ready_service_count": len(fuel_rows) if all_ready else None,
                "verified_served_quantity_tonnes": round(total_fuel_quantity, 6)
                if all_ready
                else None,
            },
            "incentives": {
                "invoices": fee_rows,
                "calculated_invoice_count": len(fee_rows),
                "calculated_discount_amount": round(total_discount, 6),
                "verified_invoice_count": len(fee_rows) if all_ready else None,
                "verified_discount_amount": round(total_discount, 6) if all_ready else None,
                "currency": policy.currency,
            },
            "benefit_sharing": {
                "allocations": benefit_rows,
                "calculated_reduction_tco2e": round(total_benefit_reduction, 6),
                "calculated_total_benefit_value": round(total_benefit_value, 6),
                "calculated_port_benefit_amount": round(total_port_benefit, 6),
                "calculated_vessel_operator_benefit_amount": round(total_vessel_benefit, 6),
                "verified_reduction_tco2e": round(total_benefit_reduction, 6)
                if all_ready
                else None,
                "verified_total_benefit_value": round(total_benefit_value, 6)
                if all_ready
                else None,
                "verified_port_benefit_amount": round(total_port_benefit, 6)
                if all_ready
                else None,
                "verified_vessel_operator_benefit_amount": round(total_vessel_benefit, 6)
                if all_ready
                else None,
                "currency": policy.currency,
            },
            "gates": gates,
            "assurance": {
                "status": "passed" if all_ready else "blocked",
                "passed_gate_count": sum(item["passed"] for item in gates),
                "required_gate_count": len(gates),
                "calculation_ready": calculation_ready,
                "collaboration_verified": all_ready,
                "software_is_port_call_platform": False,
                "software_is_bunkering_authority": False,
                "claim": "signed collaboration package reconciled" if all_ready else "claim withheld",
            },
            "production_boundary": {
                "advisory_only": True,
                "vessel_speed_instruction_allowed": False,
                "berth_plan_writeback_allowed": False,
                "shore_power_switching_allowed": False,
                "fuel_bunkering_authorization_allowed": False,
                "port_invoice_issue_allowed": False,
                "financial_transfer_allowed": False,
                "production_authority": False,
                "human_acceptance_required": True,
            },
            "input_evidence_sha256": input_evidence_sha256,
        }
        payload["evidence_sha256"] = canonical_sha256(payload)
        return PortCollaborationReport(**payload)


port_collaboration_service = PortCollaborationService()
