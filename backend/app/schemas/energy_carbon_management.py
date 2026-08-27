from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


SHA256_PATTERN = r"^[0-9a-f]{64}$"
REQUIRED_ROLES = {
    "top_management",
    "energy_manager",
    "ghg_inventory_owner",
    "operations_owner",
    "internal_auditor",
}


class ManagementPeriod(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start_at: datetime
    end_at: datetime

    @field_validator("start_at", "end_at")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("management period timestamps must be timezone-aware")
        return value

    @model_validator(mode="after")
    def ordered_period(self) -> "ManagementPeriod":
        if self.end_at <= self.start_at:
            raise ValueError("management period end_at must be after start_at")
        return self


class ManagementContextEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    system_id: str = Field(min_length=3, max_length=160)
    reporting_entity: str = Field(min_length=2, max_length=256)
    site_ids: list[str] = Field(min_length=1)
    organizational_boundary: str = Field(min_length=3, max_length=1024)
    operational_boundary: str = Field(min_length=3, max_length=1024)
    standard_references: list[str] = Field(min_length=2)
    applicable_requirements_register_id: str = Field(min_length=3, max_length=160)
    applicable_requirements_sha256: str = Field(pattern=SHA256_PATTERN)
    context_review_sha256: str = Field(pattern=SHA256_PATTERN)
    climate_change_relevance_reviewed: bool
    approved_by: str = Field(min_length=2, max_length=128)

    @field_validator("site_ids", "standard_references")
    @classmethod
    def unique_non_empty_values(cls, value: list[str]) -> list[str]:
        if any(not item.strip() for item in value) or len(set(value)) != len(value):
            raise ValueError("list values must be unique and non-empty")
        return value


class EnergyCarbonPolicyEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    policy_id: str = Field(min_length=3, max_length=160)
    policy_sha256: str = Field(pattern=SHA256_PATTERN)
    top_management_id: str = Field(min_length=2, max_length=128)
    approved_at: datetime
    effective_at: datetime
    communicated_at: datetime
    continual_improvement_commitment: bool
    information_and_resources_commitment: bool

    @field_validator("approved_at", "effective_at", "communicated_at")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("policy timestamps must be timezone-aware")
        return value


class RoleAssignmentEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal[
        "top_management",
        "energy_manager",
        "ghg_inventory_owner",
        "operations_owner",
        "internal_auditor",
    ]
    person_id: str = Field(min_length=2, max_length=128)
    authority_scope: str = Field(min_length=3, max_length=512)
    assigned_at: datetime
    appointment_sha256: str = Field(pattern=SHA256_PATTERN)

    @field_validator("assigned_at")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("assigned_at must be timezone-aware")
        return value


class SignificantEnergyUseEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    seu_id: str = Field(min_length=3, max_length=160)
    label: str = Field(min_length=2, max_length=256)
    asset_ids: list[str] = Field(min_length=1)
    energy_use_kwh: float = Field(gt=0)
    relevant_variables: list[str] = Field(min_length=1)
    meter_ids: list[str] = Field(min_length=1)
    operational_control_ids: list[str] = Field(min_length=1)


class EnergyReviewEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    review_id: str = Field(min_length=3, max_length=160)
    reviewed_at: datetime
    total_energy_use_kwh: float = Field(gt=0)
    minimum_seu_coverage_pct: float = Field(gt=0, le=100)
    significant_energy_uses: list[SignificantEnergyUseEvidence] = Field(min_length=1)
    improvement_opportunities: list[str] = Field(min_length=1)
    approved_by: str = Field(min_length=2, max_length=128)
    review_sha256: str = Field(pattern=SHA256_PATTERN)

    @field_validator("reviewed_at")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("reviewed_at must be timezone-aware")
        return value


class EnergyBaselineEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    baseline_id: str = Field(min_length=3, max_length=160)
    period: ManagementPeriod
    baseline_energy_kwh: float = Field(gt=0)
    normalization_method: str = Field(min_length=3, max_length=512)
    relevant_variables: list[str] = Field(min_length=1)
    adjustment_triggers: list[str] = Field(min_length=1)
    frozen_at: datetime
    approved_by: str = Field(min_length=2, max_length=128)
    model_sha256: str = Field(pattern=SHA256_PATTERN)

    @field_validator("frozen_at")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("frozen_at must be timezone-aware")
        return value


class EnergyPerformanceIndicatorEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enpi_id: str = Field(min_length=3, max_length=160)
    label: str = Field(min_length=2, max_length=256)
    unit: str = Field(min_length=1, max_length=64)
    direction: Literal["decrease", "increase"]
    baseline_value: float = Field(ge=0)
    target_value: float = Field(ge=0)
    current_value: float = Field(ge=0)
    measured_at: datetime
    owner_id: str = Field(min_length=2, max_length=128)
    source_sha256: str = Field(pattern=SHA256_PATTERN)

    @field_validator("measured_at")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("measured_at must be timezone-aware")
        return value


class EnergyObjectiveEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    objective_id: str = Field(min_length=3, max_length=160)
    enpi_id: str = Field(min_length=3, max_length=160)
    target_value: float = Field(ge=0)
    due_at: datetime
    owner_id: str = Field(min_length=2, max_length=128)
    approved_by: str = Field(min_length=2, max_length=128)
    approval_sha256: str = Field(pattern=SHA256_PATTERN)

    @field_validator("due_at")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("due_at must be timezone-aware")
        return value


class ActionPlanEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action_id: str = Field(min_length=3, max_length=160)
    objective_id: str = Field(min_length=3, max_length=160)
    owner_id: str = Field(min_length=2, max_length=128)
    resources: list[str] = Field(min_length=1)
    budget_cny: float = Field(ge=0)
    start_at: datetime
    due_at: datetime
    status: Literal["planned", "in_progress", "completed", "cancelled"]
    completion_evidence_sha256: str | None = Field(default=None, pattern=SHA256_PATTERN)

    @field_validator("start_at", "due_at")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("action plan timestamps must be timezone-aware")
        return value

    @model_validator(mode="after")
    def ordered_period(self) -> "ActionPlanEvidence":
        if self.due_at < self.start_at:
            raise ValueError("action due_at must not precede start_at")
        if self.status == "completed" and not self.completion_evidence_sha256:
            raise ValueError("completed action requires completion evidence")
        return self


class MonitoringMeasurementEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan_id: str = Field(min_length=3, max_length=160)
    measurement_frequency: str = Field(min_length=2, max_length=128)
    meter_ids: list[str] = Field(min_length=1)
    expected_record_count: int = Field(ge=1)
    received_record_count: int = Field(ge=0)
    minimum_coverage_pct: float = Field(gt=0, le=100)
    retention_days: int = Field(ge=1)
    calibration_register_sha256: str = Field(pattern=SHA256_PATTERN)
    correction_procedure_sha256: str = Field(pattern=SHA256_PATTERN)
    measurement_verification_evidence_sha256: str = Field(pattern=SHA256_PATTERN)
    approved_by: str = Field(min_length=2, max_length=128)


class OperationalControlEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    control_id: str = Field(min_length=3, max_length=160)
    seu_id: str = Field(min_length=3, max_length=160)
    operational_criteria: str = Field(min_length=3, max_length=1024)
    owner_id: str = Field(min_length=2, max_length=128)
    abnormal_response: str = Field(min_length=3, max_length=1024)
    control_record_sha256: str = Field(pattern=SHA256_PATTERN)


class CompetenceAwarenessEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    person_id: str = Field(min_length=2, max_length=128)
    role: Literal[
        "top_management",
        "energy_manager",
        "ghg_inventory_owner",
        "operations_owner",
        "internal_auditor",
    ]
    competence_assessed: bool
    awareness_acknowledged: bool
    completed_at: datetime
    valid_through: datetime
    evidence_sha256: str = Field(pattern=SHA256_PATTERN)

    @field_validator("completed_at", "valid_through")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("competence timestamps must be timezone-aware")
        return value


class GhgInventoryGovernanceEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    inventory_report_id: str = Field(min_length=3, max_length=160)
    inventory_period: ManagementPeriod
    organizational_boundary_approach: str = Field(min_length=3, max_length=512)
    reporting_boundary: str = Field(min_length=3, max_length=1024)
    base_year: int = Field(ge=1990, le=2200)
    expected_source_category_count: int = Field(ge=1)
    reported_source_category_count: int = Field(ge=0)
    factor_registry_id: str = Field(min_length=3, max_length=160)
    factor_registry_version: str = Field(min_length=1, max_length=64)
    factor_registry_sha256: str = Field(pattern=SHA256_PATTERN)
    inventory_evidence_sha256: str = Field(pattern=SHA256_PATTERN)
    measurement_verification_evidence_sha256: str = Field(pattern=SHA256_PATTERN)
    uncertainty_quantified: bool
    recalculation_triggers: list[str] = Field(min_length=1)
    revision_id: str = Field(min_length=1, max_length=128)
    approved_by: str = Field(min_length=2, max_length=128)


class InternalAuditEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    audit_id: str = Field(min_length=3, max_length=160)
    auditor_id: str = Field(min_length=2, max_length=128)
    independence_attested: bool
    completed_at: datetime
    scope_references: list[str] = Field(min_length=2)
    conclusion: Literal["conforming", "minor_nonconformity", "major_nonconformity"]
    finding_ids: list[str] = Field(default_factory=list)
    report_sha256: str = Field(pattern=SHA256_PATTERN)

    @field_validator("completed_at")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("completed_at must be timezone-aware")
        return value


class CorrectiveActionEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action_id: str = Field(min_length=3, max_length=160)
    finding_id: str = Field(min_length=2, max_length=160)
    root_cause: str = Field(min_length=3, max_length=1024)
    owner_id: str = Field(min_length=2, max_length=128)
    due_at: datetime
    status: Literal["open", "in_progress", "closed"]
    closed_at: datetime | None = None
    effectiveness_verified: bool
    evidence_sha256: str = Field(pattern=SHA256_PATTERN)

    @field_validator("due_at", "closed_at")
    @classmethod
    def timezone_required(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("corrective action timestamps must be timezone-aware")
        return value


class ManagementReviewEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    review_id: str = Field(min_length=3, max_length=160)
    reviewed_at: datetime
    chair_id: str = Field(min_length=2, max_length=128)
    input_topics: list[str] = Field(min_length=1)
    decisions: list[str] = Field(min_length=1)
    resources_approved: list[str] = Field(min_length=1)
    review_sha256: str = Field(pattern=SHA256_PATTERN)

    @field_validator("reviewed_at")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("reviewed_at must be timezone-aware")
        return value


class IndependentManagementAssuranceEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reviewer_id: str = Field(min_length=2, max_length=128)
    organization: str = Field(min_length=2, max_length=256)
    independence_attested: bool
    reviewed_at: datetime
    conclusion: Literal["accepted", "qualified", "rejected"]
    key_id: str = Field(min_length=3, max_length=128)
    signed_evidence_sha256: str = Field(pattern=SHA256_PATTERN)
    signature: str = Field(min_length=40, max_length=256, pattern=r"^[A-Za-z0-9+/]+={0,2}$")

    @field_validator("reviewed_at")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("reviewed_at must be timezone-aware")
        return value


class EnergyCarbonManagementRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["energy-carbon-management-system-input.v1"] = (
        "energy-carbon-management-system-input.v1"
    )
    cycle_id: str = Field(min_length=3, max_length=160)
    cycle_period: ManagementPeriod
    context: ManagementContextEvidence
    policy: EnergyCarbonPolicyEvidence
    roles: list[RoleAssignmentEvidence] = Field(min_length=5)
    energy_review: EnergyReviewEvidence
    energy_baseline: EnergyBaselineEvidence
    enpis: list[EnergyPerformanceIndicatorEvidence] = Field(min_length=1)
    objectives: list[EnergyObjectiveEvidence] = Field(min_length=1)
    action_plans: list[ActionPlanEvidence] = Field(min_length=1)
    monitoring: MonitoringMeasurementEvidence
    operational_controls: list[OperationalControlEvidence] = Field(min_length=1)
    competence_records: list[CompetenceAwarenessEvidence] = Field(min_length=5)
    ghg_inventory: GhgInventoryGovernanceEvidence
    internal_audit: InternalAuditEvidence
    corrective_actions: list[CorrectiveActionEvidence] = Field(default_factory=list)
    no_finding_declaration_sha256: str | None = Field(default=None, pattern=SHA256_PATTERN)
    management_review: ManagementReviewEvidence
    independent_assurance: IndependentManagementAssuranceEvidence | None = None


class EnergyCarbonManagementReport(BaseModel):
    schema_version: str
    report_id: str
    mode: str
    status: str
    standards: dict[str, Any]
    organization: dict[str, Any]
    pdca: dict[str, Any]
    performance: dict[str, Any]
    audit: dict[str, Any]
    gates: list[dict[str, Any]]
    assurance: dict[str, Any]
    production_boundary: dict[str, bool]
    input_evidence_sha256: str | None = None
    evidence_sha256: str
