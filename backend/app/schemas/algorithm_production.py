from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


SHA256_PATTERN = r"^[0-9a-f]{64}$"
SOURCE_DOMAINS = {
    "experiment_registry",
    "forecast_calibration",
    "runtime_monitoring",
    "execution_receipts",
    "fault_campaign",
    "human_review_log",
}
SourceDomain = Literal[
    "experiment_registry",
    "forecast_calibration",
    "runtime_monitoring",
    "execution_receipts",
    "fault_campaign",
    "human_review_log",
]
Season = Literal["spring", "summer", "autumn", "winter"]


def _timezone_required(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


class AlgorithmEvidenceAttestation(BaseModel):
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


class AlgorithmQualificationPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    policy_id: str = Field(min_length=3, max_length=160)
    candidate_policy_id: str = Field(min_length=2, max_length=160)
    baseline_policy_id: str = Field(min_length=2, max_length=160)
    minimum_distinct_seeds: int = Field(default=3, ge=3, le=100)
    required_seasons: list[Season] = Field(
        default_factory=lambda: ["spring", "summer", "autumn", "winter"],
        min_length=4,
        max_length=4,
    )
    minimum_pairs_per_seed_season: int = Field(default=1, ge=1, le=1000)
    nominal_interval_coverage: float = Field(default=0.9, gt=0, lt=1)
    minimum_interval_coverage: float = Field(default=0.85, gt=0, lt=1)
    maximum_interval_coverage: float = Field(default=0.98, gt=0, le=1)
    maximum_median_mae: float = Field(default=10.0, gt=0)
    minimum_forecast_samples: int = Field(default=20, ge=20)
    minimum_ood_true_positive_rate: float = Field(default=0.9, ge=0, le=1)
    maximum_ood_false_positive_rate: float = Field(default=0.05, ge=0, le=1)
    minimum_ood_samples_per_class: int = Field(default=10, ge=5)
    minimum_explanation_records: int = Field(default=12, ge=10)
    minimum_explanation_fidelity: float = Field(default=0.9, ge=0, le=1)
    minimum_action_receipts: int = Field(default=12, ge=10)
    maximum_action_tracking_error: float = Field(default=1.0, ge=0)
    maximum_ack_latency_ms: float = Field(default=2000.0, gt=0)
    minimum_latency_samples: int = Field(default=20, ge=20)
    maximum_p95_latency_ms: float = Field(default=1000.0, gt=0)
    maximum_p99_latency_ms: float = Field(default=1500.0, gt=0)
    required_fault_types: list[str] = Field(min_length=6)
    maximum_fault_recovery_ms: float = Field(default=5000.0, gt=0)
    minimum_human_reviews: int = Field(default=12, ge=10)
    minimum_distinct_reviewers: int = Field(default=2, ge=2)
    minimum_shadow_hours: float = Field(default=168.0, ge=24)
    minimum_shadow_decisions: int = Field(default=1000, ge=100)
    minimum_carbon_improvement_pct: float = Field(default=0.0, ge=0)
    maximum_cost_regression_pct: float = Field(default=0.0, ge=0)
    maximum_peak_regression_pct: float = Field(default=0.0, ge=0)
    maximum_throughput_regression_pct: float = Field(default=0.0, ge=0)
    maximum_reserve_breach_increase_pct: float = Field(default=0.0, ge=0)
    maximum_source_age_seconds: int = Field(default=300, ge=1, le=86_400)
    maximum_source_alignment_seconds: int = Field(default=60, ge=0, le=3_600)
    approved_by: str = Field(min_length=2, max_length=128)
    approval_record_sha256: str = Field(pattern=SHA256_PATTERN)

    @field_validator("required_seasons")
    @classmethod
    def all_seasons_once(cls, value: list[Season]) -> list[Season]:
        if len(set(value)) != 4 or set(value) != {"spring", "summer", "autumn", "winter"}:
            raise ValueError("required_seasons must contain all four seasons exactly once")
        return value

    @field_validator("required_fault_types")
    @classmethod
    def unique_fault_types(cls, value: list[str]) -> list[str]:
        if any(not item.strip() for item in value) or len(value) != len(set(value)):
            raise ValueError("required_fault_types must be unique and non-empty")
        return value

    @model_validator(mode="after")
    def coherent_coverage_band(self) -> "AlgorithmQualificationPolicy":
        if not (
            self.minimum_interval_coverage
            <= self.nominal_interval_coverage
            <= self.maximum_interval_coverage
        ):
            raise ValueError("nominal coverage must be inside the accepted coverage band")
        if self.candidate_policy_id == self.baseline_policy_id:
            raise ValueError("candidate and baseline policies must be distinct")
        return self


class PolicyArtifactEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    policy_id: str = Field(min_length=2, max_length=160)
    role: Literal["candidate", "baseline"]
    algorithm_family: str = Field(min_length=2, max_length=160)
    artifact_sha256: str = Field(pattern=SHA256_PATTERN)
    dataset_sha256: str = Field(pattern=SHA256_PATTERN)
    code_sha256: str = Field(pattern=SHA256_PATTERN)
    observation_contract_sha256: str = Field(pattern=SHA256_PATTERN)
    action_contract_sha256: str = Field(pattern=SHA256_PATTERN)
    immutable: bool


class EvaluationMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    carbon_kg: float = Field(gt=0)
    cost_cny: float = Field(gt=0)
    peak_kw: float = Field(gt=0)
    throughput_teu: float = Field(gt=0)
    delay_minutes: float = Field(ge=0)
    safety_violations: int = Field(ge=0)
    reserve_breach_steps: int = Field(ge=0)


class EvaluationPairEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pair_id: str = Field(min_length=2, max_length=160)
    seed: int = Field(ge=0)
    season: Season
    split: Literal["test", "read_only_shadow"]
    candidate_policy_id: str = Field(min_length=2, max_length=160)
    baseline_policy_id: str = Field(min_length=2, max_length=160)
    candidate: EvaluationMetrics
    baseline: EvaluationMetrics
    source_window_sha256: str = Field(pattern=SHA256_PATTERN)


class ProbabilisticForecastEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    forecast_id: str = Field(min_length=2, max_length=160)
    decision_id: str = Field(min_length=2, max_length=160)
    target: str = Field(min_length=2, max_length=80)
    horizon_minutes: int = Field(gt=0, le=10_080)
    lower: float
    median: float
    upper: float
    actual: float

    @model_validator(mode="after")
    def ordered_quantiles(self) -> "ProbabilisticForecastEvidence":
        if not self.lower <= self.median <= self.upper:
            raise ValueError("forecast quantiles must be non-decreasing")
        return self


class OodDetectionEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(min_length=2, max_length=160)
    decision_id: str = Field(min_length=2, max_length=160)
    expected_ood: bool
    score: float = Field(ge=0)
    threshold: float = Field(gt=0)
    detected: bool
    fallback_activated: bool
    recommendation_suppressed: bool
    fallback_policy_id: str | None = Field(default=None, max_length=160)


class ExplanationEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision_id: str = Field(min_length=2, max_length=160)
    model_sha256: str = Field(pattern=SHA256_PATTERN)
    policy_sha256: str = Field(pattern=SHA256_PATTERN)
    input_sha256: str = Field(pattern=SHA256_PATTERN)
    reason_codes: list[str] = Field(min_length=1)
    feature_attributions: dict[str, float] = Field(min_length=1)
    local_fidelity: float = Field(ge=0, le=1)
    counterfactual_action: dict[str, float] = Field(min_length=1)
    rationale: str = Field(min_length=8, max_length=1000)
    generated_before_human_review: bool


class ActionLimitEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    minimum: float
    maximum: float
    maximum_delta: float = Field(gt=0)
    unit: str = Field(min_length=1, max_length=32)

    @model_validator(mode="after")
    def coherent_limits(self) -> "ActionLimitEvidence":
        if self.minimum >= self.maximum:
            raise ValueError("action minimum must be below maximum")
        return self


class ActionReachabilityEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command_id: str = Field(min_length=2, max_length=160)
    decision_id: str = Field(min_length=2, max_length=160)
    mode: Literal["read_only_shadow"]
    receipt_kind: Literal["site_shadow_gateway_ack"]
    current_action: dict[str, float] = Field(min_length=1)
    requested_action: dict[str, float] = Field(min_length=1)
    projected_action: dict[str, float] = Field(min_length=1)
    acknowledged_action: dict[str, float] = Field(min_length=1)
    limits: dict[str, ActionLimitEvidence] = Field(min_length=1)
    ack_latency_ms: float = Field(ge=0)
    interlocks_satisfied: bool
    receipt_sha256: str = Field(pattern=SHA256_PATTERN)


class LatencyEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision_id: str = Field(min_length=2, max_length=160)
    mode: Literal["read_only_shadow"]
    forecast_ms: float = Field(ge=0)
    policy_ms: float = Field(ge=0)
    safety_projection_ms: float = Field(ge=0)
    end_to_end_ms: float = Field(ge=0)
    timed_out: bool
    fallback_activated: bool


class FaultInjectionEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    campaign_id: str = Field(min_length=2, max_length=160)
    fault_id: str = Field(min_length=2, max_length=160)
    fault_type: str = Field(min_length=2, max_length=160)
    detected: bool
    failed_closed: bool
    fallback_activated: bool
    unsafe_action_count: int = Field(ge=0)
    recovery_ms: float = Field(ge=0)
    receipt_sha256: str = Field(pattern=SHA256_PATTERN)


class HumanReviewEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision_id: str = Field(min_length=2, max_length=160)
    requested_by: str = Field(min_length=2, max_length=128)
    reviewer_id: str = Field(min_length=2, max_length=128)
    outcome: Literal["approve", "reject", "veto", "modify"]
    reason_code: str = Field(min_length=2, max_length=160)
    comment: str = Field(min_length=2, max_length=1000)
    reviewed_at: datetime
    policy_sha256: str = Field(pattern=SHA256_PATTERN)
    input_sha256: str = Field(pattern=SHA256_PATTERN)
    audit_event_sha256: str = Field(pattern=SHA256_PATTERN)

    @field_validator("reviewed_at")
    @classmethod
    def reviewed_at_has_timezone(cls, value: datetime) -> datetime:
        return _timezone_required(value, "reviewed_at")

    @model_validator(mode="after")
    def separation_of_duties(self) -> "HumanReviewEvidence":
        if self.requested_by == self.reviewer_id:
            raise ValueError("requester cannot review their own decision")
        return self


class ShadowRunEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(min_length=2, max_length=160)
    site_id: str = Field(min_length=2, max_length=128)
    mode: Literal["read_only_shadow"]
    started_at: datetime
    ended_at: datetime
    decision_count: int = Field(ge=0)
    live_data_verified: bool
    run_evidence_sha256: str = Field(pattern=SHA256_PATTERN)

    @field_validator("started_at", "ended_at")
    @classmethod
    def timestamps_have_timezone(cls, value: datetime) -> datetime:
        return _timezone_required(value, "shadow timestamp")

    @model_validator(mode="after")
    def positive_duration(self) -> "ShadowRunEvidence":
        if self.ended_at <= self.started_at:
            raise ValueError("shadow run end must be after start")
        return self


class AlgorithmProductionQualificationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["algorithm-production-qualification-input.v1"] = (
        "algorithm-production-qualification-input.v1"
    )
    qualification_id: str = Field(min_length=3, max_length=160)
    site_id: str = Field(min_length=2, max_length=128)
    evaluated_at: datetime
    requested_by: str = Field(min_length=2, max_length=128)
    policy: AlgorithmQualificationPolicy
    source_attestations: list[AlgorithmEvidenceAttestation] = Field(min_length=6)
    artifacts: list[PolicyArtifactEvidence] = Field(min_length=2)
    evaluation_pairs: list[EvaluationPairEvidence] = Field(min_length=12)
    probabilistic_forecasts: list[ProbabilisticForecastEvidence] = Field(min_length=20)
    ood_events: list[OodDetectionEvidence] = Field(min_length=10)
    explanations: list[ExplanationEvidence] = Field(min_length=10)
    action_receipts: list[ActionReachabilityEvidence] = Field(min_length=10)
    latency_samples: list[LatencyEvidence] = Field(min_length=20)
    fault_injections: list[FaultInjectionEvidence] = Field(min_length=6)
    human_reviews: list[HumanReviewEvidence] = Field(min_length=10)
    shadow_runs: list[ShadowRunEvidence] = Field(min_length=1)

    @field_validator("evaluated_at")
    @classmethod
    def evaluated_at_has_timezone(cls, value: datetime) -> datetime:
        return _timezone_required(value, "evaluated_at")


class AlgorithmProductionQualificationReport(BaseModel):
    schema_version: str
    report_id: str
    mode: str
    status: str
    source_readiness: dict[str, Any]
    qualification_summary: dict[str, Any]
    multi_seed_cross_season: dict[str, Any]
    probabilistic_forecast: dict[str, Any]
    ood_monitoring: dict[str, Any]
    explainability: dict[str, Any]
    action_reachability: dict[str, Any]
    realtime_performance: dict[str, Any]
    fault_campaign: dict[str, Any]
    human_oversight: dict[str, Any]
    champion_challenger: dict[str, Any]
    known_offline_evidence: dict[str, Any]
    gates: list[dict[str, Any]]
    assurance: dict[str, Any]
    production_boundary: dict[str, bool]
    input_evidence_sha256: str | None
    evidence_sha256: str
