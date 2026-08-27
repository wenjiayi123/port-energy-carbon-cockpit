from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


SHA256_PATTERN = r"^[0-9a-f]{64}$"
SOURCE_DOMAINS = {
    "single_line_topology",
    "scada_switchgear",
    "power_quality_meters",
    "transformer_monitoring",
    "charging_management",
    "battery_management_system",
}
SourceDomain = Literal[
    "single_line_topology",
    "scada_switchgear",
    "power_quality_meters",
    "transformer_monitoring",
    "charging_management",
    "battery_management_system",
]


def _require_timezone(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


class ElectricalSourceAttestation(BaseModel):
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
    def timezone_required(cls, value: datetime) -> datetime:
        return _require_timezone(value, "source observed_at")

    @field_validator("source_record_ids")
    @classmethod
    def unique_records(cls, value: list[str]) -> list[str]:
        if any(not item.strip() for item in value) or len(value) != len(set(value)):
            raise ValueError("source_record_ids must be unique and non-empty")
        return value


class ElectricalAssessmentPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    policy_id: str = Field(min_length=3, max_length=160)
    minimum_voltage_pu: float = Field(gt=0, lt=1)
    maximum_voltage_pu: float = Field(gt=1, le=1.2)
    maximum_branch_loading_pct: float = Field(gt=0, le=150)
    minimum_power_factor: float = Field(gt=0, le=1)
    maximum_voltage_thd_pct: float = Field(gt=0, le=20)
    maximum_transformer_hot_spot_c: float = Field(gt=50, le=220)
    maximum_aging_acceleration_factor: float = Field(gt=0, le=1000)
    minimum_n_minus_one_critical_load_coverage_pct: float = Field(gt=0, le=100)
    minimum_island_critical_load_coverage_pct: float = Field(gt=0, le=100)
    maximum_charger_utilization_pct: float = Field(gt=0, lt=100)
    maximum_expected_charging_wait_minutes: float = Field(ge=0, le=1440)
    maximum_source_age_seconds: int = Field(ge=1, le=86_400)
    maximum_source_alignment_seconds: int = Field(ge=0, le=3_600)
    approved_by: str = Field(min_length=2, max_length=128)
    approval_record_sha256: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def coherent_voltage_band(self) -> "ElectricalAssessmentPolicy":
        if self.minimum_voltage_pu >= self.maximum_voltage_pu:
            raise ValueError("minimum voltage must be below maximum voltage")
        return self


class BusEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bus_id: str = Field(min_length=2, max_length=128)
    nominal_voltage_kv: float = Field(gt=0)
    active_load_kw: float = Field(ge=0)
    reactive_load_kvar: float = Field(ge=0)
    critical_active_load_kw: float = Field(ge=0)
    priority: int = Field(default=1, ge=1, le=10)
    energized_required: bool = True

    @model_validator(mode="after")
    def critical_load_within_total(self) -> "BusEvidence":
        if self.critical_active_load_kw > self.active_load_kw:
            raise ValueError("critical active load cannot exceed total active load")
        return self


class BranchEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    branch_id: str = Field(min_length=2, max_length=128)
    branch_type: Literal["line", "transformer", "grid_intertie"]
    from_bus_id: str = Field(min_length=2, max_length=128)
    to_bus_id: str = Field(min_length=2, max_length=128)
    resistance_pu: float = Field(ge=0, le=1)
    reactance_pu: float = Field(ge=0, le=1)
    rating_kva: float = Field(gt=0)
    switch_id: str = Field(min_length=2, max_length=128)
    normally_open: bool = False
    n_minus_one_contingency: bool = False

    @model_validator(mode="after")
    def distinct_buses(self) -> "BranchEvidence":
        if self.from_bus_id == self.to_bus_id:
            raise ValueError("branch endpoints must be distinct")
        return self


class SwitchStateEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    switch_id: str = Field(min_length=2, max_length=128)
    closed: bool
    protection_healthy: bool
    interlock_permissive: bool
    remote_state: Literal["open", "closed", "transition", "unknown"]

    @model_validator(mode="after")
    def coherent_remote_state(self) -> "SwitchStateEvidence":
        if self.remote_state in {"open", "closed"} and (
            self.closed != (self.remote_state == "closed")
        ):
            raise ValueError("closed flag and remote_state disagree")
        return self


class ElectricalSourceEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str = Field(min_length=2, max_length=128)
    bus_id: str = Field(min_length=2, max_length=128)
    source_type: Literal["grid", "photovoltaic", "generator", "storage"]
    available: bool
    active_power_kw: float = Field(ge=0)
    reactive_power_kvar: float
    maximum_active_power_kw: float = Field(gt=0)
    maximum_reactive_power_kvar: float = Field(ge=0)
    grid_forming: bool = False
    black_start_capable: bool = False

    @model_validator(mode="after")
    def within_capability(self) -> "ElectricalSourceEvidence":
        if self.active_power_kw > self.maximum_active_power_kw:
            raise ValueError("source active power exceeds declared capability")
        if abs(self.reactive_power_kvar) > self.maximum_reactive_power_kvar:
            raise ValueError("source reactive power exceeds declared capability")
        return self


class PowerQualityEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    meter_id: str = Field(min_length=2, max_length=128)
    bus_id: str = Field(min_length=2, max_length=128)
    measured_voltage_pu: float = Field(gt=0, le=2)
    measured_active_power_kw: float
    measured_reactive_power_kvar: float
    voltage_harmonics_pct: dict[int, float] = Field(min_length=1)
    measured_voltage_thd_pct: float | None = Field(default=None, ge=0, le=100)

    @field_validator("voltage_harmonics_pct")
    @classmethod
    def valid_harmonics(cls, value: dict[int, float]) -> dict[int, float]:
        if any(order < 2 or order > 50 or magnitude < 0 for order, magnitude in value.items()):
            raise ValueError("harmonic orders must be 2..50 with non-negative magnitudes")
        return value


class TransformerThermalEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    transformer_id: str = Field(min_length=2, max_length=128)
    branch_id: str = Field(min_length=2, max_length=128)
    ambient_temperature_c: float = Field(ge=-60, le=80)
    initial_top_oil_rise_c: float = Field(ge=0, le=160)
    initial_winding_hot_spot_rise_c: float = Field(ge=0, le=200)
    rated_top_oil_rise_c: float = Field(gt=0, le=160)
    rated_winding_hot_spot_rise_c: float = Field(gt=0, le=200)
    load_loss_ratio: float = Field(gt=0, le=20)
    top_oil_time_constant_minutes: float = Field(gt=0, le=1440)
    winding_time_constant_minutes: float = Field(gt=0, le=240)
    oil_exponent: float = Field(gt=0, le=2)
    winding_exponent: float = Field(gt=0, le=2)


class ChargingPoolEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pool_id: str = Field(min_length=2, max_length=128)
    bus_id: str = Field(min_length=2, max_length=128)
    charger_count: int = Field(gt=0, le=1000)
    available_charger_count: int = Field(gt=0, le=1000)
    charger_power_kw: float = Field(gt=0)
    arrival_rate_per_hour: float = Field(ge=0)
    mean_service_minutes: float = Field(gt=0, le=1440)
    observed_queue_vehicles: int = Field(ge=0)

    @model_validator(mode="after")
    def available_within_installed(self) -> "ChargingPoolEvidence":
        if self.available_charger_count > self.charger_count:
            raise ValueError("available chargers cannot exceed installed chargers")
        return self


class StorageWarrantyEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    storage_id: str = Field(min_length=2, max_length=128)
    source_id: str = Field(min_length=2, max_length=128)
    bus_id: str = Field(min_length=2, max_length=128)
    usable_capacity_kwh: float = Field(gt=0)
    state_of_charge_pct: float = Field(ge=0, le=100)
    minimum_state_of_charge_pct: float = Field(ge=0, le=100)
    maximum_state_of_charge_pct: float = Field(ge=0, le=100)
    state_of_health_pct: float = Field(ge=0, le=100)
    minimum_state_of_health_pct: float = Field(ge=0, le=100)
    cell_temperature_c: float = Field(ge=-60, le=120)
    maximum_cell_temperature_c: float = Field(gt=0, le=120)
    requested_active_power_kw: float
    requested_reactive_power_kvar: float
    maximum_charge_power_kw: float = Field(gt=0)
    maximum_discharge_power_kw: float = Field(gt=0)
    maximum_reactive_power_kvar: float = Field(ge=0)
    charge_efficiency: float = Field(gt=0, le=1)
    discharge_efficiency: float = Field(gt=0, le=1)
    daily_throughput_kwh: float = Field(ge=0)
    maximum_daily_throughput_kwh: float = Field(gt=0)
    cumulative_throughput_kwh: float = Field(ge=0)
    warranty_throughput_limit_kwh: float = Field(gt=0)
    equivalent_full_cycles: float = Field(ge=0)
    warranty_cycle_limit: float = Field(gt=0)
    minimum_island_reserve_kwh: float = Field(ge=0)

    @model_validator(mode="after")
    def coherent_limits(self) -> "StorageWarrantyEvidence":
        if not (
            self.minimum_state_of_charge_pct
            <= self.state_of_charge_pct
            <= self.maximum_state_of_charge_pct
        ):
            raise ValueError("storage SOC must be inside the declared operating band")
        return self


class NMinusOneScenario(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenario_id: str = Field(min_length=2, max_length=128)
    contingency_branch_id: str = Field(min_length=2, max_length=128)
    approved_tie_switch_ids: list[str] = Field(default_factory=list)
    minimum_critical_load_coverage_pct: float = Field(gt=0, le=100)

    @field_validator("approved_tie_switch_ids")
    @classmethod
    def unique_ties(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("approved tie switch IDs must be unique")
        return value


class IslandScenario(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenario_id: str = Field(min_length=2, max_length=128)
    pcc_switch_ids: list[str] = Field(min_length=1)
    duration_minutes: int = Field(gt=0, le=10_080)
    minimum_critical_load_coverage_pct: float = Field(gt=0, le=100)

    @field_validator("pcc_switch_ids")
    @classmethod
    def unique_pcc_switches(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("PCC switch IDs must be unique")
        return value


class ElectricalNetworkAssessmentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["port-electrical-network-input.v1"] = (
        "port-electrical-network-input.v1"
    )
    assessment_id: str = Field(min_length=3, max_length=160)
    site_id: str = Field(min_length=2, max_length=128)
    evaluated_at: datetime
    interval_minutes: int = Field(gt=0, le=1440)
    requested_by: str = Field(min_length=2, max_length=128)
    policy: ElectricalAssessmentPolicy
    source_attestations: list[ElectricalSourceAttestation] = Field(min_length=6)
    buses: list[BusEvidence] = Field(min_length=2, max_length=1000)
    branches: list[BranchEvidence] = Field(min_length=1, max_length=2000)
    switches: list[SwitchStateEvidence] = Field(min_length=1, max_length=2000)
    sources: list[ElectricalSourceEvidence] = Field(min_length=1, max_length=500)
    power_quality_measurements: list[PowerQualityEvidence] = Field(min_length=1, max_length=1000)
    transformer_thermal_measurements: list[TransformerThermalEvidence] = Field(
        min_length=1, max_length=500
    )
    charging_pools: list[ChargingPoolEvidence] = Field(min_length=1, max_length=500)
    storage_warranties: list[StorageWarrantyEvidence] = Field(min_length=1, max_length=500)
    n_minus_one_scenarios: list[NMinusOneScenario] = Field(min_length=1, max_length=100)
    island_scenarios: list[IslandScenario] = Field(min_length=1, max_length=100)

    @field_validator("evaluated_at")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        return _require_timezone(value, "evaluated_at")


class ElectricalNetworkAssessmentReport(BaseModel):
    schema_version: str
    report_id: str
    mode: str
    status: str
    source_readiness: dict[str, Any]
    network_summary: dict[str, Any]
    bus_results: list[dict[str, Any]]
    branch_results: list[dict[str, Any]]
    harmonic_results: list[dict[str, Any]]
    transformer_thermal_results: list[dict[str, Any]]
    n_minus_one_results: list[dict[str, Any]]
    island_results: list[dict[str, Any]]
    charging_queue_results: list[dict[str, Any]]
    storage_warranty_results: list[dict[str, Any]]
    gates: list[dict[str, Any]]
    assurance: dict[str, Any]
    production_boundary: dict[str, bool]
    input_evidence_sha256: str | None = None
    evidence_sha256: str
