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
from app.schemas.enterprise_security import (
    SOURCE_DOMAINS,
    EnterpriseSecurityReport,
    EnterpriseSecurityRequest,
)


REPORT_SCHEMA_VERSION = "enterprise-platform-ot-security.v1"
REQUIRED_FRAMEWORKS = {
    "NIST SP 800-82 Rev.3",
    "NIST SP 800-207",
    "NIST SP 800-63C-4",
}
REQUIRED_OT_ZONES = {"enterprise_it", "industrial_dmz", "ot_control", "safety_system"}


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def source_domain_payload(request: EnterpriseSecurityRequest, domain: str) -> dict[str, Any]:
    if domain == "identity_provider":
        payload: Any = request.identity.model_dump(mode="json")
    elif domain == "authorization_and_tenant_control":
        payload = request.authorization_and_tenant.model_dump(mode="json")
    elif domain == "message_and_timeseries_platform":
        payload = request.messaging_and_timeseries.model_dump(mode="json")
    elif domain == "ha_orchestrator":
        payload = request.high_availability.model_dump(mode="json")
    elif domain == "backup_dr_platform":
        payload = request.backup_and_dr.model_dump(mode="json")
    elif domain == "worm_siem_platform":
        payload = request.audit_and_siem.model_dump(mode="json")
    elif domain == "pki_key_management":
        payload = request.pki_and_keys.model_dump(mode="json")
    elif domain == "ot_security_monitor":
        payload = request.ot_security.model_dump(mode="json")
    elif domain == "enterprise_governance":
        payload = {
            "policy": request.policy.model_dump(mode="json"),
            "approvals": [item.model_dump(mode="json") for item in request.approvals],
        }
    else:
        raise ValueError(f"unknown enterprise security source domain: {domain}")
    return {"domain": domain, "payload": payload}


def _gate(gate_id: str, label_zh: str, passed: bool, evidence: Any) -> dict[str, Any]:
    return {
        "gate_id": gate_id,
        "label_zh": label_zh,
        "passed": bool(passed),
        "evidence": evidence,
    }


def _tls_rank(version: str) -> int:
    return {"TLS1.2": 2, "TLS1.3": 3}.get(version, 0)


