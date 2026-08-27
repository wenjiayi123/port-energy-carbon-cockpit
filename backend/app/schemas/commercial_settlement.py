from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


SHA256_PATTERN = r"^[0-9a-f]{64}$"
SOURCE_DOMAINS = {
    "utility_tariff_invoice",
    "revenue_metering",
    "demand_response",
    "ancillary_services",
    "power_purchase_agreement",
    "renewable_certificate_registry",
    "tenant_billing",
    "investment_and_mv",
}
SourceDomain = Literal[
    "utility_tariff_invoice",
    "revenue_metering",
    "demand_response",
    "ancillary_services",
    "power_purchase_agreement",
    "renewable_certificate_registry",
    "tenant_billing",
    "investment_and_mv",
]


def _timezone_required(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


class SettlementPeriod(BaseModel):
    model_config = ConfigDict(extra="forbid")

    period_id: str = Field(min_length=3, max_length=160)
    start_at: datetime
    end_at: datetime

    @field_validator("start_at", "end_at")
    @classmethod
    def timestamps_have_timezone(cls, value: datetime) -> datetime:
        return _timezone_required(value, "settlement period timestamp")

    @model_validator(mode="after")
    def ordered_period(self) -> "SettlementPeriod":
        if self.end_at <= self.start_at:
            raise ValueError("settlement period end_at must be after start_at")
        return self


class CommercialSettlementPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    policy_id: str = Field(min_length=3, max_length=160)
    reporting_entity: str = Field(min_length=2, max_length=256)
    site_id: str = Field(min_length=2, max_length=160)
    currency: str = Field(min_length=3, max_length=3)
    settlement_period: SettlementPeriod
    expected_meter_intervals: int = Field(ge=1)
    minimum_measured_coverage_pct: float = Field(default=99.0, ge=0, le=100)
    maximum_energy_variance_pct: float = Field(default=1.0, ge=0, le=100)
    maximum_demand_variance_pct: float = Field(default=1.0, ge=0, le=100)
    maximum_amount_variance_pct: float = Field(default=0.5, ge=0, le=100)
    maximum_tenant_allocation_variance_pct: float = Field(default=0.5, ge=0, le=100)
    maximum_source_age_seconds: int = Field(default=86_400, ge=1, le=604_800)
    maximum_source_alignment_seconds: int = Field(default=86_400, ge=0, le=604_800)
    annualization_factor: float = Field(default=12.0, gt=0, le=366)
    discount_rate: float = Field(default=0.06, ge=0, lt=1)
    calculation_rule_sha256: str = Field(pattern=SHA256_PATTERN)
    approved_by: str = Field(min_length=2, max_length=128)
    approval_record_sha256: str = Field(pattern=SHA256_PATTERN)

    @field_validator("currency")
    @classmethod
    def uppercase_currency(cls, value: str) -> str:
        if value != value.upper():
            raise ValueError("currency must use uppercase ISO-style code")
        return value


class TariffPeriodRate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    period_code: str = Field(min_length=1, max_length=80)
    energy_rate_per_kwh: float = Field(ge=0)


class UtilityTariffEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    utility_id: str = Field(min_length=2, max_length=160)
    tariff_id: str = Field(min_length=2, max_length=160)
    tariff_version: str = Field(min_length=1, max_length=80)
    effective_from: datetime
    effective_through: datetime
    currency: str = Field(min_length=3, max_length=3)
    period_rates: list[TariffPeriodRate] = Field(min_length=1)
    demand_charge_per_kw: float = Field(ge=0)
    fixed_charge: float = Field(ge=0)
    tax_rate_pct: float = Field(ge=0, le=100)
    tariff_document_sha256: str = Field(pattern=SHA256_PATTERN)

    @field_validator("effective_from", "effective_through")
    @classmethod
    def timestamps_have_timezone(cls, value: datetime) -> datetime:
        return _timezone_required(value, "tariff effective timestamp")

    @model_validator(mode="after")
    def coherent_tariff(self) -> "UtilityTariffEvidence":
        if self.effective_through <= self.effective_from:
            raise ValueError("tariff effective_through must be after effective_from")
        codes = [item.period_code for item in self.period_rates]
        if len(codes) != len(set(codes)):
            raise ValueError("tariff period codes must be unique")
        if self.currency != self.currency.upper():
            raise ValueError("tariff currency must be uppercase")
        return self


class RevenueMeterInterval(BaseModel):
    model_config = ConfigDict(extra="forbid")

    interval_id: str = Field(min_length=2, max_length=160)
    meter_id: str = Field(min_length=2, max_length=160)
    start_at: datetime
    end_at: datetime
    tariff_period: str = Field(min_length=1, max_length=80)
    energy_kwh: float = Field(ge=0)
    demand_kw: float = Field(ge=0)
    quality: Literal["measured", "estimated", "invalid"]
    source_record_id: str = Field(min_length=1, max_length=256)
    source_payload_sha256: str = Field(pattern=SHA256_PATTERN)

    @field_validator("start_at", "end_at")
    @classmethod
    def timestamps_have_timezone(cls, value: datetime) -> datetime:
        return _timezone_required(value, "meter interval timestamp")

    @model_validator(mode="after")
    def ordered_interval(self) -> "RevenueMeterInterval":
        if self.end_at <= self.start_at:
            raise ValueError("meter interval end_at must be after start_at")
        return self


class UtilityInvoiceEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    invoice_id: str = Field(min_length=2, max_length=160)
    revenue_meter_id: str = Field(min_length=2, max_length=160)
    billing_start_at: datetime
    billing_end_at: datetime
    currency: str = Field(min_length=3, max_length=3)
    billed_energy_kwh: float = Field(ge=0)
    billed_peak_demand_kw: float = Field(ge=0)
    energy_charge: float = Field(ge=0)
    demand_charge: float = Field(ge=0)
    fixed_charge: float = Field(ge=0)
    tax_charge: float = Field(ge=0)
    total_amount: float = Field(ge=0)
    status: Literal["paid", "approved", "disputed", "void"]
    invoice_sha256: str = Field(pattern=SHA256_PATTERN)
    payment_receipt_sha256: str | None = Field(default=None, pattern=SHA256_PATTERN)

    @field_validator("billing_start_at", "billing_end_at")
    @classmethod
    def timestamps_have_timezone(cls, value: datetime) -> datetime:
        return _timezone_required(value, "invoice billing timestamp")

    @model_validator(mode="after")
    def ordered_period(self) -> "UtilityInvoiceEvidence":
        if self.billing_end_at <= self.billing_start_at:
            raise ValueError("invoice billing_end_at must be after billing_start_at")
        if self.currency != self.currency.upper():
            raise ValueError("invoice currency must be uppercase")
        return self


class DemandResponseSettlement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(min_length=2, max_length=160)
    baseline_method: str = Field(min_length=3, max_length=160)
    baseline_approved: bool
    committed_kw: float = Field(ge=0)
    metered_reduction_kw: float = Field(ge=0)
    event_hours: float = Field(gt=0)
    capacity_rate_per_kw: float = Field(ge=0)
    energy_rate_per_kwh: float = Field(ge=0)
    performance_factor: float = Field(ge=0, le=1)
    penalties: float = Field(ge=0)
    statement_amount: float = Field(ge=0)
    currency: str = Field(min_length=3, max_length=3)
    status: Literal["paid", "settled", "pending", "rejected"]
    operator_statement_sha256: str = Field(pattern=SHA256_PATTERN)
    payment_receipt_sha256: str | None = Field(default=None, pattern=SHA256_PATTERN)


class AncillaryServiceSettlement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    settlement_id: str = Field(min_length=2, max_length=160)
    product: str = Field(min_length=2, max_length=160)
    cleared_capacity_kw: float = Field(ge=0)
    service_hours: float = Field(gt=0)
    availability_rate_per_kw_hour: float = Field(ge=0)
    performance_score: float = Field(ge=0, le=1)
    penalties: float = Field(ge=0)
    statement_amount: float = Field(ge=0)
    currency: str = Field(min_length=3, max_length=3)
    status: Literal["paid", "settled", "pending", "rejected"]
    operator_statement_sha256: str = Field(pattern=SHA256_PATTERN)
    payment_receipt_sha256: str | None = Field(default=None, pattern=SHA256_PATTERN)


class PowerPurchaseAgreementEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_id: str = Field(min_length=2, max_length=160)
    supplier_id: str = Field(min_length=2, max_length=160)
    delivery_energy_kwh: float = Field(ge=0)
    contract_rate_per_kwh: float = Field(ge=0)
    fixed_fee: float = Field(ge=0)
    invoice_amount: float = Field(ge=0)
    currency: str = Field(min_length=3, max_length=3)
    status: Literal["paid", "settled", "pending", "disputed"]
    contract_sha256: str = Field(pattern=SHA256_PATTERN)
    delivery_statement_sha256: str = Field(pattern=SHA256_PATTERN)
    invoice_sha256: str = Field(pattern=SHA256_PATTERN)
    payment_receipt_sha256: str | None = Field(default=None, pattern=SHA256_PATTERN)


class RenewableCertificateEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    certificate_id: str = Field(min_length=2, max_length=160)
    serial_range: str = Field(min_length=2, max_length=200)
    energy_mwh: float = Field(gt=0)
    vintage: int = Field(ge=2000, le=2200)
    technology: str = Field(min_length=2, max_length=160)
    registry_account_id: str = Field(min_length=2, max_length=160)
    beneficiary: str = Field(min_length=2, max_length=256)
    retirement_period_id: str = Field(min_length=2, max_length=160)
    status: Literal["retired", "transferred", "active", "cancelled"]
    acquisition_cost: float = Field(ge=0)
    currency: str = Field(min_length=3, max_length=3)
    registry_record_sha256: str = Field(pattern=SHA256_PATTERN)
    retirement_receipt_sha256: str | None = Field(default=None, pattern=SHA256_PATTERN)


class TenantAllocationEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str = Field(min_length=2, max_length=160)
    meter_ids: list[str] = Field(min_length=1)
    energy_kwh: float = Field(ge=0)
    coincident_demand_kw: float = Field(ge=0)
    energy_charge: float = Field(ge=0)
    demand_charge: float = Field(ge=0)
    fixed_tax_charge: float = Field(ge=0)
    ppa_charge: float = Field(ge=0)
    certificate_charge: float = Field(ge=0)
    allocated_total: float = Field(ge=0)
    invoice_id: str = Field(min_length=2, max_length=160)
    invoice_status: Literal["issued", "paid", "approved", "disputed"]
    allocation_rule_sha256: str = Field(pattern=SHA256_PATTERN)
    tenant_invoice_sha256: str = Field(pattern=SHA256_PATTERN)

    @field_validator("meter_ids")
    @classmethod
    def unique_meter_ids(cls, value: list[str]) -> list[str]:
        if any(not item.strip() for item in value) or len(value) != len(set(value)):
            raise ValueError("tenant meter_ids must be unique and non-empty")
        return value


class MeasurementVerificationLink(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str = Field(min_length=2, max_length=160)
    report_id: str = Field(min_length=2, max_length=160)
    report_sha256: str = Field(pattern=SHA256_PATTERN)
    status: Literal["independently_reviewed", "calculated_only", "qualified", "rejected"]
    period_id: str = Field(min_length=2, max_length=160)
    verified_energy_savings_kwh: float = Field(ge=0)
    verified_carbon_reduction_tco2e: float = Field(ge=0)
    evidence_owner: str = Field(min_length=2, max_length=160)


class InvestmentMeasureEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    measure_id: str = Field(min_length=2, max_length=160)
    savings_claim_id: str = Field(min_length=2, max_length=160)
    energy_savings_by_period_kwh: dict[str, float] = Field(min_length=1)
    annual_demand_savings_kw: float = Field(ge=0)
    verified_carbon_reduction_tco2e: float = Field(ge=0)
    capex: float = Field(ge=0)
    annual_om_delta: float
    annual_settled_incentive: float = Field(ge=0)
    lifetime_years: int = Field(ge=1, le=100)
    currency: str = Field(min_length=3, max_length=3)
    approved: bool
    investment_approval_sha256: str = Field(pattern=SHA256_PATTERN)

    @field_validator("energy_savings_by_period_kwh")
    @classmethod
    def valid_period_savings(cls, value: dict[str, float]) -> dict[str, float]:
        if any(not key.strip() or amount < 0 for key, amount in value.items()):
            raise ValueError("energy savings periods must be non-empty and non-negative")
        return value


class CommercialApproval(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approval_id: str = Field(min_length=2, max_length=160)
    role: Literal["finance", "energy_manager"]
    approver_id: str = Field(min_length=2, max_length=160)
    decision: Literal["approved", "rejected"]
    approved_at: datetime
    calculation_rule_sha256: str = Field(pattern=SHA256_PATTERN)
    approval_record_sha256: str = Field(pattern=SHA256_PATTERN)

    @field_validator("approved_at")
    @classmethod
    def approved_at_has_timezone(cls, value: datetime) -> datetime:
        return _timezone_required(value, "approval timestamp")


class CommercialSourceAttestation(BaseModel):
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


class CommercialSettlementRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["commercial-settlement-input.v1"] = "commercial-settlement-input.v1"
    case_id: str = Field(min_length=3, max_length=160)
    evaluated_at: datetime
    policy: CommercialSettlementPolicy
    tariff: UtilityTariffEvidence
    meter_intervals: list[RevenueMeterInterval] = Field(min_length=1)
    utility_invoice: UtilityInvoiceEvidence
    demand_response_settlements: list[DemandResponseSettlement] = Field(min_length=1)
    ancillary_service_settlements: list[AncillaryServiceSettlement] = Field(min_length=1)
    ppa: PowerPurchaseAgreementEvidence
    renewable_certificates: list[RenewableCertificateEvidence] = Field(min_length=1)
    tenant_allocations: list[TenantAllocationEvidence] = Field(min_length=1)
    measurement_verification: MeasurementVerificationLink
    investment_measures: list[InvestmentMeasureEvidence] = Field(min_length=1)
    approvals: list[CommercialApproval] = Field(min_length=2)
    source_attestations: list[CommercialSourceAttestation] = Field(min_length=1)

    @field_validator("evaluated_at")
    @classmethod
    def evaluated_at_has_timezone(cls, value: datetime) -> datetime:
        return _timezone_required(value, "evaluated_at")


class CommercialSettlementReport(BaseModel):
    schema_version: str
    report_id: str
    mode: str
    status: str
    source_readiness: dict[str, Any]
    billing: dict[str, Any]
    market_settlements: dict[str, Any]
    renewable_procurement: dict[str, Any]
    tenant_allocation: dict[str, Any]
    measurement_verification: dict[str, Any]
    investment_economics: dict[str, Any]
    gates: list[dict[str, Any]]
    assurance: dict[str, Any]
    production_boundary: dict[str, bool]
    input_evidence_sha256: str | None = None
    evidence_sha256: str
