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
from app.schemas.energy_carbon_management import (
    REQUIRED_ROLES,
    EnergyCarbonManagementReport,
    EnergyCarbonManagementRequest,
)


REPORT_SCHEMA_VERSION = "energy-carbon-management-system.v1"
REQUIRED_REVIEW_TOPICS = {
    "energy_performance",
    "objectives_and_action_plans",
    "monitoring_and_measurement",
    "ghg_inventory",
    "internal_audit",
    "corrective_actions",
    "resources",
}


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _gate(
    gate_id: str,
    label_zh: str,
    stage: str,
    passed: bool,
    evidence: Any,
) -> dict[str, Any]:
    return {
        "gate_id": gate_id,
        "label_zh": label_zh,
        "stage": stage,
        "passed": passed,
        "evidence": evidence,
    }


class EnergyCarbonManagementService:
    """Evaluate a signed energy and GHG management-system evidence cycle.

    The engine checks evidence linkage and a fail-closed PDCA workflow. It does
    not interpret proprietary standard clauses, award certification, replace a
    validation/verification body, or submit a regulatory inventory.
    """

    def __init__(self, *, auditor_public_keys: dict[str, str] | None = None) -> None:
        self.auditor_public_keys = dict(
            settings.management_system_auditor_public_keys
            if auditor_public_keys is None
            else auditor_public_keys
        )

    def build_default(
        self,
        *,
        inventory_evidence_sha256: str,
        inventory_status: str,
        measurement_verification_evidence_sha256: str,
        measurement_verification_status: str,
    ) -> EnergyCarbonManagementReport:
        gate_definitions = [
            ("context_and_requirements", "组织环境与适用要求", "PLAN", "未提供组织边界、适用要求登记簿和气候相关性评审"),
            ("policy_and_leadership", "能源与碳方针及领导承诺", "PLAN", "未提供最高管理者批准、发布和沟通的方针"),
            ("roles_and_responsibilities", "职责、权限与职责分离", "PLAN", "未任命能源、温室气体、运营和内审责任人"),
            ("energy_review_and_seus", "能源评审与主要能源使用", "PLAN", "未完成现场能源评审和主要能源使用识别"),
            ("energy_baseline", "能源基准与调整规则", "PLAN", "离线策略对比不是经批准的现场能源基准"),
            ("enpis_and_objectives", "能源绩效参数与目标", "PLAN", "未建立能源绩效参数、目标值、责任人和期限"),
            ("action_plans_and_resources", "行动计划与资源", "DO", "未提供覆盖目标的行动、预算、资源和完成证据"),
            ("monitoring_measurement_analysis", "监视、测量、分析与校准", "DO", "未接入现场仪表覆盖、校准、修订和计量核证证据"),
            ("operational_controls", "主要能源使用运行控制", "DO", "未建立主要能源使用运行准则和异常响应"),
            ("competence_and_awareness", "能力与意识", "DO", "未提供责任人员能力评估和意识确认记录"),
            ("ghg_inventory_governance", "温室气体清单治理", "CHECK", "当前清单未形成完整现场边界、源类、因子、不确定度和修订证据"),
            ("internal_audit", "内部审核", "CHECK", "未提供独立于运行职责的内部审核报告"),
            ("corrective_actions", "不符合与纠正措施", "ACT", "未提供审核发现闭环或无发现声明"),
            ("management_review", "管理评审", "ACT", "未提供最高管理者评审输入、决定和资源批准"),
            ("independent_assurance", "独立保证签名", "ASSURANCE", "未配置可信公钥或未提供独立保证签名"),
        ]
        gates = [
            _gate(gate_id, label, stage, False, evidence)
            for gate_id, label, stage, evidence in gate_definitions
        ]
        payload: dict[str, Any] = {
            "schema_version": REPORT_SCHEMA_VERSION,
            "report_id": "management-system:offline-evidence-incomplete",
            "mode": "offline_evidence_readiness",
            "status": "blocked",
            "standards": {
                "energy_management_reference": "ISO 50001:2018",
                "energy_management_amendment": "ISO 50001:2018/Amd 1:2024",
                "ghg_inventory_reference": "ISO 14064-1:2018",
                "reference_version_locked": True,
                "software_interprets_proprietary_clauses": False,
            },
            "organization": {
                "system_id": None,
                "reporting_entity": None,
                "site_ids": [],
                "organizational_boundary": None,
                "operational_boundary": None,
                "policy_approved": False,
                "required_roles_assigned": 0,
                "required_roles_total": len(REQUIRED_ROLES),
            },
            "pdca": {
                "cycle_id": None,
                "cycle_period": None,
                "plan_passed": 0,
                "plan_total": 6,
                "do_passed": 0,
                "do_total": 4,
                "check_passed": 0,
                "check_total": 2,
                "act_passed": 0,
                "act_total": 2,
                "cycle_complete": False,
            },
            "performance": {
                "energy_baseline_kwh": None,
                "significant_energy_use_coverage_pct": 0.0,
                "monitoring_coverage_pct": 0.0,
                "enpi_count": 0,
                "objectives_total": 0,
                "objectives_on_target": 0,
                "action_plans_completed": 0,
                "inventory_source_coverage": None,
                "linked_inventory_status": inventory_status,
                "linked_inventory_evidence_sha256": inventory_evidence_sha256,
                "linked_measurement_verification_status": measurement_verification_status,
                "linked_measurement_verification_evidence_sha256": measurement_verification_evidence_sha256,
            },
            "audit": {
                "audit_id": None,
                "finding_count": None,
                "open_finding_count": None,
                "management_review_id": None,
                "independent_assurance_conclusion": None,
            },
            "gates": gates,
            "assurance": {
                "management_cycle_evidence_ready": False,
                "independent_assurance_evidence_accepted": False,
                "software_is_certification_body": False,
                "iso_50001_certified": False,
                "iso_14064_1_verified": False,
                "regulatory_inventory_claim_allowed": False,
                "blocker_codes": [item[0] for item in gate_definitions],
            },
            "production_boundary": {
                "simulation_mode": True,
                "site_management_evidence_verified": False,
                "software_can_issue_certification": False,
                "software_can_issue_verification_opinion": False,
                "regulatory_submission_allowed": False,
            },
            "input_evidence_sha256": None,
        }
        payload["evidence_sha256"] = _canonical_sha256(payload)
        return EnergyCarbonManagementReport(**payload)

    def evaluate(
        self,
        request: EnergyCarbonManagementRequest,
    ) -> EnergyCarbonManagementReport:
        request_payload = request.model_dump(mode="json")
        input_evidence_sha256 = _canonical_sha256(request_payload)
        cycle_start = request.cycle_period.start_at
        cycle_end = request.cycle_period.end_at

        standard_refs = set(request.context.standard_references)
        standard_versions_ready = bool(
            any(item.startswith("ISO 50001:2018") for item in standard_refs)
            and "ISO 14064-1:2018" in standard_refs
        )
        context_ready = bool(
            standard_versions_ready
            and request.context.climate_change_relevance_reviewed
            and request.context.applicable_requirements_sha256
            and request.context.context_review_sha256
        )

        policy_ready = bool(
            request.policy.approved_at <= request.policy.effective_at <= cycle_start
            and request.policy.communicated_at <= cycle_start
            and request.policy.continual_improvement_commitment
            and request.policy.information_and_resources_commitment
            and request.policy.top_management_id == request.context.approved_by
        )

        role_names = [item.role for item in request.roles]
        role_map = {item.role: item.person_id for item in request.roles}
        required_roles_ready = bool(
            set(role_names) == REQUIRED_ROLES
            and len(role_names) == len(set(role_names))
            and all(item.assigned_at <= cycle_start for item in request.roles)
            and role_map.get("top_management") == request.policy.top_management_id
            and role_map.get("internal_auditor")
            not in {
                role_map.get("top_management"),
                role_map.get("energy_manager"),
                role_map.get("ghg_inventory_owner"),
                role_map.get("operations_owner"),
            }
        )

        seus = request.energy_review.significant_energy_uses
        seu_ids = [item.seu_id for item in seus]
        total_seu_energy = sum(item.energy_use_kwh for item in seus)
        seu_coverage_pct = round(
            total_seu_energy / request.energy_review.total_energy_use_kwh * 100.0,
            3,
        )
        energy_review_ready = bool(
            len(seu_ids) == len(set(seu_ids))
            and request.energy_review.reviewed_at <= cycle_start
            and total_seu_energy <= request.energy_review.total_energy_use_kwh + 1e-6
            and seu_coverage_pct >= request.energy_review.minimum_seu_coverage_pct
            and request.energy_review.approved_by == role_map.get("energy_manager")
        )

        baseline_ready = bool(
            request.energy_baseline.period.end_at <= cycle_start
            and request.energy_baseline.frozen_at <= cycle_start
            and request.energy_baseline.approved_by == role_map.get("energy_manager")
        )

        enpi_ids = [item.enpi_id for item in request.enpis]
        objective_ids = [item.objective_id for item in request.objectives]
        objective_enpis = [item.enpi_id for item in request.objectives]
        enpi_by_id = {item.enpi_id: item for item in request.enpis}
        objectives_ready = bool(
            len(enpi_ids) == len(set(enpi_ids))
            and len(objective_ids) == len(set(objective_ids))
            and set(objective_enpis) == set(enpi_ids)
            and all(
                cycle_start <= item.measured_at <= cycle_end
                and item.owner_id == role_map.get("energy_manager")
                for item in request.enpis
            )
            and all(
                item.enpi_id in enpi_by_id
                and math.isclose(
                    item.target_value,
                    enpi_by_id[item.enpi_id].target_value,
                    rel_tol=1e-9,
                    abs_tol=1e-9,
                )
                and item.due_at <= cycle_end
                and item.owner_id == enpi_by_id[item.enpi_id].owner_id
                for item in request.objectives
            )
        )

        action_objective_ids = [item.objective_id for item in request.action_plans]
        action_ids = [item.action_id for item in request.action_plans]
        actions_ready = bool(
            len(action_ids) == len(set(action_ids))
            and set(action_objective_ids) == set(objective_ids)
            and all(
                cycle_start <= item.start_at <= item.due_at <= cycle_end
                and item.status == "completed"
                and item.completion_evidence_sha256
                for item in request.action_plans
            )
        )

        seu_meter_ids = {meter for item in seus for meter in item.meter_ids}
        monitoring_meter_ids = set(request.monitoring.meter_ids)
        monitoring_coverage_pct = round(
            min(
                100.0,
                request.monitoring.received_record_count
                / request.monitoring.expected_record_count
                * 100.0,
            ),
            3,
        )
        monitoring_ready = bool(
            len(request.monitoring.meter_ids) == len(monitoring_meter_ids)
            and seu_meter_ids <= monitoring_meter_ids
            and request.monitoring.received_record_count
            <= request.monitoring.expected_record_count
            and monitoring_coverage_pct >= request.monitoring.minimum_coverage_pct
            and request.monitoring.approved_by == role_map.get("energy_manager")
        )

        control_ids = [item.control_id for item in request.operational_controls]
        declared_control_ids = {
            control_id for item in seus for control_id in item.operational_control_ids
        }
        control_seu_ids = {item.seu_id for item in request.operational_controls}
        controls_ready = bool(
            len(control_ids) == len(set(control_ids))
            and set(control_ids) == declared_control_ids
            and control_seu_ids == set(seu_ids)
            and all(
                item.owner_id == role_map.get("operations_owner")
                for item in request.operational_controls
            )
        )

        competence_roles = [item.role for item in request.competence_records]
        competence_ready = bool(
            set(competence_roles) == REQUIRED_ROLES
            and len(competence_roles) == len(set(competence_roles))
            and all(
                role_map.get(item.role) == item.person_id
                and item.competence_assessed
                and item.awareness_acknowledged
                and item.completed_at <= cycle_start
                and item.valid_through >= cycle_end
                for item in request.competence_records
            )
        )

        inventory = request.ghg_inventory
        inventory_source_coverage_pct = round(
            min(
                100.0,
                inventory.reported_source_category_count
                / inventory.expected_source_category_count
                * 100.0,
            ),
            3,
        )
        inventory_ready = bool(
            inventory.inventory_period.start_at == cycle_start
            and inventory.inventory_period.end_at == cycle_end
            and inventory.expected_source_category_count >= 7
            and inventory.reported_source_category_count
            == inventory.expected_source_category_count
            and inventory.uncertainty_quantified
            and inventory.approved_by == role_map.get("ghg_inventory_owner")
        )

        audit = request.internal_audit
        audit_scope = set(audit.scope_references)
        audit_ready = bool(
            audit.independence_attested
            and audit.auditor_id == role_map.get("internal_auditor")
            and audit.completed_at >= cycle_end
            and "ISO 50001:2018" in audit_scope
            and "ISO 14064-1:2018" in audit_scope
            and len(audit.finding_ids) == len(set(audit.finding_ids))
        )

        corrective_by_finding = {
            item.finding_id: item for item in request.corrective_actions
        }
        corrective_ids_unique = len(request.corrective_actions) == len(
            {item.action_id for item in request.corrective_actions}
        )
        if audit.finding_ids:
            corrective_ready = bool(
                corrective_ids_unique
                and set(corrective_by_finding) == set(audit.finding_ids)
                and audit.conclusion != "conforming"
                and all(
                    item.status == "closed"
                    and item.closed_at is not None
                    and item.closed_at <= request.management_review.reviewed_at
                    and item.effectiveness_verified
                    for item in request.corrective_actions
                )
            )
        else:
            corrective_ready = bool(
                audit.conclusion == "conforming"
                and not request.corrective_actions
                and request.no_finding_declaration_sha256
            )

        latest_corrective_close = max(
            (
                item.closed_at
                for item in request.corrective_actions
                if item.closed_at is not None
            ),
            default=audit.completed_at,
        )
        management_review_ready = bool(
            request.management_review.chair_id == role_map.get("top_management")
            and request.management_review.reviewed_at >= audit.completed_at
            and request.management_review.reviewed_at >= latest_corrective_close
            and REQUIRED_REVIEW_TOPICS <= set(request.management_review.input_topics)
        )

        independent = request.independent_assurance
        independent_signature_valid = self._independent_signature_valid(request)
        assigned_people = set(role_map.values())
        independent_ready = bool(
            independent
            and independent.independence_attested
            and independent.conclusion == "accepted"
            and independent.reviewed_at >= request.management_review.reviewed_at
            and independent.reviewer_id not in assigned_people
            and independent_signature_valid
        )

        gates = [
            _gate("context_and_requirements", "组织环境与适用要求", "PLAN", context_ready, {"standard_references": sorted(standard_refs), "climate_change_relevance_reviewed": request.context.climate_change_relevance_reviewed}),
            _gate("policy_and_leadership", "能源与碳方针及领导承诺", "PLAN", policy_ready, request.policy.policy_id),
            _gate("roles_and_responsibilities", "职责、权限与职责分离", "PLAN", required_roles_ready, {"assigned_roles": sorted(set(role_names)), "required_roles": sorted(REQUIRED_ROLES)}),
            _gate("energy_review_and_seus", "能源评审与主要能源使用", "PLAN", energy_review_ready, {"review_id": request.energy_review.review_id, "seu_coverage_pct": seu_coverage_pct}),
            _gate("energy_baseline", "能源基准与调整规则", "PLAN", baseline_ready, request.energy_baseline.baseline_id),
            _gate("enpis_and_objectives", "能源绩效参数与目标", "PLAN", objectives_ready, {"enpi_count": len(request.enpis), "objective_count": len(request.objectives)}),
            _gate("action_plans_and_resources", "行动计划与资源", "DO", actions_ready, {"action_count": len(request.action_plans), "completed": sum(item.status == "completed" for item in request.action_plans)}),
            _gate("monitoring_measurement_analysis", "监视、测量、分析与校准", "DO", monitoring_ready, {"coverage_pct": monitoring_coverage_pct, "meter_ids": sorted(monitoring_meter_ids)}),
            _gate("operational_controls", "主要能源使用运行控制", "DO", controls_ready, sorted(control_ids)),
            _gate("competence_and_awareness", "能力与意识", "DO", competence_ready, {"covered_roles": sorted(set(competence_roles))}),
            _gate("ghg_inventory_governance", "温室气体清单治理", "CHECK", inventory_ready, {"report_id": inventory.inventory_report_id, "source_coverage_pct": inventory_source_coverage_pct, "revision_id": inventory.revision_id}),
            _gate("internal_audit", "内部审核", "CHECK", audit_ready, {"audit_id": audit.audit_id, "finding_ids": audit.finding_ids}),
            _gate("corrective_actions", "不符合与纠正措施", "ACT", corrective_ready, {"finding_count": len(audit.finding_ids), "closed_count": sum(item.status == "closed" for item in request.corrective_actions)}),
            _gate("management_review", "管理评审", "ACT", management_review_ready, {"review_id": request.management_review.review_id, "input_topics": sorted(set(request.management_review.input_topics))}),
            _gate("independent_assurance", "独立保证签名", "ASSURANCE", independent_ready, {"reviewer_id": independent.reviewer_id if independent else None, "key_id": independent.key_id if independent else None, "signature_valid": independent_signature_valid}),
        ]
        management_gates = gates[:-1]
        management_cycle_ready = all(item["passed"] for item in management_gates)
        evidence_package_passed = management_cycle_ready and independent_ready
        status = (
            "evidence_package_passed"
            if evidence_package_passed
            else "management_cycle_ready_pending_independent_assurance"
            if management_cycle_ready
            else "blocked"
        )

        stage_counts = {
            stage: {
                "passed": sum(item["passed"] for item in gates if item["stage"] == stage),
                "total": sum(1 for item in gates if item["stage"] == stage),
            }
            for stage in ("PLAN", "DO", "CHECK", "ACT", "ASSURANCE")
        }
        objectives_on_target = sum(
            (item.current_value <= item.target_value)
            if item.direction == "decrease"
            else (item.current_value >= item.target_value)
            for item in request.enpis
        )
        open_finding_count = sum(
            item.status != "closed" or not item.effectiveness_verified
            for item in request.corrective_actions
        )
        payload: dict[str, Any] = {
            "schema_version": REPORT_SCHEMA_VERSION,
            "report_id": f"management-system:{input_evidence_sha256[:24]}",
            "mode": "site_evidence_evaluation",
            "status": status,
            "standards": {
                "energy_management_reference": "ISO 50001:2018",
                "energy_management_amendment": "ISO 50001:2018/Amd 1:2024",
                "ghg_inventory_reference": "ISO 14064-1:2018",
                "submitted_references": sorted(standard_refs),
                "reference_version_locked": standard_versions_ready,
                "software_interprets_proprietary_clauses": False,
            },
            "organization": {
                "system_id": request.context.system_id,
                "reporting_entity": request.context.reporting_entity,
                "site_ids": request.context.site_ids,
                "organizational_boundary": request.context.organizational_boundary,
                "operational_boundary": request.context.operational_boundary,
                "policy_id": request.policy.policy_id,
                "policy_approved": policy_ready,
                "required_roles_assigned": len(set(role_names) & REQUIRED_ROLES),
                "required_roles_total": len(REQUIRED_ROLES),
            },
            "pdca": {
                "cycle_id": request.cycle_id,
                "cycle_period": request.cycle_period.model_dump(mode="json"),
                "plan_passed": stage_counts["PLAN"]["passed"],
                "plan_total": stage_counts["PLAN"]["total"],
                "do_passed": stage_counts["DO"]["passed"],
                "do_total": stage_counts["DO"]["total"],
                "check_passed": stage_counts["CHECK"]["passed"],
                "check_total": stage_counts["CHECK"]["total"],
                "act_passed": stage_counts["ACT"]["passed"],
                "act_total": stage_counts["ACT"]["total"],
                "cycle_complete": management_cycle_ready,
            },
            "performance": {
                "energy_baseline_kwh": request.energy_baseline.baseline_energy_kwh,
                "significant_energy_use_coverage_pct": seu_coverage_pct,
                "monitoring_coverage_pct": monitoring_coverage_pct,
                "enpi_count": len(request.enpis),
                "objectives_total": len(request.objectives),
                "objectives_on_target": objectives_on_target,
                "action_plans_completed": sum(item.status == "completed" for item in request.action_plans),
                "inventory_source_coverage": inventory_source_coverage_pct,
                "linked_inventory_status": "site_evidence_submitted",
                "linked_inventory_evidence_sha256": inventory.inventory_evidence_sha256,
                "linked_measurement_verification_status": "site_evidence_submitted",
                "linked_measurement_verification_evidence_sha256": inventory.measurement_verification_evidence_sha256,
            },
            "audit": {
                "audit_id": audit.audit_id,
                "audit_conclusion": audit.conclusion,
                "finding_count": len(audit.finding_ids),
                "open_finding_count": open_finding_count,
                "management_review_id": request.management_review.review_id,
                "independent_assurance_conclusion": independent.conclusion if independent else None,
            },
            "gates": gates,
            "assurance": {
                "management_cycle_evidence_ready": management_cycle_ready,
                "independent_assurance_evidence_accepted": independent_ready,
                "software_is_certification_body": False,
                "iso_50001_certified": False,
                "iso_14064_1_verified": False,
                "regulatory_inventory_claim_allowed": False,
                "blocker_codes": [item["gate_id"] for item in gates if not item["passed"]],
            },
            "production_boundary": {
                "simulation_mode": False,
                "site_management_evidence_verified": evidence_package_passed,
                "software_can_issue_certification": False,
                "software_can_issue_verification_opinion": False,
                "regulatory_submission_allowed": False,
            },
            "input_evidence_sha256": input_evidence_sha256,
        }
        payload["evidence_sha256"] = _canonical_sha256(payload)
        return EnergyCarbonManagementReport(**payload)

    def _independent_signature_valid(
        self,
        request: EnergyCarbonManagementRequest,
    ) -> bool:
        evidence = request.independent_assurance
        if evidence is None:
            return False
        public_key_text = self.auditor_public_keys.get(evidence.key_id, "")
        if not public_key_text:
            return False
        unsigned_payload = request.model_dump(mode="json")
        assurance_payload = dict(unsigned_payload.get("independent_assurance") or {})
        assurance_payload.pop("signature", None)
        assurance_payload.pop("signed_evidence_sha256", None)
        unsigned_payload["independent_assurance"] = assurance_payload
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


energy_carbon_management_service = EnergyCarbonManagementService(
    auditor_public_keys=settings.management_system_auditor_public_keys
)
