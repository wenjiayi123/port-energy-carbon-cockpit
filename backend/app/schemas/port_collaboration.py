from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


SHA256_PATTERN = r"^[0-9a-f]{64}$"
SOURCE_DOMAINS = {
    "vessel_operator_plan",
    "port_call_platform",
    "terminal_berth_operations",
    "shore_power_operator",
    "alternative_fuel_facility",
    "port_tariff_authority",
    "corridor_governance_ledger",
}
SourceDomain = Literal[
    "vessel_operator_plan",
    "port_call_platform",
    "terminal_berth_operations",
    "shore_power_operator",
    "alternative_fuel_facility",
    "port_tariff_authority",
    "corridor_governance_ledger",
]


def _timezone_required(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


class CollaborationWindow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    window_id: str = Field(min_length=3, max_length=160)
    start_at: datetime
    end_at: datetime

    @field_validator("start_at", "end_at")
    @classmethod
    def timestamps_have_timezone(cls, value: datetime) -> datetime:
        return _timezone_required(value, "collaboration window timestamp")

    @model_validator(mode="after")
    def ordered_window(self) -> "CollaborationWindow":
        if self.end_at <= self.start_at:
            raise ValueError("collaboration window end_at must be after start_at")
        return self


class PortCollaborationPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    policy_id: str = Field(min_length=3, max_length=160)
    corridor_id: str = Field(min_length=3, max_length=160)
    port_id: str = Field(min_length=2, max_length=160)
    currency: str = Field(min_length=3, max_length=3)
    window: CollaborationWindow
    maximum_arrival_deviation_minutes: float = Field(default=15.0, ge=0, le=1440)
    minimum_advice_lead_hours: float = Field(default=6.0, ge=0, le=720)
    maximum_amount_variance_pct: float = Field(default=0.5, ge=0, le=100)
    maximum_source_age_seconds: int = Field(default=86_400, ge=1, le=604_800)
    maximum_source_alignment_seconds: int = Field(default=86_400, ge=0, le=604_800)
    marine_fuel_emission_factor_kg_per_tonne: float = Field(gt=0)
    jit_priority_points: float = Field(default=30.0, ge=0)
    shore_power_priority_points: float = Field(default=40.0, ge=0)
    alternative_fuel_priority_points: float = Field(default=30.0, ge=0)
    jit_fee_discount_pct: float = Field(default=2.0, ge=0, le=100)
    shore_power_fee_discount_pct: float = Field(default=3.0, ge=0, le=100)
    alternative_fuel_fee_discount_pct: float = Field(default=2.0, ge=0, le=100)
    maximum_total_fee_discount_pct: float = Field(default=7.0, ge=0, le=100)
    port_benefit_share_pct: float = Field(ge=0, le=100)
    vessel_operator_benefit_share_pct: float = Field(ge=0, le=100)
    eligible_alternative_fuels: list[str] = Field(min_length=1)
    charter_sha256: str = Field(pattern=SHA256_PATTERN)
    allocation_rule_sha256: str = Field(pattern=SHA256_PATTERN)
    approved_by: str = Field(min_length=2, max_length=160)
    approval_record_sha256: str = Field(pattern=SHA256_PATTERN)

    @field_validator("currency")
    @classmethod
    def uppercase_currency(cls, value: str) -> str:
        if value != value.upper():
            raise ValueError("currency must be uppercase")
        return value

    @field_validator("eligible_alternative_fuels")
    @classmethod
    def unique_fuels(cls, value: list[str]) -> list[str]:
        if any(not item.strip() for item in value) or len(value) != len(set(value)):
            raise ValueError("eligible_alternative_fuels must be unique and non-empty")
        return value

    @model_validator(mode="after")
    def coherent_shares_and_discounts(self) -> "PortCollaborationPolicy":
        if abs(
            self.port_benefit_share_pct + self.vessel_operator_benefit_share_pct - 100.0
        ) > 1e-9:
            raise ValueError("port and vessel-operator benefit shares must sum to 100 percent")
        if self.maximum_total_fee_discount_pct > (
            self.jit_fee_discount_pct
            + self.shore_power_fee_discount_pct
            + self.alternative_fuel_fee_discount_pct
        ):
            raise ValueError("maximum fee discount cannot exceed all component discounts")
        return self


class VesselOperatorCallEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    vessel_call_id: str = Field(min_length=3, max_length=160)
    imo_number: str = Field(pattern=r"^IMO[0-9]{7}$")
    vessel_name: str = Field(min_length=2, max_length=160)
    vessel_operator_id: str = Field(min_length=2, max_length=160)
    origin_port_id: str = Field(min_length=2, max_length=160)
    destination_port_id: str = Field(min_length=2, max_length=160)
    original_eta: datetime
    advice_issued_at: datetime
    agreed_arrival_at: datetime
    actual_arrival_at: datetime
    distance_to_go_nm: float = Field(gt=0)
    baseline_speed_knots: float = Field(gt=0)
    advised_speed_knots: float = Field(gt=0)
    baseline_fuel_tonnes: float = Field(ge=0)
    actual_fuel_tonnes: float = Field(ge=0)
    operator_accepted: bool
    acceptance_record_sha256: str = Field(pattern=SHA256_PATTERN)
    fuel_evidence_sha256: str = Field(pattern=SHA256_PATTERN)

    @field_validator("original_eta", "advice_issued_at", "agreed_arrival_at", "actual_arrival_at")
    @classmethod
    def timestamps_have_timezone(cls, value: datetime) -> datetime:
        return _timezone_required(value, "vessel call timestamp")


class PortCallMilestoneEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    vessel_call_id: str = Field(min_length=3, max_length=160)
    berth_id: str = Field(min_length=2, max_length=160)
    terminal_ready_at: datetime
    berth_window_start_at: datetime
    berth_window_end_at: datetime
    all_fast_at: datetime
    cargo_operations_start_at: datetime
    cargo_operations_end_at: datetime
    departure_at: datetime
    milestone_record_sha256: str = Field(pattern=SHA256_PATTERN)

    @field_validator(
        "terminal_ready_at",
        "berth_window_start_at",
        "berth_window_end_at",
        "all_fast_at",
        "cargo_operations_start_at",
        "cargo_operations_end_at",
        "departure_at",
    )
    @classmethod
    def timestamps_have_timezone(cls, value: datetime) -> datetime:
        return _timezone_required(value, "port-call milestone timestamp")


class GreenBerthAssignmentEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    vessel_call_id: str = Field(min_length=3, max_length=160)
    berth_id: str = Field(min_length=2, max_length=160)
    assigned_at: datetime
    jit_eligible: bool
    shore_power_eligible: bool
    alternative_fuel_eligible: bool
    declared_priority_score: float = Field(ge=0)
    assigned_priority_rank: int = Field(ge=1)
    fairness_cohort_id: str = Field(min_length=2, max_length=160)
    allocation_rule_sha256: str = Field(pattern=SHA256_PATTERN)
    approved: bool
    assignment_record_sha256: str = Field(pattern=SHA256_PATTERN)

    @field_validator("assigned_at")
    @classmethod
    def assigned_at_has_timezone(cls, value: datetime) -> datetime:
        return _timezone_required(value, "berth assignment timestamp")


class ShorePowerReservationEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reservation_id: str = Field(min_length=3, max_length=160)
    vessel_call_id: str = Field(min_length=3, max_length=160)
    berth_id: str = Field(min_length=2, max_length=160)
    service_start_at: datetime
    service_end_at: datetime
    vessel_compatible: bool
    berth_compatible: bool
    reserved_capacity_kw: float = Field(gt=0)
    berth_capacity_kw: float = Field(gt=0)
    metered_energy_kwh: float = Field(ge=0)
    energy_rate_per_kwh: float = Field(ge=0)
    connection_fee: float = Field(ge=0)
    stated_invoice_amount: float = Field(ge=0)
    currency: str = Field(min_length=3, max_length=3)
    status: Literal["settled", "paid", "reserved", "cancelled", "failed"]
    meter_record_sha256: str = Field(pattern=SHA256_PATTERN)
    invoice_sha256: str = Field(pattern=SHA256_PATTERN)
    settlement_receipt_sha256: str | None = Field(default=None, pattern=SHA256_PATTERN)

    @field_validator("service_start_at", "service_end_at")
    @classmethod
    def timestamps_have_timezone(cls, value: datetime) -> datetime:
        return _timezone_required(value, "shore-power service timestamp")

    @model_validator(mode="after")
    def ordered_service(self) -> "ShorePowerReservationEvidence":
        if self.service_end_at <= self.service_start_at:
            raise ValueError("shore-power service_end_at must be after service_start_at")
        return self


class AlternativeFuelReadinessEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    service_id: str = Field(min_length=3, max_length=160)
    vessel_call_id: str = Field(min_length=3, max_length=160)
    fuel_type: str = Field(min_length=2, max_length=80)
    requested_quantity_tonnes: float = Field(gt=0)
    available_inventory_tonnes: float = Field(ge=0)
    maximum_transfer_rate_tonnes_per_hour: float = Field(gt=0)
    service_hours: float = Field(gt=0)
    permit_valid_through: datetime
    compatible_transfer_equipment: bool
    trained_staff_available: bool
    safety_case_approved: bool
    emergency_drill_passed: bool
    risk_assessment_accepted: bool
    status: Literal["ready", "served", "pending", "rejected"]
    permit_sha256: str = Field(pattern=SHA256_PATTERN)
    safety_case_sha256: str = Field(pattern=SHA256_PATTERN)
    service_receipt_sha256: str | None = Field(default=None, pattern=SHA256_PATTERN)

    @field_validator("permit_valid_through")
    @classmethod
    def permit_has_timezone(cls, value: datetime) -> datetime:
        return _timezone_required(value, "permit_valid_through")


class PortFeeIncentiveEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    invoice_id: str = Field(min_length=3, max_length=160)
    vessel_call_id: str = Field(min_length=3, max_length=160)
    base_port_fee: float = Field(ge=0)
    declared_discount_pct: float = Field(ge=0, le=100)
    stated_payable_amount: float = Field(ge=0)
    currency: str = Field(min_length=3, max_length=3)
    status: Literal["paid", "issued", "approved", "disputed", "void"]
    incentive_rule_sha256: str = Field(pattern=SHA256_PATTERN)
    invoice_sha256: str = Field(pattern=SHA256_PATTERN)
    payment_receipt_sha256: str | None = Field(default=None, pattern=SHA256_PATTERN)


class EmissionBenefitClaimEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim_id: str = Field(min_length=3, max_length=160)
    vessel_call_id: str = Field(min_length=3, max_length=160)
    category: Literal["jit_arrival", "shore_power", "alternative_fuel"]
    verified_reduction_tco2e: float = Field(gt=0)
    verification_status: Literal["independently_verified", "calculated_only", "rejected"]
    evidence_sha256: str = Field(pattern=SHA256_PATTERN)


class BenefitSharingEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    allocation_id: str = Field(min_length=3, max_length=160)
    vessel_call_id: str = Field(min_length=3, max_length=160)
    verified_reduction_tco2e: float = Field(gt=0)
    value_per_tco2e: float = Field(ge=0)
    total_benefit_value: float = Field(ge=0)
    port_benefit_amount: float = Field(ge=0)
    vessel_operator_benefit_amount: float = Field(ge=0)
    currency: str = Field(min_length=3, max_length=3)
    status: Literal["settled", "accepted", "pending", "rejected"]
    port_approval_sha256: str = Field(pattern=SHA256_PATTERN)
    vessel_operator_approval_sha256: str = Field(pattern=SHA256_PATTERN)
    settlement_receipt_sha256: str | None = Field(default=None, pattern=SHA256_PATTERN)


class CollaborationApproval(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approval_id: str = Field(min_length=3, max_length=160)
    role: Literal["port_authority", "vessel_operator"]
    approver_id: str = Field(min_length=2, max_length=160)
    decision: Literal["approved", "rejected"]
    approved_at: datetime
    charter_sha256: str = Field(pattern=SHA256_PATTERN)
    approval_record_sha256: str = Field(pattern=SHA256_PATTERN)

    @field_validator("approved_at")
    @classmethod
    def approved_at_has_timezone(cls, value: datetime) -> datetime:
        return _timezone_required(value, "approval timestamp")


class CollaborationSourceAttestation(BaseModel):
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
        return _timezone_required(value, "observed_at")

    @field_validator("source_record_ids")
    @classmethod
    def unique_source_records(cls, value: list[str]) -> list[str]:
        if any(not item.strip() for item in value) or len(value) != len(set(value)):
            raise ValueError("source_record_ids must be unique and non-empty")
        return value


class PortCollaborationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["port-collaboration-input.v1"] = "port-collaboration-input.v1"
    case_id: str = Field(min_length=3, max_length=160)
    evaluated_at: datetime
    policy: PortCollaborationPolicy
    vessel_calls: list[VesselOperatorCallEvidence] = Field(min_length=1)
    milestones: list[PortCallMilestoneEvidence] = Field(min_length=1)
    berth_assignments: list[GreenBerthAssignmentEvidence] = Field(min_length=1)
    shore_power_reservations: list[ShorePowerReservationEvidence] = Field(min_length=1)
    alternative_fuel_services: list[AlternativeFuelReadinessEvidence] = Field(min_length=1)
    port_fee_incentives: list[PortFeeIncentiveEvidence] = Field(min_length=1)
    emission_benefit_claims: list[EmissionBenefitClaimEvidence] = Field(min_length=1)
    benefit_sharing: list[BenefitSharingEvidence] = Field(min_length=1)
    approvals: list[CollaborationApproval] = Field(min_length=2)
    source_attestations: list[CollaborationSourceAttestation] = Field(min_length=1)

    @field_validator("evaluated_at")
    @classmethod
    def evaluated_at_has_timezone(cls, value: datetime) -> datetime:
        return _timezone_required(value, "evaluated_at")


class PortCollaborationReport(BaseModel):
    schema_version: str
    report_id: str
    mode: str
    status: str
    source_readiness: dict[str, Any]
    corridor: dict[str, Any]
    port_calls: list[dict[str, Any]]
    jit_arrival: dict[str, Any]
    green_berth: dict[str, Any]
    shore_power: dict[str, Any]
    alternative_fuel: dict[str, Any]
    incentives: dict[str, Any]
    benefit_sharing: dict[str, Any]
    gates: list[dict[str, Any]]
    assurance: dict[str, Any]
    production_boundary: dict[str, bool]
    input_evidence_sha256: str | None = None
    evidence_sha256: str
