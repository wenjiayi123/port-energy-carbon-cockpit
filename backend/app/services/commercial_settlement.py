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
from app.schemas.commercial_settlement import (
    SOURCE_DOMAINS,
    CommercialSettlementReport,
    CommercialSettlementRequest,
)


REPORT_SCHEMA_VERSION = "commercial-settlement-assessment.v1"


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
    request: CommercialSettlementRequest,
    domain: str,
) -> dict[str, Any]:
    """Return the exact source-owned payload covered by one Ed25519 signature."""
    if domain == "utility_tariff_invoice":
        payload: Any = {
            "tariff": request.tariff.model_dump(mode="json"),
            "utility_invoice": request.utility_invoice.model_dump(mode="json"),
        }
    elif domain == "revenue_metering":
        payload = [item.model_dump(mode="json") for item in request.meter_intervals]
    elif domain == "demand_response":
        payload = [
            item.model_dump(mode="json") for item in request.demand_response_settlements
        ]
    elif domain == "ancillary_services":
        payload = [
            item.model_dump(mode="json") for item in request.ancillary_service_settlements
        ]
    elif domain == "power_purchase_agreement":
        payload = request.ppa.model_dump(mode="json")
    elif domain == "renewable_certificate_registry":
        payload = [
            item.model_dump(mode="json") for item in request.renewable_certificates
        ]
    elif domain == "tenant_billing":
        payload = [item.model_dump(mode="json") for item in request.tenant_allocations]
    elif domain == "investment_and_mv":
        payload = {
            "measurement_verification": request.measurement_verification.model_dump(mode="json"),
            "investment_measures": [
                item.model_dump(mode="json") for item in request.investment_measures
            ],
            "approvals": [item.model_dump(mode="json") for item in request.approvals],
        }
    else:
        raise ValueError(f"unknown commercial settlement source domain: {domain}")
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


def _annuity_factor(rate: float, years: int) -> float:
    if rate == 0:
        return 1.0 / years
    growth = (1.0 + rate) ** years
    return rate * growth / (growth - 1.0)


