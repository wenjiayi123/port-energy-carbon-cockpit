from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


SHA256_PATTERN = r"^[0-9a-f]{64}$"
MODULE_DOMAINS = {
    "live_port_data",
    "measurement_and_calibration",
    "production_execution",
    "long_horizon_shadow",
    "port_emissions_inventory",
    "energy_carbon_management",
    "operations_energy_coupling",
    "electrical_network",
    "algorithm_production",
    "carbon_asset_compliance",
    "commercial_settlement",
    "port_collaboration",
    "enterprise_ot_security",
}
ModuleDomain = Literal[
    "live_port_data",
    "measurement_and_calibration",
    "production_execution",
    "long_horizon_shadow",
    "port_emissions_inventory",
    "energy_carbon_management",
    "operations_energy_coupling",
    "electrical_network",
    "algorithm_production",
    "carbon_asset_compliance",
    "commercial_settlement",
    "port_collaboration",
    "enterprise_ot_security",
]
APPROVAL_ROLES = {
    "port_owner",
    "operations_owner",
    "energy_carbon_owner",
    "ot_safety_owner",
    "chief_information_security_officer",
    "independent_verifier",
}
ApprovalRole = Literal[
    "port_owner",
    "operations_owner",
    "energy_carbon_owner",
    "ot_safety_owner",
    "chief_information_security_officer",
    "independent_verifier",
]
REQUIRED_SHADOW_SCENARIOS = {
    "peak_operations",
    "off_peak_operations",
    "extreme_weather",
    "equipment_failure",
    "grid_derating",
    "planned_maintenance",
}


