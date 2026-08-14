from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


RUNTIME_SCHEMA_VERSION = "energy-carbon-runtime.v1"
TELEMETRY_SCHEMA_VERSION = "telemetry-field.v1"

SourceType = Literal[
    "公开观测",
    "公开再分析",
    "官方聚合",
    "历史回放",
    "物理模拟",
    "工程派生",
    "现场实测",
]
QualityStatus = Literal["正常", "插值", "延迟", "漂移", "失联", "异常"]


class TelemetryField(BaseModel):
    """Stable field-level contract shared by simulation and future site adapters."""

    model_config = ConfigDict(extra="forbid")

    field_id: str = Field(min_length=2, max_length=128)
    value: float | int | str | bool | None
    unit: str = Field(min_length=1, max_length=64)
    event_time: str
    ingest_time: str
    source_type: SourceType
    source_id: str = Field(min_length=2, max_length=256)
    quality_status: QualityStatus
    confidence: float = Field(ge=0.0, le=1.0)
    is_measured: bool
    is_simulated: bool
    is_derived: bool
    site_id: str = Field(min_length=2, max_length=64)
    asset_id: str = Field(min_length=2, max_length=128)
    schema_version: str = TELEMETRY_SCHEMA_VERSION
    trace_id: str = Field(min_length=8, max_length=128)
    source_record_time: str | None = None
    assumption_id: str | None = None

    @model_validator(mode="after")
    def validate_classification(self) -> "TelemetryField":
        if sum((self.is_measured, self.is_simulated, self.is_derived)) != 1:
            raise ValueError(
                "exactly one of is_measured, is_simulated, or is_derived must be true"
            )
        return self


class RuntimeSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = RUNTIME_SCHEMA_VERSION
    snapshot_id: str
    trace_id: str
    site_id: str
    simulation_mode: bool = True
    simulator_state: Literal["running", "stopped", "failed_closed"]
    data_mode: Literal[
        "public_data_calibrated_realtime_simulation",
        "live_adapter_shadow",
    ] = "public_data_calibrated_realtime_simulation"
    live_data_verified: bool = False
    dispatch_allowed: bool = False
    production_authority: bool = False
    virtual_event_time: str
    generated_at: str
    dataset: dict[str, Any]
    seed: int
    step: int
    active_scenario: dict[str, Any]
    signals: dict[str, TelemetryField]
    topology: dict[str, Any]
    quality: dict[str, Any]
    kpis: dict[str, Any]
    decision_allowed: bool
    snapshot_sha256: str


class ScenarioInjectionRequest(BaseModel):
    scenario_id: Literal[
        "normal",
        "communications_loss",
        "sensor_drift",
        "transformer_derating",
        "battery_overtemperature",
        "extreme_heat",
        "equipment_fault",
        "demand_response_event",
    ]
    duration_steps: int = Field(default=8, ge=1, le=192)
    idempotency_key: str = Field(min_length=8, max_length=128)


class RuntimeControlRequest(BaseModel):
    action: Literal["start", "stop", "reset", "advance"]
    steps: int = Field(default=1, ge=1, le=1_000)
    idempotency_key: str = Field(min_length=8, max_length=128)


class DecisionRequest(BaseModel):
    objective: Literal[
        "balanced",
        "cost",
        "carbon",
        "peak",
        "service",
    ] = "balanced"
    idempotency_key: str = Field(min_length=8, max_length=128)
    requested_by: str = Field(default="local-operator", min_length=2, max_length=128)


class ApprovalRequest(BaseModel):
    approver_id: str = Field(min_length=2, max_length=128)
    decision: Literal["approve", "reject"] = "approve"
    comment: str = Field(default="", max_length=500)
    idempotency_key: str = Field(min_length=8, max_length=128)


class ExecuteRequest(BaseModel):
    idempotency_key: str = Field(min_length=8, max_length=128)
    executor_id: str = Field(default="simulation-executor", min_length=2, max_length=128)


class RollbackRequest(BaseModel):
    idempotency_key: str = Field(min_length=8, max_length=128)
    requested_by: str = Field(default="local-operator", min_length=2, max_length=128)
    reason: str = Field(min_length=2, max_length=500)