class CommercialSettlementService:
    """Reconcile signed commercial evidence without moving money or issuing invoices."""

    def __init__(self, source_public_keys: dict[str, str] | None = None) -> None:
        self.source_public_keys = (
            settings.commercial_settlement_public_keys
            if source_public_keys is None
            else source_public_keys
        )

    def build_default(
        self,
        *,
        scenario_cost_difference_cny: float,
        scenario_carbon_price_cny_per_ton: float,
    ) -> CommercialSettlementReport:
        gate_definitions = [
            ("source_domain_coverage", "八类商业来源齐备", "未接入八类商业来源"),
            ("source_signatures", "逐源数字签名", "未配置独立来源公钥与签名"),
            ("source_time_and_live", "来源时效、对齐与实数标记", "当前是离线情景而非现场记录"),
            ("tariff_contract", "生效分时电价合同", "区域代理电价不是码头合同电价"),
            ("revenue_meter_quality", "收入电表完整性", "未提供收入级区间计量"),
            ("utility_invoice_reconciliation", "电量、需量与账单重构", "未提供可重构公用事业账单"),
            ("utility_payment_receipt", "账单付款回执", "未提供到账或付款回执"),
            ("demand_response_settlement", "需求响应结算", "现有收益是工程估算"),
            ("ancillary_service_settlement", "辅助服务结算", "未接入市场运营方结算单"),
            ("ppa_settlement", "购电协议交付与结算", "未提供购电协议及交付账单"),
            ("renewable_certificate_registry", "绿证登记与注销", "未提供唯一序列和注销回执"),
            ("tenant_allocation", "租户分摊与开票对账", "未提供租户分表和分摊台账"),
            ("measurement_verification_link", "量测核证哈希引用", "离线策略差值不是现场核证节能量"),
            ("investment_approval", "投资与运维成本批准", "未提供获批资本开支和运维台账"),
            ("payback_and_macc", "回收期与边际减排成本", "缺少可核证现金流和减排量"),
            ("dual_approval_audit", "财务与能源双人审批", "未提供职责分离审批记录"),
        ]
        gates = [_gate(gate_id, label, False, reason) for gate_id, label, reason in gate_definitions]
        payload: dict[str, Any] = {
            "schema_version": REPORT_SCHEMA_VERSION,
            "report_id": "commercial-settlement:offline-evidence-incomplete",
            "mode": "scenario_estimates_only",
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
            "billing": {
                "tariff_basis": "scenario:regional_public_price_proxy",
                "scenario_cost_difference_cny": round(scenario_cost_difference_cny, 6),
                "verified_utility_invoice_total": None,
                "verified_meter_energy_kwh": None,
                "verified_peak_demand_kw": None,
                "verified_payment": False,
            },
            "market_settlements": {
                "demand_response_basis": "scenario:engineering_avoided_cost",
                "verified_demand_response_revenue": None,
                "verified_ancillary_service_revenue": None,
                "verified_ppa_cost": None,
            },
            "renewable_procurement": {
                "retired_certificate_mwh": None,
                "certificate_cost": None,
                "registry_retirement_verified": False,
            },
            "tenant_allocation": {
                "tenant_count": 0,
                "verified_allocated_total": None,
                "reconciled": False,
            },
            "measurement_verification": {
                "linked_report_id": None,
                "linked_report_sha256": None,
                "independently_reviewed": False,
                "verified_energy_savings_kwh": None,
                "verified_carbon_reduction_tco2e": None,
            },
            "investment_economics": {
                "scenario_carbon_price_cny_per_ton": scenario_carbon_price_cny_per_ton,
                "measure_count": 0,
                "verified_portfolio_simple_payback_years": None,
                "verified_macc": [],
                "currency": None,
            },
            "gates": gates,
            "assurance": {
                "status": "blocked",
                "passed_gate_count": 0,
                "required_gate_count": len(gates),
                "commercial_settlement_verified": False,
                "claim": "scenario values retained separately; no bill or market settlement verified",
            },
            "production_boundary": {
                "advisory_only": True,
                "payment_instruction_allowed": False,
                "market_bid_allowed": False,
                "certificate_trade_allowed": False,
                "tenant_invoice_issue_allowed": False,
                "accounting_posting_allowed": False,
                "production_authority": False,
                "human_release_required": True,
            },
            "input_evidence_sha256": None,
        }
        payload["evidence_sha256"] = canonical_sha256(payload)
        return CommercialSettlementReport(**payload)

    def _verify_signatures(
        self,
        request: CommercialSettlementRequest,
    ) -> dict[str, bool]:
        results: dict[str, bool] = {}
        for attestation in request.source_attestations:
            payload_digest = canonical_sha256(source_domain_payload(request, attestation.domain))
            public_key_b64 = self.source_public_keys.get(attestation.key_id)
            verified = False
            if public_key_b64 and payload_digest == attestation.signed_payload_sha256:
                try:
                    public_key = Ed25519PublicKey.from_public_bytes(
                        base64.b64decode(public_key_b64, validate=True)
                    )
                    signature = base64.b64decode(attestation.signature, validate=True)
                    public_key.verify(signature, bytes.fromhex(payload_digest))
                    verified = True
                except (ValueError, binascii.Error, InvalidSignature):
                    verified = False
            results[attestation.domain] = verified
        return results

    def evaluate(self, request: CommercialSettlementRequest) -> CommercialSettlementReport:
        policy = request.policy
        period = policy.settlement_period
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
        observation_skew = max(observed) - min(observed) if observed else math.inf
        time_live_ready = bool(ages) and all(
            0 <= age <= policy.maximum_source_age_seconds for age in ages
        ) and observation_skew <= policy.maximum_source_alignment_seconds and all(
            item.live_data_verified for item in request.source_attestations
        )

        rate_by_period = {
            item.period_code: item.energy_rate_per_kwh for item in request.tariff.period_rates
        }
        tariff_ready = bool(
            request.tariff.currency == policy.currency
            and request.tariff.effective_from <= period.start_at
            and request.tariff.effective_through >= period.end_at
            and request.utility_invoice.currency == policy.currency
            and request.utility_invoice.billing_start_at == period.start_at
            and request.utility_invoice.billing_end_at == period.end_at
            and all(item.tariff_period in rate_by_period for item in request.meter_intervals)
        )

        interval_ids = [item.interval_id for item in request.meter_intervals]
        measured_count = sum(item.quality == "measured" for item in request.meter_intervals)
        coverage_pct = measured_count / policy.expected_meter_intervals * 100.0
        meter_ready = bool(
            len(interval_ids) == len(set(interval_ids))
            and len(request.meter_intervals) == policy.expected_meter_intervals
            and coverage_pct >= policy.minimum_measured_coverage_pct
            and all(
                item.quality == "measured"
                and item.meter_id == request.utility_invoice.revenue_meter_id
                and period.start_at <= item.start_at < item.end_at <= period.end_at
                for item in request.meter_intervals
            )
        )

        meter_energy = sum(item.energy_kwh for item in request.meter_intervals)
        meter_peak = max((item.demand_kw for item in request.meter_intervals), default=0.0)
        expected_energy_charge = sum(
            item.energy_kwh * rate_by_period.get(item.tariff_period, 0.0)
            for item in request.meter_intervals
        )
        expected_demand_charge = meter_peak * request.tariff.demand_charge_per_kw
        expected_fixed_charge = request.tariff.fixed_charge
        expected_tax_charge = (
            expected_energy_charge + expected_demand_charge + expected_fixed_charge
        ) * request.tariff.tax_rate_pct / 100.0
        expected_invoice_total = (
            expected_energy_charge
            + expected_demand_charge
            + expected_fixed_charge
            + expected_tax_charge
        )
        invoice = request.utility_invoice
        invoice_variances = {
            "energy_quantity_pct": _variance_pct(invoice.billed_energy_kwh, meter_energy),
            "demand_quantity_pct": _variance_pct(invoice.billed_peak_demand_kw, meter_peak),
            "energy_charge_pct": _variance_pct(invoice.energy_charge, expected_energy_charge),
            "demand_charge_pct": _variance_pct(invoice.demand_charge, expected_demand_charge),
            "fixed_charge_pct": _variance_pct(invoice.fixed_charge, expected_fixed_charge),
            "tax_charge_pct": _variance_pct(invoice.tax_charge, expected_tax_charge),
            "total_amount_pct": _variance_pct(invoice.total_amount, expected_invoice_total),
            "invoice_internal_total_pct": _variance_pct(
                invoice.total_amount,
                invoice.energy_charge
                + invoice.demand_charge
                + invoice.fixed_charge
                + invoice.tax_charge,
            ),
        }
        invoice_ready = bool(
            tariff_ready
            and meter_ready
            and invoice_variances["energy_quantity_pct"] <= policy.maximum_energy_variance_pct
            and invoice_variances["demand_quantity_pct"] <= policy.maximum_demand_variance_pct
            and all(
                value <= policy.maximum_amount_variance_pct
                for key, value in invoice_variances.items()
                if key not in {"energy_quantity_pct", "demand_quantity_pct"}
            )
        )
        payment_ready = invoice.status == "paid" and bool(invoice.payment_receipt_sha256)

        dr_rows: list[dict[str, Any]] = []
        dr_ready = True
        for item in request.demand_response_settlements:
            expected = max(
                0.0,
                (
                    item.committed_kw * item.capacity_rate_per_kw
                    + item.metered_reduction_kw
                    * item.event_hours
                    * item.energy_rate_per_kwh
                )
                * item.performance_factor
                - item.penalties,
            )
            variance = _variance_pct(item.statement_amount, expected)
            row_ready = bool(
                item.baseline_approved
                and item.currency == policy.currency
                and item.status in {"paid", "settled"}
                and item.payment_receipt_sha256
                and variance <= policy.maximum_amount_variance_pct
            )
            dr_ready = dr_ready and row_ready
            dr_rows.append(
                {
                    "event_id": item.event_id,
                    "expected_amount": round(expected, 6),
                    "statement_amount": item.statement_amount,
                    "variance_pct": round(variance, 6),
                    "reconciled": row_ready,
                }
            )

        ancillary_rows: list[dict[str, Any]] = []
        ancillary_ready = True
        for item in request.ancillary_service_settlements:
            expected = max(
                0.0,
                item.cleared_capacity_kw
                * item.service_hours
                * item.availability_rate_per_kw_hour
                * item.performance_score
                - item.penalties,
            )
            variance = _variance_pct(item.statement_amount, expected)
            row_ready = bool(
                item.currency == policy.currency
                and item.status in {"paid", "settled"}
                and item.payment_receipt_sha256
                and variance <= policy.maximum_amount_variance_pct
            )
            ancillary_ready = ancillary_ready and row_ready
            ancillary_rows.append(
                {
                    "settlement_id": item.settlement_id,
                    "product": item.product,
                    "expected_amount": round(expected, 6),
                    "statement_amount": item.statement_amount,
                    "variance_pct": round(variance, 6),
                    "reconciled": row_ready,
                }
            )

        expected_ppa_amount = (
            request.ppa.delivery_energy_kwh * request.ppa.contract_rate_per_kwh
            + request.ppa.fixed_fee
        )
        ppa_variance = _variance_pct(request.ppa.invoice_amount, expected_ppa_amount)
        ppa_ready = bool(
            request.ppa.currency == policy.currency
            and request.ppa.status in {"paid", "settled"}
            and request.ppa.payment_receipt_sha256
            and ppa_variance <= policy.maximum_amount_variance_pct
        )

        certificate_ids = [item.certificate_id for item in request.renewable_certificates]
        serial_ranges = [item.serial_range for item in request.renewable_certificates]
        certificate_mwh = sum(item.energy_mwh for item in request.renewable_certificates)
        certificate_cost = sum(item.acquisition_cost for item in request.renewable_certificates)
        certificates_ready = bool(
            len(certificate_ids) == len(set(certificate_ids))
            and len(serial_ranges) == len(set(serial_ranges))
            and all(
                item.status == "retired"
                and item.beneficiary == policy.reporting_entity
                and item.retirement_period_id == period.period_id
                and item.currency == policy.currency
                and item.retirement_receipt_sha256
                for item in request.renewable_certificates
            )
        )

        allocable_total = invoice.total_amount + request.ppa.invoice_amount + certificate_cost
        allocated_total = sum(item.allocated_total for item in request.tenant_allocations)
        allocated_energy = sum(item.energy_kwh for item in request.tenant_allocations)
        allocated_demand = sum(item.coincident_demand_kw for item in request.tenant_allocations)
        tenant_ids = [item.tenant_id for item in request.tenant_allocations]
        tenant_invoice_ids = [item.invoice_id for item in request.tenant_allocations]
        tenant_line_items_ready = all(
            _variance_pct(
                item.allocated_total,
                item.energy_charge
                + item.demand_charge
                + item.fixed_tax_charge
                + item.ppa_charge
                + item.certificate_charge,
            )
            <= policy.maximum_tenant_allocation_variance_pct
            and item.invoice_status in {"issued", "paid", "approved"}
            for item in request.tenant_allocations
        )
        tenant_ready = bool(
            len(tenant_ids) == len(set(tenant_ids))
            and len(tenant_invoice_ids) == len(set(tenant_invoice_ids))
            and tenant_line_items_ready
            and _variance_pct(allocated_total, allocable_total)
            <= policy.maximum_tenant_allocation_variance_pct
            and _variance_pct(allocated_energy, meter_energy)
            <= policy.maximum_energy_variance_pct
            and _variance_pct(allocated_demand, meter_peak)
            <= policy.maximum_demand_variance_pct
        )

        mv = request.measurement_verification
        mv_ready = bool(
            mv.status == "independently_reviewed"
            and mv.period_id == period.period_id
            and mv.verified_energy_savings_kwh > 0
            and mv.verified_carbon_reduction_tco2e > 0
        )
        measure_ids = [item.measure_id for item in request.investment_measures]
        claim_ids = [item.savings_claim_id for item in request.investment_measures]
        investment_ready = bool(
            len(measure_ids) == len(set(measure_ids))
            and len(claim_ids) == len(set(claim_ids))
            and all(
                item.approved
                and item.currency == policy.currency
                and set(item.energy_savings_by_period_kwh) <= set(rate_by_period)
                for item in request.investment_measures
            )
            and _variance_pct(
                sum(
                    sum(item.energy_savings_by_period_kwh.values())
                    for item in request.investment_measures
                ),
                mv.verified_energy_savings_kwh,
            )
            <= policy.maximum_energy_variance_pct
            and _variance_pct(
                sum(item.verified_carbon_reduction_tco2e for item in request.investment_measures),
                mv.verified_carbon_reduction_tco2e,
            )
            <= policy.maximum_amount_variance_pct
        )

        macc_rows: list[dict[str, Any]] = []
        portfolio_capex = 0.0
        portfolio_annual_net_benefit = 0.0
        economics_ready = True
        for item in request.investment_measures:
            annual_energy_value = sum(
                amount * rate_by_period.get(period_code, 0.0)
                for period_code, amount in item.energy_savings_by_period_kwh.items()
            ) * policy.annualization_factor
            annual_demand_value = (
                item.annual_demand_savings_kw
                * request.tariff.demand_charge_per_kw
                * policy.annualization_factor
            )
            annual_net_benefit = (
                annual_energy_value
                + annual_demand_value
                + item.annual_settled_incentive
                - item.annual_om_delta
            )
            payback = item.capex / annual_net_benefit if annual_net_benefit > 0 else None
            annualized_capex = item.capex * _annuity_factor(
                policy.discount_rate, item.lifetime_years
            )
            annual_carbon = (
                item.verified_carbon_reduction_tco2e * policy.annualization_factor
            )
            macc = (
                (
                    annualized_capex
                    + item.annual_om_delta
                    - annual_energy_value
                    - annual_demand_value
                    - item.annual_settled_incentive
                )
                / annual_carbon
                if annual_carbon > 0
                else None
            )
            row_ready = payback is not None and macc is not None and math.isfinite(macc)
            economics_ready = economics_ready and row_ready
            portfolio_capex += item.capex
            portfolio_annual_net_benefit += annual_net_benefit
            macc_rows.append(
                {
                    "measure_id": item.measure_id,
                    "savings_claim_id": item.savings_claim_id,
                    "annual_energy_value": round(annual_energy_value, 6),
                    "annual_demand_value": round(annual_demand_value, 6),
                    "annual_net_benefit": round(annual_net_benefit, 6),
                    "simple_payback_years": round(payback, 6) if payback is not None else None,
                    "marginal_abatement_cost_per_tco2e": round(macc, 6)
                    if macc is not None
                    else None,
                    "annual_carbon_reduction_tco2e": round(annual_carbon, 6),
                }
            )
        macc_rows.sort(
            key=lambda row: (
                row["marginal_abatement_cost_per_tco2e"] is None,
                row["marginal_abatement_cost_per_tco2e"] or 0.0,
            )
        )
        cumulative_carbon = 0.0
        for row in macc_rows:
            cumulative_carbon += row["annual_carbon_reduction_tco2e"]
            row["cumulative_abatement_tco2e"] = round(cumulative_carbon, 6)
        portfolio_payback = (
            portfolio_capex / portfolio_annual_net_benefit
            if portfolio_annual_net_benefit > 0
            else None
        )
        economics_ready = bool(
            economics_ready
            and investment_ready
            and portfolio_payback is not None
            and macc_rows
        )

        approval_roles = {item.role for item in request.approvals if item.decision == "approved"}
        approval_ids = [item.approval_id for item in request.approvals]
        approvers = [item.approver_id for item in request.approvals]
        dual_approval_ready = bool(
            approval_roles == {"finance", "energy_manager"}
            and len(request.approvals) == 2
            and len(approval_ids) == len(set(approval_ids))
            and len(approvers) == len(set(approvers))
            and all(
                item.calculation_rule_sha256 == policy.calculation_rule_sha256
                for item in request.approvals
            )
        )

        gates = [
            _gate(
                "source_domain_coverage",
                "八类商业来源齐备",
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
                    "observation_skew_seconds": round(observation_skew, 3)
                    if math.isfinite(observation_skew)
                    else None,
                },
            ),
            _gate("tariff_contract", "生效分时电价合同", tariff_ready, request.tariff.tariff_id),
            _gate(
                "revenue_meter_quality",
                "收入电表完整性",
                meter_ready,
                {"coverage_pct": round(coverage_pct, 6), "meter_id": invoice.revenue_meter_id},
            ),
            _gate(
                "utility_invoice_reconciliation",
                "电量、需量与账单重构",
                invoice_ready,
                {key: round(value, 6) for key, value in invoice_variances.items()},
            ),
            _gate("utility_payment_receipt", "账单付款回执", payment_ready, invoice.status),
            _gate("demand_response_settlement", "需求响应结算", dr_ready, dr_rows),
            _gate(
                "ancillary_service_settlement",
                "辅助服务结算",
                ancillary_ready,
                ancillary_rows,
            ),
            _gate(
                "ppa_settlement",
                "购电协议交付与结算",
                ppa_ready,
                {"variance_pct": round(ppa_variance, 6), "contract_id": request.ppa.contract_id},
            ),
            _gate(
                "renewable_certificate_registry",
                "绿证登记与注销",
                certificates_ready,
                {"certificate_count": len(certificate_ids), "retired_mwh": certificate_mwh},
            ),
            _gate(
                "tenant_allocation",
                "租户分摊与开票对账",
                tenant_ready,
                {
                    "tenant_count": len(tenant_ids),
                    "allocated_total": round(allocated_total, 6),
                    "allocable_total": round(allocable_total, 6),
                },
            ),
            _gate(
                "measurement_verification_link",
                "量测核证哈希引用",
                mv_ready,
                {"report_id": mv.report_id, "status": mv.status, "sha256": mv.report_sha256},
            ),
            _gate(
                "investment_approval",
                "投资与运维成本批准",
                investment_ready,
                {"measure_ids": measure_ids, "claim_ids": claim_ids},
            ),
            _gate(
                "payback_and_macc",
                "回收期与边际减排成本",
                economics_ready,
                {"portfolio_simple_payback_years": portfolio_payback, "rows": macc_rows},
            ),
            _gate(
                "dual_approval_audit",
                "财务与能源双人审批",
                dual_approval_ready,
                {"roles": sorted(approval_roles), "approvers": approvers},
            ),
        ]
        all_ready = all(item["passed"] for item in gates)
        calculation_gates = gates[3:]
        calculation_ready = all(item["passed"] for item in calculation_gates)
        if all_ready:
            status = "evidence_package_passed"
        elif calculation_ready:
            status = "reconciled_pending_source_attestation"
        else:
            status = "blocked"

        total_dr = sum(item.statement_amount for item in request.demand_response_settlements)
        total_ancillary = sum(
            item.statement_amount for item in request.ancillary_service_settlements
        )
        input_evidence_sha256 = canonical_sha256(request.model_dump(mode="json"))
        payload: dict[str, Any] = {
            "schema_version": REPORT_SCHEMA_VERSION,
            "report_id": f"commercial-settlement:{request.case_id}:{input_evidence_sha256[:16]}",
            "mode": "signed_site_commercial_evidence",
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
                "maximum_observation_skew_seconds": round(observation_skew, 6)
                if math.isfinite(observation_skew)
                else None,
            },
            "billing": {
                "tariff_id": request.tariff.tariff_id,
                "invoice_id": invoice.invoice_id,
                "currency": policy.currency,
                "calculated_meter_energy_kwh": round(meter_energy, 6),
                "calculated_peak_demand_kw": round(meter_peak, 6),
                "calculated_invoice_total": round(expected_invoice_total, 6),
                "stated_invoice_total": invoice.total_amount,
                "invoice_variances_pct": {
                    key: round(value, 6) for key, value in invoice_variances.items()
                },
                "verified_utility_invoice_total": invoice.total_amount if all_ready else None,
                "verified_meter_energy_kwh": round(meter_energy, 6) if all_ready else None,
                "verified_peak_demand_kw": round(meter_peak, 6) if all_ready else None,
                "verified_payment": bool(all_ready and payment_ready),
            },
            "market_settlements": {
                "demand_response": dr_rows,
                "ancillary_services": ancillary_rows,
                "ppa": {
                    "contract_id": request.ppa.contract_id,
                    "delivery_energy_kwh": request.ppa.delivery_energy_kwh,
                    "calculated_amount": round(expected_ppa_amount, 6),
                    "stated_amount": request.ppa.invoice_amount,
                    "variance_pct": round(ppa_variance, 6),
                },
                "verified_demand_response_revenue": total_dr if all_ready else None,
                "verified_ancillary_service_revenue": total_ancillary if all_ready else None,
                "verified_ppa_cost": request.ppa.invoice_amount if all_ready else None,
            },
            "renewable_procurement": {
                "certificate_count": len(certificate_ids),
                "calculated_retired_certificate_mwh": round(certificate_mwh, 6),
                "calculated_certificate_cost": round(certificate_cost, 6),
                "verified_retired_certificate_mwh": round(certificate_mwh, 6)
                if all_ready
                else None,
                "verified_certificate_cost": round(certificate_cost, 6) if all_ready else None,
                "registry_retirement_verified": bool(all_ready and certificates_ready),
            },
            "tenant_allocation": {
                "tenant_count": len(tenant_ids),
                "calculated_allocated_total": round(allocated_total, 6),
                "allocable_total": round(allocable_total, 6),
                "verified_allocated_total": round(allocated_total, 6) if all_ready else None,
                "reconciled": bool(all_ready and tenant_ready),
            },
            "measurement_verification": {
                "linked_project_id": mv.project_id,
                "linked_report_id": mv.report_id,
                "linked_report_sha256": mv.report_sha256,
                "status": mv.status,
                "independently_reviewed": mv_ready,
                "calculated_energy_savings_kwh": mv.verified_energy_savings_kwh,
                "calculated_carbon_reduction_tco2e": mv.verified_carbon_reduction_tco2e,
                "verified_energy_savings_kwh": mv.verified_energy_savings_kwh
                if all_ready
                else None,
                "verified_carbon_reduction_tco2e": mv.verified_carbon_reduction_tco2e
                if all_ready
                else None,
            },
            "investment_economics": {
                "currency": policy.currency,
                "discount_rate": policy.discount_rate,
                "annualization_factor": policy.annualization_factor,
                "measure_count": len(macc_rows),
                "calculated_portfolio_simple_payback_years": round(portfolio_payback, 6)
                if portfolio_payback is not None
                else None,
                "calculated_macc": macc_rows,
                "verified_portfolio_simple_payback_years": round(portfolio_payback, 6)
                if all_ready and portfolio_payback is not None
                else None,
                "verified_macc": macc_rows if all_ready else [],
            },
            "gates": gates,
            "assurance": {
                "status": "passed" if all_ready else "blocked",
                "passed_gate_count": sum(item["passed"] for item in gates),
                "required_gate_count": len(gates),
                "calculation_ready": calculation_ready,
                "commercial_settlement_verified": all_ready,
                "software_is_payment_rail": False,
                "software_is_market_operator": False,
                "claim": "signed evidence package reconciled" if all_ready else "claim withheld",
            },
            "production_boundary": {
                "advisory_only": True,
                "payment_instruction_allowed": False,
                "market_bid_allowed": False,
                "certificate_trade_allowed": False,
                "tenant_invoice_issue_allowed": False,
                "accounting_posting_allowed": False,
                "production_authority": False,
                "human_release_required": True,
            },
            "input_evidence_sha256": input_evidence_sha256,
        }
        payload["evidence_sha256"] = canonical_sha256(payload)
        return CommercialSettlementReport(**payload)


commercial_settlement_service = CommercialSettlementService()
