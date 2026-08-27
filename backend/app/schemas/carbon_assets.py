from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


SHA256_PATTERN = r"^[0-9a-f]{64}$"


class CompliancePeriod(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start_at: datetime
    end_at: datetime
    surrender_deadline: datetime

    @field_validator("start_at", "end_at", "surrender_deadline")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("compliance timestamps must be timezone-aware")
        return value

    @model_validator(mode="after")
    def ordered_period(self) -> "CompliancePeriod":
        if self.end_at <= self.start_at:
            raise ValueError("compliance period end_at must be after start_at")
        if self.surrender_deadline <= self.end_at:
            raise ValueError("surrender_deadline must be after the compliance period")
        return self


class CarbonProgramRules(BaseModel):
    model_config = ConfigDict(extra="forbid")

    program_id: str = Field(min_length=3, max_length=128)
    program_version: str = Field(min_length=1, max_length=64)
    jurisdiction: str = Field(min_length=2, max_length=128)
    compliance_period: CompliancePeriod
    surrender_ratio: float = Field(gt=0, le=2)
    eligible_vintages: list[int] = Field(min_length=1)
    approved_by: str = Field(min_length=2, max_length=128)
    approval_record_sha256: str = Field(pattern=SHA256_PATTERN)
    rules_document_sha256: str = Field(pattern=SHA256_PATTERN)

    @field_validator("eligible_vintages")
    @classmethod
    def unique_vintages(cls, value: list[int]) -> list[int]:
        if len(value) != len(set(value)):
            raise ValueError("eligible_vintages must be unique")
        return value


class RegistryAccountEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    registry_id: str = Field(min_length=3, max_length=128)
    account_id: str = Field(min_length=3, max_length=128)
    account_holder: str = Field(min_length=2, max_length=256)
    legal_entity_id: str = Field(min_length=2, max_length=128)
    status: Literal["active", "suspended", "closed"]
    ownership_evidence_sha256: str = Field(pattern=SHA256_PATTERN)
    approved_by: str = Field(min_length=2, max_length=128)


class VerifiedEmissionsEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    inventory_report_id: str = Field(min_length=3, max_length=160)
    reporting_entity: str = Field(min_length=2, max_length=256)
    period_start: datetime
    period_end: datetime
    verified_emissions_tco2e: float = Field(ge=0)
    assurance_conclusion: Literal["accepted", "qualified", "rejected"]
    verifier_id: str = Field(min_length=2, max_length=128)
    verified_at: datetime
    report_sha256: str = Field(pattern=SHA256_PATTERN)

    @field_validator("period_start", "period_end", "verified_at")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("verified emissions timestamps must be timezone-aware")
        return value

    @model_validator(mode="after")
    def ordered_period(self) -> "VerifiedEmissionsEvidence":
        if self.period_end <= self.period_start:
            raise ValueError("verified emissions period_end must be after period_start")
        if self.verified_at < self.period_end:
            raise ValueError("verified_at must not precede period_end")
        return self


class AllowanceLotEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    instrument_id: str = Field(min_length=3, max_length=160)
    serial_batch_id: str = Field(min_length=3, max_length=160)
    vintage: int
    quantity_tco2e: float = Field(gt=0)
    status: Literal["active", "reserved", "retired", "transferred"]
    beneficial_owner: str = Field(min_length=2, max_length=256)
    registry_record_sha256: str = Field(pattern=SHA256_PATTERN)


class CarbonTradeEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    transaction_id: str = Field(min_length=3, max_length=160)
    side: Literal["buy", "sell"]
    instrument_id: str = Field(min_length=3, max_length=160)
    quantity_tco2e: float = Field(gt=0)
    unit_price: float = Field(ge=0)
    currency: str = Field(min_length=3, max_length=3)
    fees: float = Field(ge=0)
    venue: str = Field(min_length=2, max_length=160)
    counterparty_id: str = Field(min_length=2, max_length=160)
    executed_at: datetime
    settled_at: datetime
    registry_transfer_id: str = Field(min_length=3, max_length=160)
    status: Literal["settled", "pending", "failed", "cancelled"]
    trade_confirmation_sha256: str = Field(pattern=SHA256_PATTERN)
    cash_settlement_sha256: str = Field(pattern=SHA256_PATTERN)

    @field_validator("executed_at", "settled_at")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("trade timestamps must be timezone-aware")
        return value

    @model_validator(mode="after")
    def ordered_trade(self) -> "CarbonTradeEvidence":
        if self.settled_at < self.executed_at:
            raise ValueError("settled_at must not precede executed_at")
        return self


class AllowanceRetirementEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    retirement_id: str = Field(min_length=3, max_length=160)
    quantity_tco2e: float = Field(gt=0)
    retired_at: datetime
    compliance_period_id: str = Field(min_length=3, max_length=160)
    registry_confirmation_sha256: str = Field(pattern=SHA256_PATTERN)
    status: Literal["confirmed", "pending", "rejected"]

    @field_validator("retired_at")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("retired_at must be timezone-aware")
        return value


class RegistryReconciliationEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reconciliation_id: str = Field(min_length=3, max_length=160)
    as_of: datetime
    opening_balance_tco2e: float = Field(ge=0)
    acquisitions_tco2e: float = Field(ge=0)
    disposals_tco2e: float = Field(ge=0)
    retirements_tco2e: float = Field(ge=0)
    registry_closing_balance_tco2e: float = Field(ge=0)
    internal_closing_balance_tco2e: float = Field(ge=0)
    registry_statement_sha256: str = Field(pattern=SHA256_PATTERN)
    status: Literal["reconciled", "review", "failed"]

    @field_validator("as_of")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("reconciliation as_of must be timezone-aware")
        return value


class CarbonComplianceApproval(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approval_id: str = Field(min_length=3, max_length=160)
    role: Literal["compliance", "finance"]
    approver_id: str = Field(min_length=2, max_length=128)
    decision: Literal["approved", "rejected"]
    approved_at: datetime
    approval_record_sha256: str = Field(pattern=SHA256_PATTERN)

    @field_validator("approved_at")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("approved_at must be timezone-aware")
        return value


class RegistryAttestationEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    attester_id: str = Field(min_length=2, max_length=128)
    organization: str = Field(min_length=2, max_length=256)
    issued_at: datetime
    conclusion: Literal["confirmed", "qualified", "rejected"]
    key_id: str = Field(min_length=3, max_length=128)
    signed_evidence_sha256: str = Field(pattern=SHA256_PATTERN)
    signature: str = Field(min_length=40, max_length=256, pattern=r"^[A-Za-z0-9+/]+={0,2}$")

    @field_validator("issued_at")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("issued_at must be timezone-aware")
        return value


class CarbonAssetComplianceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["carbon-asset-compliance-input.v1"] = (
        "carbon-asset-compliance-input.v1"
    )
    case_id: str = Field(min_length=3, max_length=160)
    program: CarbonProgramRules
    account: RegistryAccountEvidence
    verified_emissions: VerifiedEmissionsEvidence
    allowance_lots: list[AllowanceLotEvidence] = Field(min_length=1)
    trades: list[CarbonTradeEvidence] = Field(default_factory=list)
    no_trade_declaration_sha256: str | None = Field(default=None, pattern=SHA256_PATTERN)
    retirements: list[AllowanceRetirementEvidence] = Field(min_length=1)
    reconciliation: RegistryReconciliationEvidence
    approvals: list[CarbonComplianceApproval] = Field(min_length=2)
    registry_attestation: RegistryAttestationEvidence | None = None


class CarbonAssetComplianceReport(BaseModel):
    schema_version: str
    report_id: str
    mode: str
    status: str
    program: dict[str, Any]
    account: dict[str, Any]
    positions: dict[str, Any]
    settlement: dict[str, Any]
    ledger: list[dict[str, Any]]
    gates: list[dict[str, Any]]
    assurance: dict[str, Any]
    production_boundary: dict[str, bool]
    input_evidence_sha256: str | None = None
    evidence_sha256: str