class EnterpriseSecurityService:
    """Assess enterprise and OT safeguards without granting a production cutover."""

    def __init__(self, source_public_keys: dict[str, str] | None = None) -> None:
        self.source_public_keys = (
            settings.enterprise_security_public_keys
            if source_public_keys is None
            else source_public_keys
        )

    def build_default(self) -> EnterpriseSecurityReport:
        definitions = [
            ("source_domain_coverage", "九类安全来源齐备", "未接入九类企业与运行技术安全责任系统"),
            ("source_signatures", "逐源数字签名", "未配置独立安全来源公钥和签名"),
            ("source_time_and_live", "来源时效、对齐与现场实数", "当前仅有仓库内控制，不是现场平台证据"),
            ("governance_frameworks", "安全架构与标准治理", "未提供获批架构、风险评估和版本化标准基线"),
            ("federated_identity", "联合身份与令牌核验", "可执行 OIDC 验签代码已具备，未配置现场身份提供方"),
            ("mfa_and_identity_lifecycle", "多因素认证与身份生命周期", "未提供多因素认证、离职回收和应急账户演练证据"),
            ("named_rbac_least_privilege", "具名用户、角色和最小权限", "现有 API 密钥仍是角色级共享身份"),
            ("segregation_and_privileged_review", "职责分离与特权复核", "未提供现场策略测试和特权访问复核"),
            ("tenant_isolation", "组织租户端到端隔离", "OIDC 租户上下文已实现，外部数据库和时序存储隔离未证明"),
            ("durable_messaging", "可靠消息总线", "仓库未部署外部高可用消息集群"),
            ("timeseries_resilience", "时序数据库复制与租户分区", "当前使用进程内和文件状态，不是生产时序集群"),
            ("ha_topology", "多实例与无单点拓扑", "当前 Compose 是单实例"),
            ("failover_and_slo", "故障切换与可用性目标", "未提供负载均衡、故障切换和容量演练"),
            ("immutable_backups", "加密、不可变和异地备份", "本地持久卷不是不可变异地备份"),
            ("restore_rpo_rto", "恢复演练与恢复目标", "未提供恢复点和恢复时间实测"),
            ("worm_audit_retention", "外部 WORM 审计与留存", "本地哈希链可检篡改，但没有外部留存锁"),
            ("siem_detection_response", "安全信息事件管理检测响应", "未接入集中检测规则和事件工单"),
            ("mtls_and_key_rotation", "双向 TLS、密钥托管与轮换", "未配置现场 PKI、密钥托管和吊销演练"),
            ("ot_segmentation_remote_access", "运行技术分区与远程访问", "未提供工业隔离区、允许通道和跳板机证据"),
            ("ot_safety_and_approvals", "运行技术安全联锁与三方批准", "独立联锁、人工控制和三方验收未提供"),
        ]
        gates = [_gate(gate_id, label, False, reason) for gate_id, label, reason in definitions]
        payload: dict[str, Any] = {
            "schema_version": REPORT_SCHEMA_VERSION,
            "report_id": "enterprise-security:site-evidence-incomplete",
            "mode": "repository_controls_only",
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
            "current_repository_controls": {
                "oidc_eddsa_validation_available": True,
                "issuer_audience_time_validation_available": True,
                "named_subject_audit_available": True,
                "signed_tenant_context_enforcement_available": True,
                "role_authorization_available": True,
                "request_rate_and_body_limits_available": True,
                "local_hash_chain_audit_available": True,
                "container_hardening_configured": True,
                "single_instance_runtime": True,
                "external_worm_siem_verified": False,
                "external_ha_dr_verified": False,
                "ot_network_and_interlock_verified": False,
            },
            "identity_and_access": {
                "configured_mode": settings.api_auth_mode,
                "verified_identity_provider": None,
                "verified_named_user_count": None,
                "verified_mfa_enforced": None,
            },
            "tenant_isolation": {
                "verified_organization_count": None,
                "verified_cross_tenant_rejection_rate_pct": None,
                "verified_storage_isolation": None,
            },
            "messaging_and_timeseries": {
                "verified_broker_nodes": None,
                "verified_message_ack_rate_pct": None,
                "verified_timeseries_nodes": None,
                "verified_timeseries_replication_factor": None,
            },
            "availability_and_recovery": {
                "verified_availability_pct": None,
                "verified_failover_minutes": None,
                "verified_rpo_minutes": None,
                "verified_rto_minutes": None,
            },
            "audit_and_monitoring": {
                "local_hash_chain_only": True,
                "verified_worm_retention_days": None,
                "verified_siem_delivery_rate_pct": None,
                "verified_detection_minutes": None,
            },
            "pki_and_key_management": {
                "verified_minimum_tls_version": None,
                "verified_mtls_boundaries": None,
                "verified_maximum_key_age_days": None,
            },
            "ot_security": {
                "verified_zone_count": None,
                "verified_asset_inventory_coverage_pct": None,
                "verified_independent_safety_interlock": None,
            },
            "gates": gates,
            "assurance": {
                "status": "blocked",
                "passed_gate_count": 0,
                "required_gate_count": len(gates),
                "enterprise_security_verified": False,
                "claim": "repository controls are not site deployment evidence",
            },
            "production_boundary": {
                "assessment_only": True,
                "automatic_security_configuration_allowed": False,
                "enterprise_cutover_authorized": False,
                "ot_command_authority": False,
                "safety_interlock_bypass_allowed": False,
                "security_certification_claim_allowed": False,
                "production_authority": False,
                "human_release_required": True,
            },
            "input_evidence_sha256": None,
        }
        payload["evidence_sha256"] = canonical_sha256(payload)
        return EnterpriseSecurityReport(**payload)

    def _verify_signatures(self, request: EnterpriseSecurityRequest) -> dict[str, bool]:
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

    def evaluate(self, request: EnterpriseSecurityRequest) -> EnterpriseSecurityReport:
        policy = request.policy
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

        governance_ready = bool(
            REQUIRED_FRAMEWORKS.issubset(set(policy.framework_versions))
            and policy.window.start_at <= request.evaluated_at <= policy.window.end_at
        )
        identity = request.identity
        federated_identity_ready = bool(
            identity.issuer.startswith("https://")
            and identity.audience
            and len(identity.active_signing_key_ids) >= 2
            and identity.sampled_successful_logins > 0
            and identity.rejected_invalid_token_tests > 0
        )
        identity_lifecycle_ready = bool(
            identity.mfa_enforced
            and identity.phishing_resistant_mfa_for_privileged_users
            and identity.automated_deprovisioning
            and identity.maximum_deprovisioning_minutes <= 60
            and identity.dormant_accounts_disabled
            and identity.break_glass_accounts_monitored_and_tested
        )

        authorization = request.authorization_and_tenant
        named_rbac_ready = bool(
            authorization.named_user_count > 0
            and authorization.role_binding_count >= authorization.named_user_count
            and authorization.least_privilege_review_completed
            and authorization.denied_unauthorized_test_count > 0
        )
        segregation_ready = bool(
            authorization.privileged_access_review_completed
            and authorization.segregation_of_duties_test_count > 0
        )
        tenant_keys = authorization.tenant_encryption_key_ids
        tenant_ready = bool(
            set(authorization.organization_ids) == set(tenant_keys)
            and len(set(tenant_keys.values())) == len(tenant_keys)
            and authorization.cross_tenant_test_count
            == authorization.cross_tenant_rejected_count
            and authorization.row_level_security_enforced
            and authorization.tenant_partition_keys_enforced
        )

        platform = request.messaging_and_timeseries
        message_ack_rate = (
            platform.acknowledged_message_count / platform.published_message_count * 100
        )
        messaging_ready = bool(
            platform.broker_cluster_nodes >= 3
            and platform.broker_quorum_enabled
            and platform.durable_messages_enabled
            and platform.producer_idempotency_enabled
            and platform.consumer_acknowledgements_enabled
            and platform.schema_registry_enforced
            and platform.dead_letter_queue_enabled
            and platform.replay_drill_passed
            and message_ack_rate >= 99.9
            and platform.duplicate_effect_count == 0
        )
        timeseries_ready = bool(
            platform.timeseries_cluster_nodes >= 2
            and platform.timeseries_replication_factor >= 2
            and platform.timeseries_retention_days >= 30
            and platform.timeseries_backup_export_verified
            and platform.tenant_partition_enforced
        )

        ha = request.high_availability
        ha_topology_ready = bool(
            ha.api_replica_count >= 2
            and ha.worker_replica_count >= 2
            and ha.availability_zone_count >= 2
            and ha.database_replica_count >= 2
            and ha.load_balancer_health_checks_enabled
            and ha.automatic_failover_enabled
            and ha.split_brain_prevention_enabled
        )
        failover_ready = bool(
            ha.failover_drill_passed
            and ha.measured_failover_minutes <= policy.maximum_rto_minutes
            and ha.measured_availability_pct >= policy.availability_slo_pct
            and ha.capacity_after_single_failure_pct >= 100
        )

        backup = request.backup_and_dr
        immutable_backup_ready = bool(
            backup.encrypted_backups
            and backup.immutable_backups
            and backup.geographically_separate_copy
            and backup.offline_recovery_copy
            and backup.backup_retention_days >= 30
        )
        recovery_ready = bool(
            backup.restore_drill_passed
            and backup.restored_data_hash_matches
            and backup.measured_rpo_minutes <= policy.maximum_rpo_minutes
            and backup.measured_rto_minutes <= policy.maximum_rto_minutes
        )

        audit = request.audit_and_siem
        delivery_rate = audit.delivered_event_count / audit.generated_event_count * 100
        worm_ready = bool(
            audit.external_worm_sink_enabled
            and audit.retention_lock_enabled
            and audit.retention_days >= policy.minimum_audit_retention_days
            and audit.hash_chain_verified
            and delivery_rate >= 99.9
            and audit.clock_synchronization_verified
            and audit.sensitive_field_redaction_verified
        )
        siem_ready = bool(
            audit.siem_detection_rule_count >= 5
            and audit.detection_drill_passed
            and audit.tested_incident_ticket_id
            and audit.maximum_detection_minutes <= 15
        )

        pki = request.pki_and_keys
        pki_ready = bool(
            _tls_rank(pki.minimum_tls_version) >= _tls_rank(policy.minimum_tls_version)
            and pki.mtls_user_to_api
            and pki.mtls_service_to_service
            and pki.mtls_it_dmz_boundary
            and pki.mtls_dmz_ot_boundary
            and pki.expired_certificate_count == 0
            and pki.maximum_certificate_days_remaining <= 397
            and pki.maximum_active_key_age_days <= policy.maximum_key_age_days
            and pki.key_rotation_drill_passed
            and pki.revocation_drill_passed
            and pki.secrets_manager_enabled
            and pki.root_keys_hardware_protected
            and pki.repository_secret_scan_clean
        )

        ot = request.ot_security
        ot_segmentation_ready = bool(
            REQUIRED_OT_ZONES.issubset(set(ot.security_zones))
            and ot.allowlisted_conduit_count > 0
            and ot.default_deny_between_zones
            and ot.direct_internet_to_ot_blocked
            and ot.read_only_it_ot_gateway
            and ot.outbound_ot_egress_allowlisted
            and ot.remote_access_jump_host_enforced
            and ot.remote_access_mfa_enforced
            and ot.remote_sessions_recorded
            and ot.vendor_access_just_in_time
            and ot.asset_inventory_coverage_pct >= 95
            and ot.vulnerability_remediation_within_policy_pct >= 95
        )
        approval_roles = {
            item.role for item in request.approvals if item.decision == "approved"
        }
        approvers = [item.approver_id for item in request.approvals]
        approval_ready = bool(
            len(request.approvals) == 3
            and approval_roles
            == {"enterprise_owner", "chief_information_security_officer", "ot_security_owner"}
            and len(approvers) == len(set(approvers))
            and all(
                item.security_architecture_sha256 == policy.security_architecture_sha256
                for item in request.approvals
            )
        )
        ot_safety_ready = bool(
            ot.ot_incident_exercise_passed
            and ot.independent_safety_interlock_tested
            and ot.local_manual_control_retained
            and ot.application_command_authority_disabled
            and approval_ready
        )

        gates = [
            _gate("source_domain_coverage", "九类安全来源齐备", coverage_ready, sorted(unique_domains)),
            _gate("source_signatures", "逐源数字签名", signature_ready, signature_results),
            _gate(
                "source_time_and_live",
                "来源时效、对齐与现场实数",
                time_live_ready,
                {"ages_seconds": ages, "observation_skew_seconds": skew if math.isfinite(skew) else None},
            ),
            _gate("governance_frameworks", "安全架构与标准治理", governance_ready, policy.framework_versions),
            _gate("federated_identity", "联合身份与令牌核验", federated_identity_ready, identity.issuer),
            _gate("mfa_and_identity_lifecycle", "多因素认证与身份生命周期", identity_lifecycle_ready, identity.model_dump(mode="json")),
            _gate("named_rbac_least_privilege", "具名用户、角色和最小权限", named_rbac_ready, authorization.named_user_count),
            _gate("segregation_and_privileged_review", "职责分离与特权复核", segregation_ready, authorization.segregation_of_duties_test_count),
            _gate("tenant_isolation", "组织租户端到端隔离", tenant_ready, authorization.organization_ids),
            _gate("durable_messaging", "可靠消息总线", messaging_ready, {"ack_rate_pct": round(message_ack_rate, 6), "nodes": platform.broker_cluster_nodes}),
            _gate("timeseries_resilience", "时序数据库复制与租户分区", timeseries_ready, {"nodes": platform.timeseries_cluster_nodes, "replication_factor": platform.timeseries_replication_factor}),
            _gate("ha_topology", "多实例与无单点拓扑", ha_topology_ready, ha.model_dump(mode="json")),
            _gate("failover_and_slo", "故障切换与可用性目标", failover_ready, {"availability_pct": ha.measured_availability_pct, "failover_minutes": ha.measured_failover_minutes}),
            _gate("immutable_backups", "加密、不可变和异地备份", immutable_backup_ready, backup.backup_ids),
            _gate("restore_rpo_rto", "恢复演练与恢复目标", recovery_ready, {"rpo_minutes": backup.measured_rpo_minutes, "rto_minutes": backup.measured_rto_minutes}),
            _gate("worm_audit_retention", "外部 WORM 审计与留存", worm_ready, {"delivery_rate_pct": round(delivery_rate, 6), "retention_days": audit.retention_days}),
            _gate("siem_detection_response", "安全信息事件管理检测响应", siem_ready, {"rule_count": audit.siem_detection_rule_count, "detection_minutes": audit.maximum_detection_minutes}),
            _gate("mtls_and_key_rotation", "双向 TLS、密钥托管与轮换", pki_ready, {"tls": pki.minimum_tls_version, "maximum_key_age_days": pki.maximum_active_key_age_days}),
            _gate("ot_segmentation_remote_access", "运行技术分区与远程访问", ot_segmentation_ready, ot.security_zones),
            _gate("ot_safety_and_approvals", "运行技术安全联锁与三方批准", ot_safety_ready, {"approval_roles": sorted(approval_roles), "approvers": approvers}),
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
        payload: dict[str, Any] = {
            "schema_version": REPORT_SCHEMA_VERSION,
            "report_id": f"enterprise-security:{request.case_id}:{input_evidence_sha256[:16]}",
            "mode": "signed_enterprise_and_ot_security_evidence",
            "status": status,
            "source_readiness": {
                "required_domains": sorted(SOURCE_DOMAINS),
                "received_domains": sorted(unique_domains),
                "signed_domains": sorted(domain for domain, passed in signature_results.items() if passed),
                "live_verified_domains": sorted(item.domain for item in request.source_attestations if item.live_data_verified),
                "domain_count": len(unique_domains),
                "required_domain_count": len(SOURCE_DOMAINS),
                "maximum_observation_skew_seconds": round(skew, 6) if math.isfinite(skew) else None,
            },
            "current_repository_controls": self.build_default().current_repository_controls,
            "identity_and_access": {
                "calculated_identity_provider": identity.issuer,
                "calculated_named_user_count": authorization.named_user_count,
                "verified_identity_provider": identity.issuer if all_ready else None,
                "verified_named_user_count": authorization.named_user_count if all_ready else None,
                "verified_mfa_enforced": True if all_ready else None,
            },
            "tenant_isolation": {
                "calculated_organization_count": len(authorization.organization_ids),
                "calculated_cross_tenant_rejection_rate_pct": round(authorization.cross_tenant_rejected_count / authorization.cross_tenant_test_count * 100, 6),
                "verified_organization_count": len(authorization.organization_ids) if all_ready else None,
                "verified_cross_tenant_rejection_rate_pct": 100.0 if all_ready else None,
                "verified_storage_isolation": True if all_ready else None,
            },
            "messaging_and_timeseries": {
                "calculated_message_ack_rate_pct": round(message_ack_rate, 6),
                "verified_broker_nodes": platform.broker_cluster_nodes if all_ready else None,
                "verified_message_ack_rate_pct": round(message_ack_rate, 6) if all_ready else None,
                "verified_timeseries_nodes": platform.timeseries_cluster_nodes if all_ready else None,
                "verified_timeseries_replication_factor": platform.timeseries_replication_factor if all_ready else None,
            },
            "availability_and_recovery": {
                "calculated_availability_pct": ha.measured_availability_pct,
                "calculated_failover_minutes": ha.measured_failover_minutes,
                "calculated_rpo_minutes": backup.measured_rpo_minutes,
                "calculated_rto_minutes": backup.measured_rto_minutes,
                "verified_availability_pct": ha.measured_availability_pct if all_ready else None,
                "verified_failover_minutes": ha.measured_failover_minutes if all_ready else None,
                "verified_rpo_minutes": backup.measured_rpo_minutes if all_ready else None,
                "verified_rto_minutes": backup.measured_rto_minutes if all_ready else None,
            },
            "audit_and_monitoring": {
                "calculated_delivery_rate_pct": round(delivery_rate, 6),
                "local_hash_chain_only": False if all_ready else True,
                "verified_worm_retention_days": audit.retention_days if all_ready else None,
                "verified_siem_delivery_rate_pct": round(delivery_rate, 6) if all_ready else None,
                "verified_detection_minutes": audit.maximum_detection_minutes if all_ready else None,
            },
            "pki_and_key_management": {
                "verified_minimum_tls_version": pki.minimum_tls_version if all_ready else None,
                "verified_mtls_boundaries": 4 if all_ready else None,
                "verified_maximum_key_age_days": pki.maximum_active_key_age_days if all_ready else None,
            },
            "ot_security": {
                "verified_zone_count": len(ot.security_zones) if all_ready else None,
                "verified_asset_inventory_coverage_pct": ot.asset_inventory_coverage_pct if all_ready else None,
                "verified_independent_safety_interlock": True if all_ready else None,
            },
            "gates": gates,
            "assurance": {
                "status": "passed" if all_ready else "blocked",
                "passed_gate_count": sum(item["passed"] for item in gates),
                "required_gate_count": len(gates),
                "calculation_ready": calculation_ready,
                "enterprise_security_verified": all_ready,
                "software_is_security_certification_authority": False,
                "claim": "signed enterprise and OT package reconciled" if all_ready else "claim withheld",
            },
            "production_boundary": {
                "assessment_only": True,
                "automatic_security_configuration_allowed": False,
                "enterprise_cutover_authorized": False,
                "ot_command_authority": False,
                "safety_interlock_bypass_allowed": False,
                "security_certification_claim_allowed": False,
                "production_authority": False,
                "human_release_required": True,
            },
            "input_evidence_sha256": input_evidence_sha256,
        }
        payload["evidence_sha256"] = canonical_sha256(payload)
        return EnterpriseSecurityReport(**payload)


enterprise_security_service = EnterpriseSecurityService()
