from __future__ import annotations

import base64
import binascii
from datetime import timedelta
import hashlib
import json
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from app.core.config import settings
from app.schemas.site_cutover import (
    APPROVAL_ROLES,
    MODULE_DOMAINS,
    REQUIRED_SHADOW_SCENARIOS,
    CutoverModuleEvidence,
    SiteCutoverReport,
    SiteCutoverRequest,
)


REPORT_SCHEMA_VERSION = "site-cutover-readiness.v1"


def canonical_sha256(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def module_signature_payload(evidence: CutoverModuleEvidence) -> dict[str, Any]:
    return evidence.model_dump(
        mode="json",
        exclude={"signed_payload_sha256", "signature"},
    )


def approval_subject_sha256(request: SiteCutoverRequest) -> str:
    return canonical_sha256(request.model_dump(mode="json", exclude={"approvals"}))


def _gate(gate_id: str, label_zh: str, passed: bool, evidence: Any) -> dict[str, Any]:
    return {
        "gate_id": gate_id,
        "label_zh": label_zh,
        "passed": passed,
        "evidence": evidence,
    }


class SiteCutoverService:
    def __init__(self, trusted_signers: dict[str, dict[str, str]] | None = None) -> None:
        self.trusted_signers = dict(
            settings.site_cutover_trusted_signers
            if trusted_signers is None
            else trusted_signers
        )

    @staticmethod
    def _production_boundary(eligible: bool) -> dict[str, bool]:
        return {
            "assessment_only": True,
            "cutover_plan_export_allowed": eligible,
            "automatic_cutover_allowed": False,
            "production_dispatch_allowed": False,
            "production_authority": False,
            "interlock_bypass_allowed": False,
            "external_change_control_required": True,
            "human_release_required": True,
            "rollback_owner_required": True,
        }

    def build_default(
        self,
        repository_reports: dict[str, dict[str, Any]] | None = None,
    ) -> SiteCutoverReport:
        reports = dict(repository_reports or {})
        domain_evidence = []
        for domain in sorted(MODULE_DOMAINS):
            report = dict(reports.get(domain) or {})
            domain_evidence.append(
                {
                    "domain": domain,
                    "repository_report_available": bool(report),
                    "schema_version": report.get("schema_version"),
                    "report_id": report.get("report_id"),
                    "report_status": report.get("report_status", "not_connected"),
                    "evidence_sha256": report.get("evidence_sha256"),
                    "site_bound": False,
                    "tenant_bound": False,
                    "window_bound": False,
                    "signature_valid": False,
                    "independently_accepted": False,
                }
            )
        definitions = [
            ("module_coverage", "十三域证据齐备", "未收到同一现场的十三域签名证据"),
            ("module_signatures", "逐域责任方签名", "未配置或未通过十三个责任域的独立签名"),
            ("site_tenant_window", "港口租户窗口一致", "报告尚未绑定同一港口、租户和验收窗口"),
            ("freshness_and_cutoff", "时效与数据截止对齐", "现场证据时效和数据截止一致性未核验"),
            ("module_acceptance", "逐域独立验收", "各域仍是仓库或离线状态，不是现场独立验收"),
            ("live_data_closed_loop", "实港实时数据闭环", "六类现场适配器和复合影子快照未核验"),
            ("metering_and_calibration", "计量标定与三方对账", "分路计量、标定、能量和账单对账未核验"),
            ("long_horizon_shadow", "长周期影子与异常覆盖", "180 天、旺淡季和六类异常场景未完成"),
            ("production_execution", "生产执行网关与联锁", "外部指令网关、设备检查、回执和联锁未核验"),
            ("takeover_and_rollback", "人工接管与回滚", "人工接管、超时降级和现场回滚演练未完成"),
            ("resilience_and_restore", "高可用与恢复实测", "备份恢复、恢复点目标和恢复时间目标未核验"),
            ("cyber_readiness", "网络安全事件准备", "安全事件演练或高严重度缺陷清零未核验"),
            ("training_and_change", "培训、规程与变更窗口", "培训覆盖、规程、运行手册和变更单未核验"),
            ("benefit_assurance", "效益归因与独立核证", "节能减排效益尚未由独立量测与验证接受"),
            ("binding_approvals", "六方绑定签字", "港口、运营、能碳、运行技术安全、信息安全和独立核证未签字"),
            ("application_authority_boundary", "应用权限分离", "尚未证明应用无生产授权和联锁绕过能力"),
        ]
        gates = [_gate(gate_id, label, False, reason) for gate_id, label, reason in definitions]
        payload: dict[str, Any] = {
            "schema_version": REPORT_SCHEMA_VERSION,
            "report_id": "site-cutover:site-evidence-incomplete",
            "mode": "repository_evidence_only",
            "status": "blocked",
            "source_readiness": {
                "required_domains": sorted(MODULE_DOMAINS),
                "required_domain_count": len(MODULE_DOMAINS),
                "repository_report_count": len(reports),
                "received_domain_count": 0,
                "signed_domain_count": 0,
                "accepted_domain_count": 0,
            },
            "domain_evidence": domain_evidence,
            "site_consistency": {
                "verified_site_id": None,
                "verified_tenant_id": None,
                "verified_window_id": None,
                "verified_data_cutoff_alignment_hours": None,
            },
            "operational_acceptance": {
                "verified_shadow_days": None,
                "verified_operating_seasons": None,
                "verified_shadow_scenarios": [],
                "verified_live_adapter_count": None,
                "verified_meter_coverage_pct": None,
                "verified_device_receipt_rate_pct": None,
                "verified_rollback_minutes": None,
                "verified_rpo_minutes": None,
                "verified_rto_minutes": None,
                "verified_training_coverage_pct": None,
            },
            "approval_summary": {
                "required_roles": sorted(APPROVAL_ROLES),
                "signed_roles": [],
                "approved_roles": [],
                "all_bound_to_package": False,
            },
            "gates": gates,
            "assurance": {
                "status": "blocked",
                "passed_gate_count": 0,
                "required_gate_count": len(gates),
                "eligible_for_external_cutover_review": False,
                "claim": "repository reports are not a site cutover package",
            },
            "production_boundary": self._production_boundary(False),
            "approval_subject_sha256": None,
            "input_evidence_sha256": None,
        }
        payload["evidence_sha256"] = canonical_sha256(payload)
        return SiteCutoverReport(**payload)

    def _verify_signature(self, key_id: str, authority: str, digest: str, signature: str) -> bool:
        signer = self.trusted_signers.get(key_id) or {}
        if signer.get("authority") != authority:
            return False
        try:
            public_key = Ed25519PublicKey.from_public_bytes(
                base64.b64decode(signer.get("public_key", ""), validate=True)
            )
            public_key.verify(base64.b64decode(signature, validate=True), bytes.fromhex(digest))
        except (ValueError, InvalidSignature, binascii.Error):
            return False
        return True

    def evaluate(self, request: SiteCutoverRequest) -> SiteCutoverReport:
        input_evidence_sha256 = canonical_sha256(request.model_dump(mode="json"))
        approval_subject = approval_subject_sha256(request)
        modules = request.module_evidence
        policy = request.policy
        operational = request.operational_evidence

        domain_counts = {domain: 0 for domain in MODULE_DOMAINS}
        for item in modules:
            domain_counts[item.domain] += 1
        module_coverage = len(modules) == len(MODULE_DOMAINS) and all(
            count == 1 for count in domain_counts.values()
        )

        module_digest_results: dict[str, bool] = {}
        module_signature_results: dict[str, bool] = {}
        for item in modules:
            digest = canonical_sha256(module_signature_payload(item))
            module_digest_results[item.domain] = item.signed_payload_sha256 == digest
            module_signature_results[item.domain] = bool(
                module_digest_results[item.domain]
                and self._verify_signature(item.key_id, item.domain, digest, item.signature)
            )
        module_signatures_ready = bool(
            module_coverage
            and len(module_signature_results) == len(MODULE_DOMAINS)
            and all(module_signature_results.values())
        )

        site_tenant_window_ready = bool(
            module_coverage
            and all(item.site_id == policy.site_id for item in modules)
            and all(item.tenant_id == policy.tenant_id for item in modules)
            and all(item.assessment_window_id == policy.window.window_id for item in modules)
        )
        cutoffs = [item.data_cutoff_at for item in modules]
        cutoff_alignment_hours = (
            (max(cutoffs) - min(cutoffs)).total_seconds() / 3600 if cutoffs else None
        )
        allowed_shadow_domains = {
            "production_execution",
            "long_horizon_shadow",
            "algorithm_production",
        }
        freshness_ready = bool(
            module_coverage
            and cutoff_alignment_hours is not None
            and cutoff_alignment_hours <= policy.maximum_data_cutoff_alignment_hours
            and all(policy.window.start_at <= item.data_cutoff_at <= policy.window.end_at for item in modules)
            and all(item.data_cutoff_at <= item.observed_at <= request.evaluated_at for item in modules)
            and all(
                request.evaluated_at - item.observed_at
                <= timedelta(days=policy.maximum_module_age_days)
                for item in modules
            )
            and all(
                item.source_mode == "live_site"
                or (item.domain in allowed_shadow_domains and item.source_mode == "production_shadow")
                for item in modules
            )
        )
        module_acceptance_ready = bool(
            module_coverage
            and all(item.independently_verified for item in modules)
            and all(item.acceptance_conclusion == "accepted" for item in modules)
            and all(not item.exception_ids for item in modules)
        )

        live_data_ready = bool(
            operational.required_live_adapter_count >= 6
            and operational.ready_live_adapter_count == operational.required_live_adapter_count
            and operational.accepted_live_snapshot_count >= 1_000
            and operational.composite_shadow_release_count >= 100
        )
        metering_ready = bool(
            operational.meter_coverage_pct == 100
            and operational.calibrated_meter_coverage_pct == 100
            and operational.energy_balance_error_pct <= policy.maximum_energy_balance_error_pct
            and operational.bill_reconciliation_error_pct
            <= policy.maximum_bill_reconciliation_error_pct
        )
        shadow_ready = bool(
            operational.shadow_run_days >= policy.minimum_shadow_days
            and len(set(operational.operating_seasons)) >= policy.minimum_operating_season_count
            and REQUIRED_SHADOW_SCENARIOS.issubset(operational.covered_shadow_scenarios)
        )
        execution_ready = bool(
            operational.production_instruction_gateway_external
            and operational.device_capability_checks_passed
            and operational.independent_plc_interlocks_tested
            and operational.device_receipt_rate_pct == 100
            and operational.command_timeout_fallback_tested
        )
        takeover_ready = bool(
            operational.human_takeover_drill_passed
            and operational.rollback_drill_passed
            and operational.measured_rollback_minutes <= policy.maximum_rollback_minutes
        )
        resilience_ready = bool(
            operational.backup_restore_drill_passed
            and operational.measured_rpo_minutes <= policy.maximum_rpo_minutes
            and operational.measured_rto_minutes <= policy.maximum_rto_minutes
        )
        cyber_ready = bool(
            operational.cyber_incident_exercise_passed
            and operational.unresolved_severity_1_count == 0
            and operational.unresolved_severity_2_count == 0
        )
        training_change_ready = bool(
            operational.operator_training_coverage_pct == 100
            and operational.change_ticket_id.strip()
            and operational.change_window_end_at > operational.change_window_start_at
        )
        benefit_ready = operational.independent_mv_accepted
        authority_boundary_ready = operational.production_authority_disabled_in_application

        approval_counts = {role: 0 for role in APPROVAL_ROLES}
        approval_binding_results: dict[str, bool] = {}
        approval_signature_results: dict[str, bool] = {}
        for approval in request.approvals:
            approval_counts[approval.role] += 1
            approval_binding_results[approval.role] = bool(
                approval.acceptance_package_sha256 == approval_subject
                and policy.window.end_at <= approval.approved_at <= request.evaluated_at
            )
            approval_signature_results[approval.role] = bool(
                approval_binding_results[approval.role]
                and self._verify_signature(
                    approval.key_id,
                    approval.role,
                    approval_subject,
                    approval.signature,
                )
            )
        approvals_ready = bool(
            len(request.approvals) == len(APPROVAL_ROLES)
            and all(count == 1 for count in approval_counts.values())
            and all(approval.decision == "approved" for approval in request.approvals)
            and len(approval_signature_results) == len(APPROVAL_ROLES)
            and all(approval_signature_results.values())
        )
        approval_preconditions_ready = bool(
            len(request.approvals) == len(APPROVAL_ROLES)
            and all(count == 1 for count in approval_counts.values())
            and all(approval.decision == "approved" for approval in request.approvals)
            and len(approval_binding_results) == len(APPROVAL_ROLES)
            and all(approval_binding_results.values())
        )

        gates = [
            _gate("module_coverage", "十三域证据齐备", module_coverage, domain_counts),
            _gate("module_signatures", "逐域责任方签名", module_signatures_ready, module_signature_results),
            _gate("site_tenant_window", "港口租户窗口一致", site_tenant_window_ready, {"site_id": policy.site_id, "tenant_id": policy.tenant_id, "window_id": policy.window.window_id}),
            _gate("freshness_and_cutoff", "时效与数据截止对齐", freshness_ready, {"alignment_hours": cutoff_alignment_hours, "maximum_hours": policy.maximum_data_cutoff_alignment_hours}),
            _gate("module_acceptance", "逐域独立验收", module_acceptance_ready, {item.domain: item.acceptance_conclusion for item in modules}),
            _gate("live_data_closed_loop", "实港实时数据闭环", live_data_ready, {"ready_adapters": operational.ready_live_adapter_count, "required_adapters": operational.required_live_adapter_count, "accepted_snapshots": operational.accepted_live_snapshot_count, "composite_releases": operational.composite_shadow_release_count}),
            _gate("metering_and_calibration", "计量标定与三方对账", metering_ready, {"meter_coverage_pct": operational.meter_coverage_pct, "calibrated_meter_coverage_pct": operational.calibrated_meter_coverage_pct, "energy_balance_error_pct": operational.energy_balance_error_pct, "bill_reconciliation_error_pct": operational.bill_reconciliation_error_pct}),
            _gate("long_horizon_shadow", "长周期影子与异常覆盖", shadow_ready, {"shadow_days": operational.shadow_run_days, "seasons": operational.operating_seasons, "scenarios": operational.covered_shadow_scenarios}),
            _gate("production_execution", "生产执行网关与联锁", execution_ready, {"receipt_rate_pct": operational.device_receipt_rate_pct, "external_gateway": operational.production_instruction_gateway_external}),
            _gate("takeover_and_rollback", "人工接管与回滚", takeover_ready, {"rollback_minutes": operational.measured_rollback_minutes, "maximum_minutes": policy.maximum_rollback_minutes}),
            _gate("resilience_and_restore", "高可用与恢复实测", resilience_ready, {"rpo_minutes": operational.measured_rpo_minutes, "rto_minutes": operational.measured_rto_minutes}),
            _gate("cyber_readiness", "网络安全事件准备", cyber_ready, {"severity_1": operational.unresolved_severity_1_count, "severity_2": operational.unresolved_severity_2_count}),
            _gate("training_and_change", "培训、规程与变更窗口", training_change_ready, {"training_coverage_pct": operational.operator_training_coverage_pct, "change_ticket_id": operational.change_ticket_id}),
            _gate("benefit_assurance", "效益归因与独立核证", benefit_ready, {"independent_mv_accepted": operational.independent_mv_accepted}),
            _gate("binding_approvals", "六方绑定签字", approvals_ready, approval_signature_results),
            _gate("application_authority_boundary", "应用权限分离", authority_boundary_ready, {"production_authority_disabled_in_application": operational.production_authority_disabled_in_application}),
        ]
        all_ready = all(gate["passed"] for gate in gates)
        non_attestation_ready = all(
            gate["passed"]
            for gate in gates
            if gate["gate_id"] not in {"module_signatures", "binding_approvals"}
        )
        pending_only_on_trust_configuration = bool(
            non_attestation_ready
            and len(module_digest_results) == len(MODULE_DOMAINS)
            and all(module_digest_results.values())
            and approval_preconditions_ready
        )
        status = (
            "eligible_for_external_cutover_review"
            if all_ready
            else "reconciled_pending_attestation"
            if pending_only_on_trust_configuration
            else "blocked"
        )

        domain_evidence = [
            {
                "domain": item.domain,
                "schema_version": item.schema_version,
                "report_id": item.report_id,
                "report_status": item.report_status,
                "evidence_sha256": item.evidence_sha256,
                "source_mode": item.source_mode,
                "owner_system": item.owner_system,
                "signature_valid": module_signature_results.get(item.domain, False),
                "independently_accepted": bool(
                    item.independently_verified
                    and item.acceptance_conclusion == "accepted"
                    and not item.exception_ids
                ),
            }
            for item in sorted(modules, key=lambda value: value.domain)
        ]
        payload: dict[str, Any] = {
            "schema_version": REPORT_SCHEMA_VERSION,
            "report_id": f"site-cutover:{request.case_id}:{input_evidence_sha256[:16]}",
            "mode": "signed_site_cutover_assessment",
            "status": status,
            "source_readiness": {
                "required_domains": sorted(MODULE_DOMAINS),
                "required_domain_count": len(MODULE_DOMAINS),
                "repository_report_count": len(MODULE_DOMAINS),
                "received_domain_count": len(set(item.domain for item in modules)),
                "signed_domain_count": sum(module_signature_results.values()),
                "accepted_domain_count": sum(
                    item.independently_verified
                    and item.acceptance_conclusion == "accepted"
                    and not item.exception_ids
                    for item in modules
                ),
            },
            "domain_evidence": domain_evidence,
            "site_consistency": {
                "verified_site_id": policy.site_id if all_ready else None,
                "verified_tenant_id": policy.tenant_id if all_ready else None,
                "verified_window_id": policy.window.window_id if all_ready else None,
                "verified_data_cutoff_alignment_hours": round(cutoff_alignment_hours, 3) if all_ready and cutoff_alignment_hours is not None else None,
            },
            "operational_acceptance": {
                "verified_shadow_days": operational.shadow_run_days if all_ready else None,
                "verified_operating_seasons": operational.operating_seasons if all_ready else None,
                "verified_shadow_scenarios": operational.covered_shadow_scenarios if all_ready else [],
                "verified_live_adapter_count": operational.ready_live_adapter_count if all_ready else None,
                "verified_meter_coverage_pct": operational.meter_coverage_pct if all_ready else None,
                "verified_device_receipt_rate_pct": operational.device_receipt_rate_pct if all_ready else None,
                "verified_rollback_minutes": operational.measured_rollback_minutes if all_ready else None,
                "verified_rpo_minutes": operational.measured_rpo_minutes if all_ready else None,
                "verified_rto_minutes": operational.measured_rto_minutes if all_ready else None,
                "verified_training_coverage_pct": operational.operator_training_coverage_pct if all_ready else None,
            },
            "approval_summary": {
                "required_roles": sorted(APPROVAL_ROLES),
                "signed_roles": sorted(role for role, valid in approval_signature_results.items() if valid),
                "approved_roles": sorted(approval.role for approval in request.approvals if approval.decision == "approved"),
                "all_bound_to_package": approvals_ready,
            },
            "gates": gates,
            "assurance": {
                "status": status,
                "passed_gate_count": sum(gate["passed"] for gate in gates),
                "required_gate_count": len(gates),
                "eligible_for_external_cutover_review": all_ready,
                "claim": "external human cutover review eligibility; not software production authority",
            },
            "production_boundary": self._production_boundary(all_ready),
            "approval_subject_sha256": approval_subject,
            "input_evidence_sha256": input_evidence_sha256,
        }
        payload["evidence_sha256"] = canonical_sha256(payload)
        return SiteCutoverReport(**payload)


site_cutover_service = SiteCutoverService()
