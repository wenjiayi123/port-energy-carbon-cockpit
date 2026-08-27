from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


SHA256_PATTERN = r"^[0-9a-f]{64}$"


class MeasurementPeriod(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start_at: datetime
    end_at: datetime

    @field_validator("start_at", "end_at")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("measurement period timestamps must be timezone-aware")
        return value

    @model_validator(mode="after")
    def ordered_period(self) -> "MeasurementPeriod":
        if self.end_at <= self.start_at:
            raise ValueError("measurement period end_at must be after start_at")
        return self


class MeasurementBoundaryEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    boundary_id: str = Field(min_length=3, max_length=128)
    reporting_entity: str = Field(min_length=2, max_length=256)
    site_id: str = Field(min_length=2, max_length=128)
    accounting_meter_ids: list[str] = Field(min_length=1)
    included_assets: list[str] = Field(min_length=1)
    excluded_assets: list[str] = Field(default_factory=list)
    approved_by: str = Field(min_length=2, max_length=128)
    approval_record_sha256: str = Field(pattern=SHA256_PATTERN)

    @field_validator("accounting_meter_ids")
    @classmethod
    def unique_meter_ids(cls, value: list[str]) -> list[str]:
        if any(not item.strip() for item in value) or len(set(value)) != len(value):
            raise ValueError("accounting_meter_ids must be unique and non-empty")
        return value


class MeasurementVerificationPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan_id: str = Field(min_length=3, max_length=128)
    plan_version: str = Field(min_length=1, max_length=64)
    approved_by: str = Field(min_length=2, max_length=128)
    approval_record_sha256: str = Field(pattern=SHA256_PATTERN)
    expected_meter_interval_count: int = Field(ge=1)
    minimum_coverage_pct: float = Field(ge=0, le=100)
    maximum_estimated_pct: float = Field(ge=0, le=100)
    maximum_cv_rmse_pct: float = Field(ge=0)
    maximum_absolute_nmbe_pct: float = Field(ge=0)
    maximum_invoice_variance_pct: float = Field(ge=0)
    uncertainty_confidence_pct: float = Field(gt=0, lt=100)
    uncertainty_coverage_factor: float = Field(gt=0, le=5)


class BaselineModelEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    baseline_model_id: str = Field(min_length=3, max_length=128)
    method: str = Field(min_length=3, max_length=256)
    model_sha256: str = Field(pattern=SHA256_PATTERN)
    baseline_period: MeasurementPeriod
    frozen_at: datetime
    training_observations: int = Field(ge=1)
    validation_observations: int = Field(ge=1)
    cv_rmse_pct: float = Field(ge=0)
    nmbe_pct: float
    independent_variables: list[str] = Field(min_length=1)
    approved_by: str = Field(min_length=2, max_length=128)
    approval_record_sha256: str = Field(pattern=SHA256_PATTERN)

    @field_validator("frozen_at")
    @classmethod
    def frozen_at_timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("frozen_at must be timezone-aware")
        return value


class MeterIntervalEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    interval_id: str = Field(min_length=3, max_length=160)
    meter_id: str = Field(min_length=2, max_length=128)
    start_at: datetime
    end_at: datetime
    baseline_adjusted_energy_kwh: float = Field(ge=0)
    reporting_energy_kwh: float = Field(ge=0)
    baseline_adjusted_carbon_kg: float = Field(ge=0)
    reporting_carbon_kg: float = Field(ge=0)
    baseline_standard_uncertainty_kwh: float = Field(ge=0)
    reporting_standard_uncertainty_kwh: float = Field(ge=0)
    baseline_standard_uncertainty_carbon_kg: float = Field(ge=0)
    reporting_standard_uncertainty_carbon_kg: float = Field(ge=0)
    quality: Literal["measured", "estimated"]
    source_record_id: str = Field(min_length=1, max_length=256)
    source_payload_sha256: str = Field(pattern=SHA256_PATTERN)

    @field_validator("start_at", "end_at")
    @classmethod
    def interval_timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("meter interval timestamps must be timezone-aware")
        return value

    @model_validator(mode="after")
    def ordered_interval(self) -> "MeterIntervalEvidence":
        if self.end_at <= self.start_at:
            raise ValueError("meter interval end_at must be after start_at")
        return self


class MeterCalibrationEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    meter_id: str = Field(min_length=2, max_length=128)
    certificate_id: str = Field(min_length=2, max_length=128)
    valid_from: datetime
    valid_through: datetime
    certificate_sha256: str = Field(pattern=SHA256_PATTERN)
    status: Literal["valid", "expired", "revoked"]

    @field_validator("valid_from", "valid_through")
    @classmethod
    def calibration_timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("calibration timestamps must be timezone-aware")
        return value

    @model_validator(mode="after")
    def ordered_validity(self) -> "MeterCalibrationEvidence":
        if self.valid_through <= self.valid_from:
            raise ValueError("calibration valid_through must be after valid_from")
        return self


class InvoiceReconciliationEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reconciliation_id: str = Field(min_length=3, max_length=128)
    revenue_meter_id: str = Field(min_length=2, max_length=128)
    invoice_energy_kwh: float = Field(ge=0)
    interval_energy_kwh: float = Field(ge=0)
    variance_pct: float = Field(ge=0)
    status: Literal["reconciled", "review", "failed"]
    approved_by: str = Field(min_length=2, max_length=128)
    evidence_sha256: str = Field(pattern=SHA256_PATTERN)


class NonRoutineAdjustmentEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    adjustment_id: str = Field(min_length=3, max_length=128)
    adjustment_type: str = Field(min_length=3, max_length=128)
    reason: str = Field(min_length=3, max_length=512)
    applied_energy_kwh: float
    applied_carbon_kg: float
    approved: bool
    approved_by: str = Field(min_length=2, max_length=128)
    evidence_sha256: str = Field(pattern=SHA256_PATTERN)


class EmissionFactorRegistryEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    registry_id: str = Field(min_length=3, max_length=128)
    registry_version: str = Field(min_length=1, max_length=64)
    registry_sha256: str = Field(pattern=SHA256_PATTERN)
    approved_by: str = Field(min_length=2, max_length=128)


class IndependentVerificationEvidence(BaseModel):
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
    def reviewed_at_timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("reviewed_at must be timezone-aware")
        return value


class MeasurementVerificationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["energy-carbon-mv-input.v1"] = "energy-carbon-mv-input.v1"
    project_id: str = Field(min_length=3, max_length=128)
    boundary: MeasurementBoundaryEvidence
    plan: MeasurementVerificationPlan
    baseline_model: BaselineModelEvidence
    reporting_period: MeasurementPeriod
    intervals: list[MeterIntervalEvidence] = Field(min_length=1)
    meter_calibrations: list[MeterCalibrationEvidence] = Field(min_length=1)
    invoice_reconciliation: InvoiceReconciliationEvidence
    non_routine_adjustments: list[NonRoutineAdjustmentEvidence] = Field(default_factory=list)
    non_routine_adjustment_declaration_sha256: str = Field(pattern=SHA256_PATTERN)
    emission_factor_registry: EmissionFactorRegistryEvidence
    independent_verification: IndependentVerificationEvidence | None = None


class MeasurementVerificationReport(BaseModel):
    schema_version: str
    report_id: str
    mode: str
    status: str
    project: dict[str, Any]
    periods: dict[str, Any]
    baseline_model: dict[str, Any]
    data_quality: dict[str, Any]
    adjustments: dict[str, Any]
    uncertainty: dict[str, Any]
    gates: list[dict[str, Any]]
    results: dict[str, Any]
    assurance: dict[str, Any]
    production_boundary: dict[str, bool]
    input_evidence_sha256: str | None = None
    evidence_sha256: str
