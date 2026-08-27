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
from app.schemas.measurement_verification import (
    MeasurementVerificationReport,
    MeasurementVerificationRequest,
)


REPORT_SCHEMA_VERSION = "energy-carbon-measurement-verification.v1"


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


class MeasurementVerificationService:
    """Evaluate an approved site M&V evidence package without inventing savings.

    Thresholds are supplied by an approved site plan. The engine validates the
    package and calculates signed differences; it does not choose a universal
    protocol, certify a meter, or act as the independent verifier.
    """

    def __init__(self, *, verifier_public_keys: dict[str, str] | None = None) -> None:
        self.verifier_public_keys = dict(
            settings.mv_verifier_public_keys
            if verifier_public_keys is None
            else verifier_public_keys
        )

    def build_default(
        self,
        *,
        dataset_id: str,
        dataset_sha256: str,
        trajectory_steps: int,
        baseline_energy_kwh: float,
        reporting_energy_kwh: float,
        baseline_carbon_kg: float,
        reporting_carbon_kg: float,
        baseline_cost_cny: float,
        reporting_cost_cny: float,
    ) -> MeasurementVerificationReport:
        gate_definitions = [
            ("approved_mv_plan", "现场计量与核证计划", "未提供经批准的现场计划与阈值"),
            ("measurement_boundary", "计量边界与资产清单", "未建立具名组织、场站、仪表和资产边界"),
            ("baseline_model", "冻结基线与调整模型", "当前基线是离线控制策略，不是现场冻结基线"),
            ("interval_coverage", "报告期计量覆盖", "未接入收入电表或设备分表区间值"),
            ("meter_calibration", "仪表校准有效性", "未提供仪表校准证书与有效期"),
            ("invoice_reconciliation", "账单与区间计量对账", "未提供公用事业账单对账记录"),
            ("model_quality", "基线模型质量", "未提供现场基线模型的 CV(RMSE) 与 NMBE"),
            ("non_routine_adjustments", "非例行调整变更记录", "未建立经审批的非例行调整台账"),
            ("uncertainty", "节能减排量不确定性", "未量化计量和基线模型不确定性"),
            ("emission_factor_registry", "排放因子版本与审批", "未提供现场批准的排放因子登记簿"),
            ("independent_verification", "独立复核证据", "未提供独立复核结论和声明哈希"),
        ]
        payload: dict[str, Any] = {
            "schema_version": REPORT_SCHEMA_VERSION,
            "report_id": "mv:offline-scenario-not-verifiable",
            "mode": "offline_scenario_comparison",
            "status": "blocked",
            "project": {
                "project_id": "offline-policy-comparison",
                "reporting_entity": None,
                "site_id": None,
                "measurement_boundary_id": None,
                "dataset_id": dataset_id,
                "dataset_sha256": dataset_sha256,
            },
            "periods": {
                "baseline_period": "same held-out trajectory under control policy",
                "reporting_period": "same held-out trajectory under candidate policy",
                "trajectory_steps": trajectory_steps,
                "field_reporting_period_established": False,
            },
            "baseline_model": {
                "method": "offline_control_policy_counterfactual",
                "frozen": True,
                "site_approved": False,
                "routine_adjustment_variables": [],
                "cv_rmse_pct": None,
                "nmbe_pct": None,
            },
            "data_quality": {
                "expected_meter_interval_count": None,
                "received_meter_interval_count": 0,
                "coverage_pct": 0.0,
                "estimated_pct": None,
                "calibrated_meter_count": 0,
                "invoice_reconciled": False,
            },
            "adjustments": {
                "routine_adjustment_model": "not_established_for_site",
                "non_routine_adjustment_count": 0,
                "all_non_routine_adjustments_approved": False,
            },
            "uncertainty": {
                "quantified": False,
                "confidence_pct": None,
                "energy_savings_interval_kwh": None,
                "carbon_savings_interval_kg": None,
            },
            "gates": [
                _gate(gate_id, label_zh, False, evidence)
                for gate_id, label_zh, evidence in gate_definitions
            ],
            "results": {
                "scenario_energy_difference_kwh": round(
                    baseline_energy_kwh - reporting_energy_kwh,
                    3,
                ),
                "scenario_carbon_difference_kg": round(
                    baseline_carbon_kg - reporting_carbon_kg,
                    3,
                ),
                "scenario_cost_difference_cny": round(
                    baseline_cost_cny - reporting_cost_cny,
                    3,
                ),
                "calculated_energy_savings_kwh": None,
                "calculated_carbon_reduction_kg": None,
                "verified_energy_savings_kwh": None,
                "verified_carbon_reduction_kg": None,
                "verified_financial_savings_cny": None,
                "note": "Scenario differences are retained as offline evidence, not field savings.",
            },
            "assurance": {
                "calculation_ready": False,
                "independent_verification_evidence_accepted": False,
                "software_is_verifier": False,
                "verified_savings_claim_allowed": False,
                "financial_settlement_allowed": False,
                "regulatory_submission_allowed": False,
                "blocker_codes": [item[0] for item in gate_definitions],
            },
            "production_boundary": {
                "simulation_mode": True,
                "live_meter_data_verified": False,
                "field_savings_verified": False,
                "software_is_independent_verifier": False,
                "financial_settlement_allowed": False,
                "regulatory_submission_allowed": False,
            },
            "input_evidence_sha256": None,
        }
        payload["evidence_sha256"] = _canonical_sha256(payload)
        return MeasurementVerificationReport(**payload)

    def evaluate(
        self,
        request: MeasurementVerificationRequest,
    ) -> MeasurementVerificationReport:
        request_payload = request.model_dump(mode="json")
        input_evidence_sha256 = _canonical_sha256(request_payload)
        interval_ids = [item.interval_id for item in request.intervals]
        configured_meters = set(request.boundary.accounting_meter_ids)
        observed_meters = {item.meter_id for item in request.intervals}

        interval_ids_unique = len(interval_ids) == len(set(interval_ids))
        meters_match_boundary = observed_meters == configured_meters
        intervals_inside_period = all(
            item.start_at >= request.reporting_period.start_at
            and item.end_at <= request.reporting_period.end_at
            for item in request.intervals
        )
        no_overlaps = self._no_overlapping_intervals(request)
        received_count = len(request.intervals)
        expected_count = request.plan.expected_meter_interval_count
        interval_count_not_excessive = received_count <= expected_count
        coverage_pct = round(min(100.0, received_count / expected_count * 100.0), 3)
        estimated_count = sum(item.quality == "estimated" for item in request.intervals)
        estimated_pct = round(estimated_count / received_count * 100.0, 3)
        interval_quality_ready = bool(
            interval_ids_unique
            and meters_match_boundary
            and intervals_inside_period
            and no_overlaps
            and interval_count_not_excessive
            and coverage_pct >= request.plan.minimum_coverage_pct
            and estimated_pct <= request.plan.maximum_estimated_pct
        )

        baseline_ready = bool(
            request.baseline_model.baseline_period.end_at <= request.reporting_period.start_at
            and request.baseline_model.frozen_at <= request.reporting_period.start_at
        )
        model_quality_ready = bool(
            request.baseline_model.cv_rmse_pct <= request.plan.maximum_cv_rmse_pct
            and abs(request.baseline_model.nmbe_pct)
            <= request.plan.maximum_absolute_nmbe_pct
        )

        calibration_by_meter = {
            item.meter_id: item for item in request.meter_calibrations
        }
        calibration_ready = bool(
            configured_meters
            and configured_meters <= set(calibration_by_meter)
            and all(
                calibration_by_meter[meter_id].status == "valid"
                and calibration_by_meter[meter_id].valid_from
                <= request.reporting_period.start_at
                and calibration_by_meter[meter_id].valid_through
                >= request.reporting_period.end_at
                for meter_id in configured_meters
            )
        )

        revenue_meter_id = request.invoice_reconciliation.revenue_meter_id
        revenue_interval_energy = sum(
            item.reporting_energy_kwh
            for item in request.intervals
            if item.meter_id == revenue_meter_id
        )
        interval_sum_matches = math.isclose(
            revenue_interval_energy,
            request.invoice_reconciliation.interval_energy_kwh,
            rel_tol=1e-9,
            abs_tol=1e-6,
        )
        invoice_denominator = max(
            request.invoice_reconciliation.invoice_energy_kwh,
            1e-12,
        )
        calculated_invoice_variance_pct = round(
            abs(
                request.invoice_reconciliation.invoice_energy_kwh
                - revenue_interval_energy
            )
            / invoice_denominator
            * 100.0,
            6,
        )
        stated_variance_matches = math.isclose(
            calculated_invoice_variance_pct,
            request.invoice_reconciliation.variance_pct,
            rel_tol=1e-6,
            abs_tol=1e-6,
        )
        invoice_ready = bool(
            revenue_meter_id in configured_meters
            and request.invoice_reconciliation.status == "reconciled"
            and interval_sum_matches
            and stated_variance_matches
            and calculated_invoice_variance_pct
            <= request.plan.maximum_invoice_variance_pct
        )

        adjustments_ready = bool(
            request.non_routine_adjustment_declaration_sha256
            and all(item.approved for item in request.non_routine_adjustments)
        )
        uncertainty_ready = bool(
            sum(
                item.baseline_standard_uncertainty_kwh
                + item.reporting_standard_uncertainty_kwh
                + item.baseline_standard_uncertainty_carbon_kg
                + item.reporting_standard_uncertainty_carbon_kg
                for item in request.intervals
            )
            > 0
        )
        independent = request.independent_verification
        independent_signature_valid = self._independent_signature_valid(request)
        approval_principals = {
            request.plan.approved_by,
            request.boundary.approved_by,
            request.baseline_model.approved_by,
            *(item.approved_by for item in request.non_routine_adjustments),
        }
        independent_ready = bool(
            independent
            and independent.independence_attested
            and independent.conclusion == "accepted"
            and independent.reviewed_at >= request.reporting_period.end_at
            and independent.reviewer_id not in approval_principals
            and independent_signature_valid
        )
        factor_registry_ready = bool(
            request.emission_factor_registry.registry_sha256
            and request.emission_factor_registry.approved_by
        )

        gates = [
            _gate(
                "approved_mv_plan",
                "现场计量与核证计划",
                bool(request.plan.approved_by),
                request.plan.plan_id,
            ),
            _gate(
                "measurement_boundary",
                "计量边界与资产清单",
                bool(request.boundary.approved_by and configured_meters),
                request.boundary.boundary_id,
            ),
            _gate(
                "baseline_model",
                "冻结基线与调整模型",
                baseline_ready,
                request.baseline_model.baseline_model_id,
            ),
            _gate(
                "interval_coverage",
                "报告期计量覆盖",
                interval_quality_ready,
                {
                    "coverage_pct": coverage_pct,
                    "estimated_pct": estimated_pct,
                    "meters_match_boundary": meters_match_boundary,
                    "intervals_inside_period": intervals_inside_period,
                    "no_overlaps": no_overlaps,
                },
            ),
            _gate(
                "meter_calibration",
                "仪表校准有效性",
                calibration_ready,
                sorted(calibration_by_meter),
            ),
            _gate(
                "invoice_reconciliation",
                "账单与区间计量对账",
                invoice_ready,
                {
                    "revenue_meter_id": revenue_meter_id,
                    "calculated_variance_pct": calculated_invoice_variance_pct,
                },
            ),
            _gate(
                "model_quality",
                "基线模型质量",
                model_quality_ready,
                {
                    "cv_rmse_pct": request.baseline_model.cv_rmse_pct,
                    "nmbe_pct": request.baseline_model.nmbe_pct,
                },
            ),
            _gate(
                "non_routine_adjustments",
                "非例行调整变更记录",
                adjustments_ready,
                len(request.non_routine_adjustments),
            ),
            _gate(
                "uncertainty",
                "节能减排量不确定性",
                uncertainty_ready,
                request.plan.uncertainty_confidence_pct,
            ),
            _gate(
                "emission_factor_registry",
                "排放因子版本与审批",
                factor_registry_ready,
                {
                    "registry_id": request.emission_factor_registry.registry_id,
                    "registry_version": request.emission_factor_registry.registry_version,
                },
            ),
            _gate(
                "independent_verification",
                "独立复核证据",
                independent_ready,
                {
                    "reviewer_id": independent.reviewer_id if independent else None,
                    "key_id": independent.key_id if independent else None,
                    "signature_valid": independent_signature_valid,
                },
            ),
        ]
        calculation_gates = gates[:-1]
        calculation_ready = all(item["passed"] for item in calculation_gates)
        evidence_package_passed = calculation_ready and independent_ready

        baseline_energy = sum(
            item.baseline_adjusted_energy_kwh for item in request.intervals
        )
        reporting_energy = sum(item.reporting_energy_kwh for item in request.intervals)
        baseline_carbon = sum(
            item.baseline_adjusted_carbon_kg for item in request.intervals
        )
        reporting_carbon = sum(item.reporting_carbon_kg for item in request.intervals)
        energy_savings = baseline_energy - reporting_energy
        carbon_reduction = baseline_carbon - reporting_carbon
        energy_standard_uncertainty = math.sqrt(
            sum(
                item.baseline_standard_uncertainty_kwh**2
                + item.reporting_standard_uncertainty_kwh**2
                for item in request.intervals
            )
        )
        carbon_standard_uncertainty = math.sqrt(
            sum(
                item.baseline_standard_uncertainty_carbon_kg**2
                + item.reporting_standard_uncertainty_carbon_kg**2
                for item in request.intervals
            )
        )
        energy_expanded_uncertainty = (
            request.plan.uncertainty_coverage_factor * energy_standard_uncertainty
        )
        carbon_expanded_uncertainty = (
            request.plan.uncertainty_coverage_factor * carbon_standard_uncertainty
        )

        status = (
            "evidence_package_passed"
            if evidence_package_passed
            else "calculated_pending_independent_verification"
            if calculation_ready
            else "blocked"
        )
        payload: dict[str, Any] = {
            "schema_version": REPORT_SCHEMA_VERSION,
            "report_id": f"mv:{input_evidence_sha256[:24]}",
            "mode": "site_evidence_evaluation",
            "status": status,
            "project": {
                "project_id": request.project_id,
                "reporting_entity": request.boundary.reporting_entity,
                "site_id": request.boundary.site_id,
                "measurement_boundary_id": request.boundary.boundary_id,
                "accounting_meter_ids": request.boundary.accounting_meter_ids,
                "included_assets": request.boundary.included_assets,
                "excluded_assets": request.boundary.excluded_assets,
            },
            "periods": {
                "baseline_period": request.baseline_model.baseline_period.model_dump(mode="json"),
                "reporting_period": request.reporting_period.model_dump(mode="json"),
                "field_reporting_period_established": True,
            },
            "baseline_model": {
                "baseline_model_id": request.baseline_model.baseline_model_id,
                "method": request.baseline_model.method,
                "model_sha256": request.baseline_model.model_sha256,
                "frozen_at": request.baseline_model.frozen_at.isoformat(),
                "training_observations": request.baseline_model.training_observations,
                "validation_observations": request.baseline_model.validation_observations,
                "cv_rmse_pct": request.baseline_model.cv_rmse_pct,
                "nmbe_pct": request.baseline_model.nmbe_pct,
                "independent_variables": request.baseline_model.independent_variables,
                "site_approved": True,
            },
            "data_quality": {
                "expected_meter_interval_count": expected_count,
                "received_meter_interval_count": received_count,
                "coverage_pct": coverage_pct,
                "measured_pct": round(
                    (received_count - estimated_count) / received_count * 100.0,
                    3,
                ),
                "estimated_pct": estimated_pct,
                "calibrated_meter_count": sum(
                    meter_id in calibration_by_meter for meter_id in configured_meters
                ),
                "invoice_reconciled": invoice_ready,
                "calculated_invoice_variance_pct": calculated_invoice_variance_pct,
            },
            "adjustments": {
                "routine_adjustment_model": request.baseline_model.baseline_model_id,
                "independent_variables": request.baseline_model.independent_variables,
                "non_routine_adjustment_count": len(request.non_routine_adjustments),
                "all_non_routine_adjustments_approved": adjustments_ready,
                "recorded_energy_adjustment_kwh": round(
                    sum(item.applied_energy_kwh for item in request.non_routine_adjustments),
                    6,
                ),
                "recorded_carbon_adjustment_kg": round(
                    sum(item.applied_carbon_kg for item in request.non_routine_adjustments),
                    6,
                ),
                "note": "Interval baseline values are already adjusted; records are not applied twice.",
            },
            "uncertainty": {
                "quantified": uncertainty_ready,
                "confidence_pct": request.plan.uncertainty_confidence_pct,
                "coverage_factor": request.plan.uncertainty_coverage_factor,
                "energy_standard_uncertainty_kwh": round(energy_standard_uncertainty, 6),
                "carbon_standard_uncertainty_kg": round(carbon_standard_uncertainty, 6),
                "energy_savings_interval_kwh": [
                    round(energy_savings - energy_expanded_uncertainty, 6),
                    round(energy_savings + energy_expanded_uncertainty, 6),
                ]
                if calculation_ready
                else None,
                "carbon_savings_interval_kg": [
                    round(carbon_reduction - carbon_expanded_uncertainty, 6),
                    round(carbon_reduction + carbon_expanded_uncertainty, 6),
                ]
                if calculation_ready
                else None,
            },
            "gates": gates,
            "results": {
                "scenario_energy_difference_kwh": None,
                "scenario_carbon_difference_kg": None,
                "scenario_cost_difference_cny": None,
                "baseline_adjusted_energy_kwh": round(baseline_energy, 6)
                if calculation_ready
                else None,
                "reporting_energy_kwh": round(reporting_energy, 6)
                if calculation_ready
                else None,
                "baseline_adjusted_carbon_kg": round(baseline_carbon, 6)
                if calculation_ready
                else None,
                "reporting_carbon_kg": round(reporting_carbon, 6)
                if calculation_ready
                else None,
                "calculated_energy_savings_kwh": round(energy_savings, 6)
                if calculation_ready
                else None,
                "calculated_carbon_reduction_kg": round(carbon_reduction, 6)
                if calculation_ready
                else None,
                "verified_energy_savings_kwh": round(energy_savings, 6)
                if evidence_package_passed
                else None,
                "verified_carbon_reduction_kg": round(carbon_reduction, 6)
                if evidence_package_passed
                else None,
                "verified_financial_savings_cny": None,
                "note": "Financial savings require a separate approved tariff and settlement contract.",
            },
            "assurance": {
                "calculation_ready": calculation_ready,
                "independent_verification_evidence_accepted": independent_ready,
                "software_is_verifier": False,
                "verified_savings_claim_allowed": evidence_package_passed,
                "financial_settlement_allowed": False,
                "regulatory_submission_allowed": False,
                "blocker_codes": [
                    item["gate_id"] for item in gates if not item["passed"]
                ],
            },
            "production_boundary": {
                "simulation_mode": False,
                "live_meter_data_verified": calculation_ready,
                "field_savings_verified": evidence_package_passed,
                "software_is_independent_verifier": False,
                "financial_settlement_allowed": False,
                "regulatory_submission_allowed": False,
            },
            "input_evidence_sha256": input_evidence_sha256,
        }
        payload["evidence_sha256"] = _canonical_sha256(payload)
        return MeasurementVerificationReport(**payload)

    @staticmethod
    def _no_overlapping_intervals(request: MeasurementVerificationRequest) -> bool:
        for meter_id in request.boundary.accounting_meter_ids:
            items = sorted(
                (item for item in request.intervals if item.meter_id == meter_id),
                key=lambda item: item.start_at,
            )
            if any(current.start_at < previous.end_at for previous, current in zip(items, items[1:])):
                return False
        return True

    def _independent_signature_valid(
        self,
        request: MeasurementVerificationRequest,
    ) -> bool:
        evidence = request.independent_verification
        if evidence is None:
            return False
        public_key_text = self.verifier_public_keys.get(evidence.key_id, "")
        if not public_key_text:
            return False
        unsigned_payload = request.model_dump(mode="json")
        independent_payload = dict(unsigned_payload.get("independent_verification") or {})
        independent_payload.pop("signature", None)
        independent_payload.pop("signed_evidence_sha256", None)
        unsigned_payload["independent_verification"] = independent_payload
        computed_sha256 = _canonical_sha256(unsigned_payload)
        if computed_sha256 != evidence.signed_evidence_sha256:
            return False
        try:
            public_key_bytes = base64.b64decode(public_key_text, validate=True)
            signature = base64.b64decode(evidence.signature, validate=True)
            Ed25519PublicKey.from_public_bytes(public_key_bytes).verify(
                signature,
                bytes.fromhex(computed_sha256),
            )
        except (ValueError, binascii.Error, InvalidSignature):
            return False
        return True


measurement_verification_service = MeasurementVerificationService(
    verifier_public_keys=settings.mv_verifier_public_keys
)