def _timezone_required(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


class SiteCutoverWindow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    window_id: str = Field(min_length=3, max_length=160)
    start_at: datetime
    end_at: datetime

    @field_validator("start_at", "end_at")
    @classmethod
    def timestamps_have_timezone(cls, value: datetime) -> datetime:
        return _timezone_required(value, "site cutover assessment window timestamp")

    @model_validator(mode="after")
    def ordered_window(self) -> "SiteCutoverWindow":
        if self.end_at <= self.start_at:
            raise ValueError("site cutover end_at must be after start_at")
        return self


class SiteCutoverPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    policy_id: str = Field(min_length=3, max_length=160)
    site_id: str = Field(min_length=2, max_length=160)
    tenant_id: str = Field(min_length=2, max_length=160)
    target_release: str = Field(min_length=2, max_length=160)
    window: SiteCutoverWindow
    configuration_sha256: str = Field(pattern=SHA256_PATTERN)
    infrastructure_as_code_sha256: str = Field(pattern=SHA256_PATTERN)
    minimum_shadow_days: int = Field(default=180, ge=90, le=730)
    minimum_operating_season_count: int = Field(default=2, ge=2, le=12)
    maximum_module_age_days: int = Field(default=30, ge=1, le=180)
    maximum_data_cutoff_alignment_hours: int = Field(default=24, ge=0, le=168)
    maximum_energy_balance_error_pct: float = Field(default=1.0, ge=0, le=5)
    maximum_bill_reconciliation_error_pct: float = Field(default=0.5, ge=0, le=5)
    maximum_rollback_minutes: float = Field(default=30, gt=0, le=1440)
    maximum_rpo_minutes: float = Field(default=15, gt=0, le=1440)
    maximum_rto_minutes: float = Field(default=60, gt=0, le=10080)


class CutoverModuleEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    domain: ModuleDomain
    schema_version: str = Field(min_length=3, max_length=160)
    report_id: str = Field(min_length=3, max_length=200)
    report_status: str = Field(min_length=2, max_length=160)
    evidence_sha256: str = Field(pattern=SHA256_PATTERN)
    site_id: str = Field(min_length=2, max_length=160)
    tenant_id: str = Field(min_length=2, max_length=160)
    assessment_window_id: str = Field(min_length=3, max_length=160)
    data_cutoff_at: datetime
    observed_at: datetime
    source_mode: Literal["live_site", "production_shadow"]
    owner_system: str = Field(min_length=2, max_length=160)
    source_record_ids: list[str] = Field(min_length=1)
    independently_verified: bool
    acceptance_conclusion: Literal["accepted", "rejected"]
    exception_ids: list[str] = Field(default_factory=list)
    key_id: str = Field(min_length=3, max_length=160)
    signed_payload_sha256: str = Field(pattern=SHA256_PATTERN)
    signature: str = Field(min_length=40, max_length=256, pattern=r"^[A-Za-z0-9+/]+={0,2}$")

    @field_validator("data_cutoff_at", "observed_at")
    @classmethod
    def timestamps_have_timezone(cls, value: datetime) -> datetime:
        return _timezone_required(value, "cutover module evidence timestamp")

    @field_validator("source_record_ids", "exception_ids")
    @classmethod
    def unique_string_lists(cls, value: list[str]) -> list[str]:
        if any(not item.strip() for item in value) or len(value) != len(set(value)):
            raise ValueError("evidence string lists must be unique and non-empty")
        return value


class SiteOperationalAcceptanceEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ready_live_adapter_count: int = Field(ge=0)
    required_live_adapter_count: int = Field(ge=1)
    accepted_live_snapshot_count: int = Field(ge=0)
    composite_shadow_release_count: int = Field(ge=0)
    meter_coverage_pct: float = Field(ge=0, le=100)
    calibrated_meter_coverage_pct: float = Field(ge=0, le=100)
    energy_balance_error_pct: float = Field(ge=0, le=100)
    bill_reconciliation_error_pct: float = Field(ge=0, le=100)
    shadow_run_days: int = Field(ge=0)
    operating_seasons: list[str]
    covered_shadow_scenarios: list[str]
    production_instruction_gateway_external: bool
    device_capability_checks_passed: bool
    independent_plc_interlocks_tested: bool
    device_receipt_rate_pct: float = Field(ge=0, le=100)
    command_timeout_fallback_tested: bool
    human_takeover_drill_passed: bool
    rollback_drill_passed: bool
    measured_rollback_minutes: float = Field(ge=0)
    backup_restore_drill_passed: bool
    measured_rpo_minutes: float = Field(ge=0)
    measured_rto_minutes: float = Field(ge=0)
    cyber_incident_exercise_passed: bool
    unresolved_severity_1_count: int = Field(ge=0)
    unresolved_severity_2_count: int = Field(ge=0)
    operator_training_coverage_pct: float = Field(ge=0, le=100)
    approved_sop_sha256: str = Field(pattern=SHA256_PATTERN)
    approved_runbook_sha256: str = Field(pattern=SHA256_PATTERN)
    safety_case_sha256: str = Field(pattern=SHA256_PATTERN)
    independent_mv_accepted: bool
    benefit_attribution_report_sha256: str = Field(pattern=SHA256_PATTERN)
    change_ticket_id: str = Field(min_length=3, max_length=160)
    change_window_start_at: datetime
    change_window_end_at: datetime
    production_authority_disabled_in_application: bool

    @field_validator("change_window_start_at", "change_window_end_at")
    @classmethod
    def timestamps_have_timezone(cls, value: datetime) -> datetime:
        return _timezone_required(value, "change window timestamp")

    @field_validator("operating_seasons", "covered_shadow_scenarios")
    @classmethod
    def unique_non_empty_lists(cls, value: list[str]) -> list[str]:
        if any(not item.strip() for item in value) or len(value) != len(set(value)):
            raise ValueError("operational evidence lists must be unique and non-empty")
        return value

    @model_validator(mode="after")
    def ordered_change_window(self) -> "SiteOperationalAcceptanceEvidence":
        if self.change_window_end_at <= self.change_window_start_at:
            raise ValueError("change window end must be after start")
        return self


class SiteCutoverApproval(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approval_id: str = Field(min_length=3, max_length=160)
    role: ApprovalRole
    approver_id: str = Field(min_length=2, max_length=160)
    decision: Literal["approved", "rejected"]
    approved_at: datetime
    acceptance_package_sha256: str = Field(pattern=SHA256_PATTERN)
    approval_record_sha256: str = Field(pattern=SHA256_PATTERN)
    key_id: str = Field(min_length=3, max_length=160)
    signature: str = Field(min_length=40, max_length=256, pattern=r"^[A-Za-z0-9+/]+={0,2}$")

    @field_validator("approved_at")
    @classmethod
    def approval_has_timezone(cls, value: datetime) -> datetime:
        return _timezone_required(value, "site cutover approval timestamp")


class SiteCutoverRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["site-cutover-input.v1"] = "site-cutover-input.v1"
    case_id: str = Field(min_length=3, max_length=160)
    evaluated_at: datetime
    policy: SiteCutoverPolicy
    module_evidence: list[CutoverModuleEvidence] = Field(min_length=1)
    operational_evidence: SiteOperationalAcceptanceEvidence
    approvals: list[SiteCutoverApproval] = Field(min_length=1)

    @field_validator("evaluated_at")
    @classmethod
    def evaluated_at_has_timezone(cls, value: datetime) -> datetime:
        return _timezone_required(value, "site cutover evaluated_at")


class SiteCutoverReport(BaseModel):
    schema_version: str
    report_id: str
    mode: str
    status: str
    source_readiness: dict[str, Any]
    domain_evidence: list[dict[str, Any]]
    site_consistency: dict[str, Any]
    operational_acceptance: dict[str, Any]
    approval_summary: dict[str, Any]
    gates: list[dict[str, Any]]
    assurance: dict[str, Any]
    production_boundary: dict[str, bool]
    approval_subject_sha256: str | None = None
    input_evidence_sha256: str | None = None
    evidence_sha256: str
