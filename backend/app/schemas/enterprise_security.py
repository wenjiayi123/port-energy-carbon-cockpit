from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


SHA256_PATTERN = r"^[0-9a-f]{64}$"
SOURCE_DOMAINS = {
    "identity_provider",
    "authorization_and_tenant_control",
    "message_and_timeseries_platform",
    "ha_orchestrator",
    "backup_dr_platform",
    "worm_siem_platform",
    "pki_key_management",
    "ot_security_monitor",
    "enterprise_governance",
}
SourceDomain = Literal[
    "identity_provider",
    "authorization_and_tenant_control",
    "message_and_timeseries_platform",
    "ha_orchestrator",
    "backup_dr_platform",
    "worm_siem_platform",
    "pki_key_management",
    "ot_security_monitor",
    "enterprise_governance",
]


def _timezone_required(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


class SecurityAssessmentWindow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    window_id: str = Field(min_length=3, max_length=160)
    start_at: datetime
    end_at: datetime

    @field_validator("start_at", "end_at")
    @classmethod
    def timestamps_have_timezone(cls, value: datetime) -> datetime:
        return _timezone_required(value, "security assessment window timestamp")

    @model_validator(mode="after")
    def ordered_window(self) -> "SecurityAssessmentWindow":
        if self.end_at <= self.start_at:
            raise ValueError("security assessment end_at must be after start_at")
        return self


class EnterpriseSecurityPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    policy_id: str = Field(min_length=3, max_length=160)
    organization_id: str = Field(min_length=2, max_length=160)
    site_id: str = Field(min_length=2, max_length=160)
    window: SecurityAssessmentWindow
    framework_versions: list[str] = Field(min_length=3)
    availability_slo_pct: float = Field(ge=99.0, le=100)
    maximum_rpo_minutes: float = Field(gt=0, le=1440)
    maximum_rto_minutes: float = Field(gt=0, le=10080)
    minimum_audit_retention_days: int = Field(ge=365, le=36500)
    maximum_key_age_days: int = Field(ge=1, le=365)
    maximum_source_age_seconds: int = Field(default=86_400, ge=1, le=604_800)
    maximum_source_alignment_seconds: int = Field(default=86_400, ge=0, le=604_800)
    minimum_tls_version: Literal["TLS1.2", "TLS1.3"] = "TLS1.2"
    security_architecture_sha256: str = Field(pattern=SHA256_PATTERN)
    tenant_policy_sha256: str = Field(pattern=SHA256_PATTERN)
    ot_risk_assessment_sha256: str = Field(pattern=SHA256_PATTERN)
    approved_by: str = Field(min_length=2, max_length=160)
    approval_record_sha256: str = Field(pattern=SHA256_PATTERN)

    @field_validator("framework_versions")
    @classmethod
    def unique_frameworks(cls, value: list[str]) -> list[str]:
        if any(not item.strip() for item in value) or len(value) != len(set(value)):
            raise ValueError("framework_versions must be unique and non-empty")
        return value


class FederatedIdentityEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    issuer: str = Field(min_length=8, max_length=512)
    audience: str = Field(min_length=2, max_length=256)
    discovery_document_sha256: str = Field(pattern=SHA256_PATTERN)
    active_signing_key_ids: list[str] = Field(min_length=2)
    sampled_successful_logins: int = Field(ge=1)
    rejected_invalid_token_tests: int = Field(ge=1)
    mfa_enforced: bool
    phishing_resistant_mfa_for_privileged_users: bool
    automated_deprovisioning: bool
    maximum_deprovisioning_minutes: float = Field(ge=0, le=1440)
    dormant_accounts_disabled: bool
    break_glass_accounts_monitored_and_tested: bool
    identity_test_report_sha256: str = Field(pattern=SHA256_PATTERN)

    @field_validator("active_signing_key_ids")
    @classmethod
    def unique_signing_keys(cls, value: list[str]) -> list[str]:
        if any(not item.strip() for item in value) or len(value) != len(set(value)):
            raise ValueError("active_signing_key_ids must be unique and non-empty")
        return value


class AuthorizationTenantEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    named_user_count: int = Field(ge=1)
    organization_ids: list[str] = Field(min_length=1)
    role_binding_count: int = Field(ge=1)
    least_privilege_review_completed: bool
    privileged_access_review_completed: bool
    segregation_of_duties_test_count: int = Field(ge=1)
    denied_unauthorized_test_count: int = Field(ge=1)
    cross_tenant_test_count: int = Field(ge=1)
    cross_tenant_rejected_count: int = Field(ge=0)
    row_level_security_enforced: bool
    tenant_partition_keys_enforced: bool
    tenant_encryption_key_ids: dict[str, str] = Field(min_length=1)
    authorization_policy_sha256: str = Field(pattern=SHA256_PATTERN)
    tenant_isolation_report_sha256: str = Field(pattern=SHA256_PATTERN)

    @field_validator("organization_ids")
    @classmethod
    def unique_organizations(cls, value: list[str]) -> list[str]:
        if any(not item.strip() for item in value) or len(value) != len(set(value)):
            raise ValueError("organization_ids must be unique and non-empty")
        return value


class MessagingTimeseriesEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    broker_cluster_nodes: int = Field(ge=1)
    broker_quorum_enabled: bool
    durable_messages_enabled: bool
    producer_idempotency_enabled: bool
    consumer_acknowledgements_enabled: bool
    schema_registry_enforced: bool
    dead_letter_queue_enabled: bool
    replay_drill_passed: bool
    published_message_count: int = Field(ge=1)
    acknowledged_message_count: int = Field(ge=0)
    duplicate_effect_count: int = Field(ge=0)
    timeseries_cluster_nodes: int = Field(ge=1)
    timeseries_replication_factor: int = Field(ge=1)
    timeseries_retention_days: int = Field(ge=1)
    timeseries_point_count: int = Field(ge=1)
    timeseries_backup_export_verified: bool
    tenant_partition_enforced: bool
    platform_test_report_sha256: str = Field(pattern=SHA256_PATTERN)


class HighAvailabilityEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    api_replica_count: int = Field(ge=1)
    worker_replica_count: int = Field(ge=1)
    availability_zone_count: int = Field(ge=1)
    database_replica_count: int = Field(ge=1)
    load_balancer_health_checks_enabled: bool
    automatic_failover_enabled: bool
    split_brain_prevention_enabled: bool
    failover_drill_passed: bool
    measured_failover_minutes: float = Field(ge=0)
    measured_availability_pct: float = Field(ge=0, le=100)
    capacity_after_single_failure_pct: float = Field(ge=0, le=200)
    failover_report_sha256: str = Field(pattern=SHA256_PATTERN)


class BackupDisasterRecoveryEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    backup_ids: list[str] = Field(min_length=2)
    encrypted_backups: bool
    immutable_backups: bool
    geographically_separate_copy: bool
    offline_recovery_copy: bool
    restore_drill_passed: bool
    restored_data_hash_matches: bool
    measured_rpo_minutes: float = Field(ge=0)
    measured_rto_minutes: float = Field(ge=0)
    backup_retention_days: int = Field(ge=1)
    recovery_runbook_sha256: str = Field(pattern=SHA256_PATTERN)
    restore_report_sha256: str = Field(pattern=SHA256_PATTERN)

    @field_validator("backup_ids")
    @classmethod
    def unique_backups(cls, value: list[str]) -> list[str]:
        if any(not item.strip() for item in value) or len(value) != len(set(value)):
            raise ValueError("backup_ids must be unique and non-empty")
        return value


class AuditSiemEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    external_worm_sink_enabled: bool
    retention_lock_enabled: bool
    retention_days: int = Field(ge=1)
    hash_chain_verified: bool
    generated_event_count: int = Field(ge=1)
    delivered_event_count: int = Field(ge=0)
    clock_synchronization_verified: bool
    sensitive_field_redaction_verified: bool
    siem_detection_rule_count: int = Field(ge=1)
    detection_drill_passed: bool
    tested_incident_ticket_id: str = Field(min_length=3, max_length=160)
    maximum_detection_minutes: float = Field(ge=0)
    audit_export_sha256: str = Field(pattern=SHA256_PATTERN)
    siem_test_report_sha256: str = Field(pattern=SHA256_PATTERN)


class PkiKeyManagementEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    minimum_tls_version: Literal["TLS1.2", "TLS1.3"]
    mtls_user_to_api: bool
    mtls_service_to_service: bool
    mtls_it_dmz_boundary: bool
    mtls_dmz_ot_boundary: bool
    certificate_inventory_count: int = Field(ge=1)
    expired_certificate_count: int = Field(ge=0)
    maximum_certificate_days_remaining: int = Field(ge=0)
    maximum_active_key_age_days: int = Field(ge=0)
    key_rotation_drill_passed: bool
    revocation_drill_passed: bool
    secrets_manager_enabled: bool
    root_keys_hardware_protected: bool
    repository_secret_scan_clean: bool
    pki_inventory_sha256: str = Field(pattern=SHA256_PATTERN)
    rotation_report_sha256: str = Field(pattern=SHA256_PATTERN)


class OTSecurityEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    security_zones: list[str] = Field(min_length=4)
    allowlisted_conduit_count: int = Field(ge=1)
    default_deny_between_zones: bool
    direct_internet_to_ot_blocked: bool
    read_only_it_ot_gateway: bool
    outbound_ot_egress_allowlisted: bool
    remote_access_jump_host_enforced: bool
    remote_access_mfa_enforced: bool
    remote_sessions_recorded: bool
    vendor_access_just_in_time: bool
    asset_inventory_coverage_pct: float = Field(ge=0, le=100)
    vulnerability_remediation_within_policy_pct: float = Field(ge=0, le=100)
    ot_incident_exercise_passed: bool
    independent_safety_interlock_tested: bool
    local_manual_control_retained: bool
    application_command_authority_disabled: bool
    ot_architecture_sha256: str = Field(pattern=SHA256_PATTERN)
    exercise_report_sha256: str = Field(pattern=SHA256_PATTERN)

    @field_validator("security_zones")
    @classmethod
    def unique_zones(cls, value: list[str]) -> list[str]:
        if any(not item.strip() for item in value) or len(value) != len(set(value)):
            raise ValueError("security_zones must be unique and non-empty")
        return value


class EnterpriseSecurityApproval(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approval_id: str = Field(min_length=3, max_length=160)
    role: Literal["enterprise_owner", "chief_information_security_officer", "ot_security_owner"]
    approver_id: str = Field(min_length=2, max_length=160)
    decision: Literal["approved", "rejected"]
    approved_at: datetime
    security_architecture_sha256: str = Field(pattern=SHA256_PATTERN)
    approval_record_sha256: str = Field(pattern=SHA256_PATTERN)

    @field_validator("approved_at")
    @classmethod
    def approval_has_timezone(cls, value: datetime) -> datetime:
        return _timezone_required(value, "enterprise security approval timestamp")


class EnterpriseSecuritySourceAttestation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    domain: SourceDomain
    source_system: str = Field(min_length=2, max_length=160)
    source_record_ids: list[str] = Field(min_length=1)
    observed_at: datetime
    live_data_verified: bool
    key_id: str = Field(min_length=3, max_length=160)
    signed_payload_sha256: str = Field(pattern=SHA256_PATTERN)
    signature: str = Field(min_length=40, max_length=256, pattern=r"^[A-Za-z0-9+/]+={0,2}$")

    @field_validator("observed_at")
    @classmethod
    def observed_at_has_timezone(cls, value: datetime) -> datetime:
        return _timezone_required(value, "enterprise security source observed_at")

    @field_validator("source_record_ids")
    @classmethod
    def unique_source_records(cls, value: list[str]) -> list[str]:
        if any(not item.strip() for item in value) or len(value) != len(set(value)):
            raise ValueError("source_record_ids must be unique and non-empty")
        return value


class EnterpriseSecurityRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["enterprise-security-input.v1"] = "enterprise-security-input.v1"
    case_id: str = Field(min_length=3, max_length=160)
    evaluated_at: datetime
    policy: EnterpriseSecurityPolicy
    identity: FederatedIdentityEvidence
    authorization_and_tenant: AuthorizationTenantEvidence
    messaging_and_timeseries: MessagingTimeseriesEvidence
    high_availability: HighAvailabilityEvidence
    backup_and_dr: BackupDisasterRecoveryEvidence
    audit_and_siem: AuditSiemEvidence
    pki_and_keys: PkiKeyManagementEvidence
    ot_security: OTSecurityEvidence
    approvals: list[EnterpriseSecurityApproval] = Field(min_length=3)
    source_attestations: list[EnterpriseSecuritySourceAttestation] = Field(min_length=1)

    @field_validator("evaluated_at")
    @classmethod
    def evaluated_at_has_timezone(cls, value: datetime) -> datetime:
        return _timezone_required(value, "enterprise security evaluated_at")


class EnterpriseSecurityReport(BaseModel):
    schema_version: str
    report_id: str
    mode: str
    status: str
    source_readiness: dict[str, Any]
    current_repository_controls: dict[str, Any]
    identity_and_access: dict[str, Any]
    tenant_isolation: dict[str, Any]
    messaging_and_timeseries: dict[str, Any]
    availability_and_recovery: dict[str, Any]
    audit_and_monitoring: dict[str, Any]
    pki_and_key_management: dict[str, Any]
    ot_security: dict[str, Any]
    gates: list[dict[str, Any]]
    assurance: dict[str, Any]
    production_boundary: dict[str, bool]
    input_evidence_sha256: str | None = None
    evidence_sha256: str
