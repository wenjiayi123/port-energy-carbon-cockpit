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
from app.schemas.carbon_assets import (
    CarbonAssetComplianceReport,
    CarbonAssetComplianceRequest,
)


REPORT_SCHEMA_VERSION = "carbon-asset-compliance.v1"


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _gate(gate_id: str, label_zh: str, passed: bool, evidence: Any) -> dict[str, Any]:
    return {
        "gate_id": gate_id,
        "label_zh": label_zh,
        "passed": passed,
        "evidence": evidence,
    }


class CarbonAssetComplianceService:
    """Reconcile carbon assets from externally authorized evidence.

    The service verifies evidence and calculates a compliance position. It is
    never an exchange, registry, cash-settlement rail, or regulatory filing
    authority, and therefore cannot execute a trade or submit a filing.
    """

    def __init__(self, *, registry_public_keys: dict[str, str] | None = None) -> None:
        self.registry_public_keys = dict(
            settings.carbon_registry_public_keys
            if registry_public_keys is None
            else registry_public_keys
        )

    def build_default(
        self,
        *,
        scenario_emission_ton: float,
        scenario_quota_reference_ton: float,
        scenario_quota_gap_ton: float,
        scenario_carbon_cost_cny: float,
        scenario_carbon_price_cny_per_ton: float,
    ) -> CarbonAssetComplianceReport:
        gate_definitions = [
            ("approved_program_rules", "经批准的履约规则", "未提供适用计划、履约期和审批规则"),
            ("registry_account", "登记簿账户与主体", "未接入具名登记簿账户和权属证据"),
            ("verified_emissions", "经核证履约排放量", "离线情景排放不是经核证履约排放量"),
            ("eligible_allowance_lots", "合格配额批次", "未提供批次、年份、数量与受益所有人"),
            ("serial_integrity", "配额序列唯一性", "未提供可去重的工具编号和序列批次"),
            ("trade_confirmation", "交易成交确认", "未提供成交回执或无交易声明"),
            ("cash_settlement", "资金结算凭证", "未提供交易资金结算凭证"),
            ("registry_reconciliation", "登记簿与内部账对账", "未提供期初、变动、注销和期末余额对账"),
            ("dual_approval", "合规与财务双人审批", "未提供职责分离的合规和财务审批"),
            ("surrender_quantity", "履约义务数量覆盖", "未提供核证排放对应的足额履约数量"),
            ("retirement_confirmation", "配额注销确认", "未提供登记簿注销编号和确认凭证"),
            ("registry_attestation", "登记簿签名证明", "未配置可信公钥或未提供签名证明"),
        ]
        payload: dict[str, Any] = {
            "schema_version": REPORT_SCHEMA_VERSION,
            "report_id": "carbon-assets:offline-scenario-not-settleable",
            "mode": "offline_scenario_valuation",
            "status": "blocked",
            "program": {
                "program_id": None,
                "jurisdiction": None,
                "compliance_period": None,
                "rules_approved": False,
            },
            "account": {
                "registry_id": None,
                "account_id": None,
                "account_holder": None,
                "registry_connected": False,
            },
            "positions": {
                "scenario_emission_ton": round(scenario_emission_ton, 3),
                "scenario_quota_reference_ton": round(
                    scenario_quota_reference_ton,
                    3,
                ),
                "scenario_quota_gap_ton": round(scenario_quota_gap_ton, 3),
                "calculated_verified_emissions_tco2e": None,
                "calculated_obligation_tco2e": None,
                "calculated_retired_tco2e": None,
                "calculated_surplus_tco2e": None,
                "calculated_deficit_tco2e": None,
                "verified_emissions_tco2e": None,
                "verified_obligation_tco2e": None,
                "verified_retired_tco2e": None,
                "verified_registry_balance_tco2e": None,
                "verified_surplus_tco2e": None,
                "verified_deficit_tco2e": None,
            },
            "settlement": {
                "scenario_carbon_price_cny_per_ton": round(
                    scenario_carbon_price_cny_per_ton,
                    3,
                ),
                "scenario_carbon_cost_cny": round(scenario_carbon_cost_cny, 3),
                "transaction_count": 0,
                "calculated_purchase_cny": None,
                "calculated_sale_cny": None,
                "calculated_fees_cny": None,
                "calculated_net_cash_outflow_cny": None,
                "verified_net_cash_outflow_cny": None,
                "currency": None,
            },
            "ledger": [],
            "gates": [
                _gate(gate_id, label_zh, False, evidence)
                for gate_id, label_zh, evidence in gate_definitions
            ],
            "assurance": {
                "calculation_ready": False,
                "registry_attestation_accepted": False,
                "financial_settlement_verified": False,
                "compliance_position_verified": False,
                "software_is_registry": False,
                "software_is_exchange": False,
                "blocker_codes": [item[0] for item in gate_definitions],
            },
            "production_boundary": {
                "simulation_mode": True,
                "registry_connected": False,
                "trade_execution_allowed": False,
                "cash_movement_allowed": False,
                "compliance_claim_allowed": False,
                "regulatory_submission_allowed": False,
            },
            "input_evidence_sha256": None,
        }
        payload["evidence_sha256"] = _canonical_sha256(payload)
        return CarbonAssetComplianceReport(**payload)

    def evaluate(
        self,
        request: CarbonAssetComplianceRequest,
    ) -> CarbonAssetComplianceReport:
        request_payload = request.model_dump(mode="json")
        input_evidence_sha256 = _canonical_sha256(request_payload)
        period = request.program.compliance_period
        account_ready = bool(
            request.account.status == "active"
            and request.account.account_holder == request.verified_emissions.reporting_entity
        )
        verifier_separate = request.verified_emissions.verifier_id not in {
            request.program.approved_by,
            request.account.approved_by,
        }
        verified_emissions_ready = bool(
            request.verified_emissions.period_start == period.start_at
            and request.verified_emissions.period_end == period.end_at
            and request.verified_emissions.assurance_conclusion == "accepted"
            and request.verified_emissions.verified_at <= period.surrender_deadline
            and verifier_separate
        )

        lots = request.allowance_lots
        lot_ids = [item.instrument_id for item in lots]
        serial_batches = [item.serial_batch_id for item in lots]
        serial_integrity_ready = bool(
            len(lot_ids) == len(set(lot_ids))
            and len(serial_batches) == len(set(serial_batches))
        )
        eligible_lots_ready = bool(
            all(
                item.vintage in request.program.eligible_vintages
                and item.beneficial_owner == request.account.account_holder
                for item in lots
            )
        )
        active_lot_balance = sum(
            item.quantity_tco2e
            for item in lots
            if item.status in {"active", "reserved"}
        )

        trades = request.trades
        transaction_ids = [item.transaction_id for item in trades]
        transfer_ids = [item.registry_transfer_id for item in trades]
        declared_no_trade = bool(not trades and request.no_trade_declaration_sha256)
        trade_ids_unique = bool(
            len(transaction_ids) == len(set(transaction_ids))
            and len(transfer_ids) == len(set(transfer_ids))
        )
        trades_in_window = all(
            period.start_at <= item.executed_at <= period.surrender_deadline
            and item.settled_at <= period.surrender_deadline
            for item in trades
        )
        trades_reference_lots = all(item.instrument_id in set(lot_ids) for item in trades)
        trade_confirmation_ready = bool(
            declared_no_trade
            or (
                trades
                and trade_ids_unique
                and trades_in_window
                and trades_reference_lots
                and all(item.status == "settled" for item in trades)
            )
        )
        currency_values = {item.currency for item in trades}
        currency_ready = declared_no_trade or len(currency_values) == 1
        cash_settlement_ready = bool(
            declared_no_trade
            or (
                trade_confirmation_ready
                and currency_ready
                and all(
                    item.cash_settlement_sha256
                    and item.trade_confirmation_sha256
                    for item in trades
                )
            )
        )

        buy_quantity = sum(item.quantity_tco2e for item in trades if item.side == "buy")
        sell_quantity = sum(item.quantity_tco2e for item in trades if item.side == "sell")
        confirmed_retirements = [
            item for item in request.retirements if item.status == "confirmed"
        ]
        retired_quantity = sum(item.quantity_tco2e for item in confirmed_retirements)
        retirement_ids = [item.retirement_id for item in request.retirements]
        retirement_confirmation_ready = bool(
            len(retirement_ids) == len(set(retirement_ids))
            and len(confirmed_retirements) == len(request.retirements)
            and all(
                item.compliance_period_id == request.case_id
                and period.end_at <= item.retired_at <= period.surrender_deadline
                for item in confirmed_retirements
            )
        )

        reconciliation = request.reconciliation
        calculated_closing_balance = (
            reconciliation.opening_balance_tco2e
            + buy_quantity
            - sell_quantity
            - retired_quantity
        )
        registry_reconciliation_ready = bool(
            reconciliation.status == "reconciled"
            and reconciliation.as_of <= period.surrender_deadline
            and math.isclose(
                reconciliation.acquisitions_tco2e,
                buy_quantity,
                abs_tol=1e-6,
            )
            and math.isclose(
                reconciliation.disposals_tco2e,
                sell_quantity,
                abs_tol=1e-6,
            )
            and math.isclose(
                reconciliation.retirements_tco2e,
                retired_quantity,
                abs_tol=1e-6,
            )
            and math.isclose(
                reconciliation.registry_closing_balance_tco2e,
                calculated_closing_balance,
                abs_tol=1e-6,
            )
            and math.isclose(
                reconciliation.internal_closing_balance_tco2e,
                reconciliation.registry_closing_balance_tco2e,
                abs_tol=1e-6,
            )
            and math.isclose(
                active_lot_balance,
                reconciliation.registry_closing_balance_tco2e,
                abs_tol=1e-6,
            )
        )

        approvals_by_role = {item.role: item for item in request.approvals}
        compliance_approval = approvals_by_role.get("compliance")
        finance_approval = approvals_by_role.get("finance")
        retirement_time = min(item.retired_at for item in request.retirements)
        dual_approval_ready = bool(
            len(request.approvals) == 2
            and compliance_approval
            and finance_approval
            and compliance_approval.decision == "approved"
            and finance_approval.decision == "approved"
            and compliance_approval.approver_id != finance_approval.approver_id
            and compliance_approval.approver_id
            not in {request.program.approved_by, request.verified_emissions.verifier_id}
            and finance_approval.approver_id
            not in {request.program.approved_by, request.verified_emissions.verifier_id}
            and compliance_approval.approved_at <= retirement_time
            and finance_approval.approved_at <= retirement_time
        )

        obligation = (
            request.verified_emissions.verified_emissions_tco2e
            * request.program.surrender_ratio
        )
        surrender_quantity_ready = bool(
            verified_emissions_ready
            and retirement_confirmation_ready
            and retired_quantity + 1e-6 >= obligation
        )
        registry_signature_valid = self._registry_signature_valid(request)
        attestation = request.registry_attestation
        registry_attestation_ready = bool(
            attestation
            and attestation.conclusion == "confirmed"
            and attestation.issued_at >= reconciliation.as_of
            and attestation.attester_id
            not in {
                request.program.approved_by,
                request.account.approved_by,
                request.verified_emissions.verifier_id,
                *(item.approver_id for item in request.approvals),
            }
            and registry_signature_valid
        )

        gates = [
            _gate(
                "approved_program_rules",
                "经批准的履约规则",
                bool(request.program.approved_by),
                {
                    "program_id": request.program.program_id,
                    "program_version": request.program.program_version,
                },
            ),
            _gate(
                "registry_account",
                "登记簿账户与主体",
                account_ready,
                request.account.account_id,
            ),
            _gate(
                "verified_emissions",
                "经核证履约排放量",
                verified_emissions_ready,
                {
                    "inventory_report_id": request.verified_emissions.inventory_report_id,
                    "verifier_separate": verifier_separate,
                },
            ),
            _gate(
                "eligible_allowance_lots",
                "合格配额批次",
                eligible_lots_ready,
                {"lot_count": len(lots), "active_balance_tco2e": active_lot_balance},
            ),
            _gate(
                "serial_integrity",
                "配额序列唯一性",
                serial_integrity_ready,
                {"instrument_ids_unique": serial_integrity_ready},
            ),
            _gate(
                "trade_confirmation",
                "交易成交确认",
                trade_confirmation_ready,
                {
                    "transaction_count": len(trades),
                    "declared_no_trade": declared_no_trade,
                },
            ),
            _gate(
                "cash_settlement",
                "资金结算凭证",
                cash_settlement_ready,
                {"settled_transaction_count": sum(item.status == "settled" for item in trades)},
            ),
            _gate(
                "registry_reconciliation",
                "登记簿与内部账对账",
                registry_reconciliation_ready,
                {
                    "calculated_closing_balance_tco2e": round(calculated_closing_balance, 6),
                    "registry_closing_balance_tco2e": reconciliation.registry_closing_balance_tco2e,
                },
            ),
            _gate(
                "dual_approval",
                "合规与财务双人审批",
                dual_approval_ready,
                sorted(approvals_by_role),
            ),
            _gate(
                "surrender_quantity",
                "履约义务数量覆盖",
                surrender_quantity_ready,
                {
                    "obligation_tco2e": round(obligation, 6),
                    "retired_tco2e": round(retired_quantity, 6),
                },
            ),
            _gate(
                "retirement_confirmation",
                "配额注销确认",
                retirement_confirmation_ready,
                retirement_ids,
            ),
            _gate(
                "registry_attestation",
                "登记簿签名证明",
                registry_attestation_ready,
                {
                    "key_id": attestation.key_id if attestation else None,
                    "signature_valid": registry_signature_valid,
                },
            ),
        ]
        calculation_ready = all(item["passed"] for item in gates[:-1])
        evidence_package_passed = calculation_ready and registry_attestation_ready
        financial_settlement_verified = bool(
            evidence_package_passed
            and trade_confirmation_ready
            and cash_settlement_ready
            and registry_reconciliation_ready
        )

        gross_purchase = sum(
            item.quantity_tco2e * item.unit_price
            for item in trades
            if item.side == "buy"
        )
        gross_sale = sum(
            item.quantity_tco2e * item.unit_price
            for item in trades
            if item.side == "sell"
        )
        total_fees = sum(item.fees for item in trades)
        net_cash_outflow = gross_purchase + total_fees - gross_sale
        surplus = max(0.0, retired_quantity - obligation)
        deficit = max(0.0, obligation - retired_quantity)
        currency = next(iter(currency_values)) if len(currency_values) == 1 else None

        ledger = self._build_ledger(request)
        status = (
            "evidence_package_passed"
            if evidence_package_passed
            else "reconciled_pending_registry_attestation"
            if calculation_ready
            else "blocked"
        )
        payload: dict[str, Any] = {
            "schema_version": REPORT_SCHEMA_VERSION,
            "report_id": f"carbon-assets:{input_evidence_sha256[:24]}",
            "mode": "registry_evidence_evaluation",
            "status": status,
            "program": {
                "program_id": request.program.program_id,
                "program_version": request.program.program_version,
                "jurisdiction": request.program.jurisdiction,
                "compliance_period": period.model_dump(mode="json"),
                "surrender_ratio": request.program.surrender_ratio,
                "eligible_vintages": request.program.eligible_vintages,
                "rules_approved": bool(request.program.approved_by),
            },
            "account": {
                "registry_id": request.account.registry_id,
                "account_id": request.account.account_id,
                "account_holder": request.account.account_holder,
                "legal_entity_id": request.account.legal_entity_id,
                "registry_connected": registry_attestation_ready,
            },
            "positions": {
                "scenario_emission_ton": None,
                "scenario_quota_reference_ton": None,
                "scenario_quota_gap_ton": None,
                "calculated_verified_emissions_tco2e": round(
                    request.verified_emissions.verified_emissions_tco2e,
                    6,
                )
                if calculation_ready
                else None,
                "calculated_obligation_tco2e": round(obligation, 6)
                if calculation_ready
                else None,
                "calculated_retired_tco2e": round(retired_quantity, 6)
                if calculation_ready
                else None,
                "calculated_surplus_tco2e": round(surplus, 6)
                if calculation_ready
                else None,
                "calculated_deficit_tco2e": round(deficit, 6)
                if calculation_ready
                else None,
                "verified_emissions_tco2e": round(
                    request.verified_emissions.verified_emissions_tco2e,
                    6,
                )
                if evidence_package_passed
                else None,
                "verified_obligation_tco2e": round(obligation, 6)
                if evidence_package_passed
                else None,
                "verified_retired_tco2e": round(retired_quantity, 6)
                if evidence_package_passed
                else None,
                "verified_registry_balance_tco2e": round(
                    reconciliation.registry_closing_balance_tco2e,
                    6,
                )
                if evidence_package_passed
                else None,
                "verified_surplus_tco2e": round(surplus, 6)
                if evidence_package_passed
                else None,
                "verified_deficit_tco2e": round(deficit, 6)
                if evidence_package_passed
                else None,
            },
            "settlement": {
                "scenario_carbon_price_cny_per_ton": None,
                "scenario_carbon_cost_cny": None,
                "transaction_count": len(trades),
                "calculated_purchase_cny": round(gross_purchase, 6)
                if cash_settlement_ready and currency_ready
                else None,
                "calculated_sale_cny": round(gross_sale, 6)
                if cash_settlement_ready and currency_ready
                else None,
                "calculated_fees_cny": round(total_fees, 6)
                if cash_settlement_ready and currency_ready
                else None,
                "calculated_net_cash_outflow_cny": round(net_cash_outflow, 6)
                if cash_settlement_ready and currency_ready
                else None,
                "verified_net_cash_outflow_cny": round(net_cash_outflow, 6)
                if financial_settlement_verified and currency_ready
                else None,
                "currency": currency,
            },
            "ledger": ledger,
            "gates": gates,
            "assurance": {
                "calculation_ready": calculation_ready,
                "registry_attestation_accepted": registry_attestation_ready,
                "financial_settlement_verified": financial_settlement_verified,
                "compliance_position_verified": evidence_package_passed,
                "software_is_registry": False,
                "software_is_exchange": False,
                "blocker_codes": [item["gate_id"] for item in gates if not item["passed"]],
            },
            "production_boundary": {
                "simulation_mode": False,
                "registry_connected": registry_attestation_ready,
                "trade_execution_allowed": False,
                "cash_movement_allowed": False,
                "compliance_claim_allowed": evidence_package_passed,
                "regulatory_submission_allowed": False,
            },
            "input_evidence_sha256": input_evidence_sha256,
        }
        payload["evidence_sha256"] = _canonical_sha256(payload)
        return CarbonAssetComplianceReport(**payload)

    @staticmethod
    def _build_ledger(request: CarbonAssetComplianceRequest) -> list[dict[str, Any]]:
        events: list[tuple[str, str, Any, float]] = [
            (
                "opening_balance",
                request.reconciliation.reconciliation_id,
                request.program.compliance_period.start_at,
                request.reconciliation.opening_balance_tco2e,
            )
        ]
        events.extend(
            (
                f"trade_{item.side}",
                item.transaction_id,
                item.settled_at,
                item.quantity_tco2e if item.side == "buy" else -item.quantity_tco2e,
            )
            for item in request.trades
        )
        events.extend(
            ("retirement", item.retirement_id, item.retired_at, -item.quantity_tco2e)
            for item in request.retirements
        )
        opening, *movements = events
        movements.sort(key=lambda item: (item[2], item[1]))
        ordered = [opening, *movements]
        ledger: list[dict[str, Any]] = []
        balance = 0.0
        previous_hash = "0" * 64
        for index, (entry_type, reference_id, occurred_at, quantity_delta) in enumerate(ordered):
            balance += quantity_delta
            entry = {
                "index": index,
                "entry_type": entry_type,
                "reference_id": reference_id,
                "occurred_at": occurred_at.isoformat(),
                "quantity_delta_tco2e": round(quantity_delta, 6),
                "running_balance_tco2e": round(balance, 6),
                "previous_hash": previous_hash,
            }
            entry_hash = _canonical_sha256(entry)
            entry["entry_hash"] = entry_hash
            ledger.append(entry)
            previous_hash = entry_hash
        return ledger

    def _registry_signature_valid(
        self,
        request: CarbonAssetComplianceRequest,
    ) -> bool:
        attestation = request.registry_attestation
        if attestation is None:
            return False
        public_key_text = self.registry_public_keys.get(attestation.key_id, "")
        if not public_key_text:
            return False
        unsigned_payload = request.model_dump(mode="json")
        attestation_payload = dict(unsigned_payload.get("registry_attestation") or {})
        attestation_payload.pop("signature", None)
        attestation_payload.pop("signed_evidence_sha256", None)
        unsigned_payload["registry_attestation"] = attestation_payload
        computed_sha256 = _canonical_sha256(unsigned_payload)
        if computed_sha256 != attestation.signed_evidence_sha256:
            return False
        try:
            public_key_bytes = base64.b64decode(public_key_text, validate=True)
            signature = base64.b64decode(attestation.signature, validate=True)
            Ed25519PublicKey.from_public_bytes(public_key_bytes).verify(
                signature,
                bytes.fromhex(computed_sha256),
            )
        except (ValueError, binascii.Error, InvalidSignature):
            return False
        return True


carbon_asset_compliance_service = CarbonAssetComplianceService(
    registry_public_keys=settings.carbon_registry_public_keys
)
