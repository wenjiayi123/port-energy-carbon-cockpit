from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


SHA256_PATTERN = r"^[0-9a-f]{64}$"
SOURCE_DOMAINS = {
    "ais_and_vessel_calls",
    "berth_plan",
    "crane_work_orders",
    "yard_inventory",
    "truck_appointments",
    "reefer_monitoring",
    "shore_power_registry",
    "energy_management_system",
}
SourceDomain = Literal[
    "ais_and_vessel_calls",
    "berth_plan",
    "crane_work_orders",
    "yard_inventory",
    "truck_appointments",
    "reefer_monitoring",
    "shore_power_registry",
    "energy_management_system",
]


def _require_timezone(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


class PlanningHorizon(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start_at: datetime
    interval_minutes: Literal[15, 30, 60]
    slot_count: int = Field(ge=2, le=96)

    @field_validator("start_at")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        return _require_timezone(value, "horizon start_at")


class SourceAttestationEvidence(BaseModel):
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


class JointPlanningPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    policy_id: str = Field(min_length=3, max_length=160)
    minimum_service_coverage_pct: float = Field(gt=0, le=100)
    minimum_truck_appointment_coverage_pct: float = Field(gt=0, le=100)
    grid_reserve_margin_pct: float = Field(ge=0, lt=50)
    maximum_source_age_seconds: int = Field(ge=1, le=86_400)
    maximum_source_alignment_seconds: int = Field(ge=0, le=3_600)
    berth_beam_width: int = Field(ge=8, le=512)
    cost_weight: float = Field(ge=0)
    carbon_weight: float = Field(ge=0)
    delay_weight: float = Field(ge=0)
    battery_degradation_cny_per_kwh: float = Field(ge=0)
    approved_by: str = Field(min_length=2, max_length=128)
    approval_record_sha256: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def objective_has_weight(self) -> "JointPlanningPolicy":
        if self.cost_weight + self.carbon_weight + self.delay_weight <= 0:
            raise ValueError("at least one planning objective weight must be positive")
        return self


class VesselCallEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    vessel_call_id: str = Field(min_length=3, max_length=160)
    imo_number: str = Field(pattern=r"^IMO[0-9]{7}$")
    vessel_length_m: float = Field(gt=0)
    eta: datetime
    required_departure_at: datetime
    import_teu: float = Field(ge=0)
    export_teu: float = Field(ge=0)
    total_moves_teu: float = Field(gt=0)
    minimum_cranes: int = Field(ge=1, le=8)
    maximum_cranes: int = Field(ge=1, le=8)
    candidate_berth_ids: list[str] = Field(min_length=1)
    candidate_yard_block_ids: list[str] = Field(min_length=1)
    shore_power_compatible: bool
    hotel_load_kw: float = Field(ge=0)
    minimum_shore_energy_kwh: float = Field(ge=0)
    priority: int = Field(default=1, ge=1, le=10)

    @field_validator("eta", "required_departure_at")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        return _require_timezone(value, "vessel timestamp")

    @model_validator(mode="after")
    def coherent_call(self) -> "VesselCallEvidence":
        if self.required_departure_at <= self.eta:
            raise ValueError("required_departure_at must be after eta")
        if self.maximum_cranes < self.minimum_cranes:
            raise ValueError("maximum_cranes must not be below minimum_cranes")
        if abs(self.import_teu + self.export_teu - self.total_moves_teu) > 1e-6:
            raise ValueError("import_teu plus export_teu must equal total_moves_teu")
        for values in (self.candidate_berth_ids, self.candidate_yard_block_ids):
            if any(not item.strip() for item in values) or len(values) != len(set(values)):
                raise ValueError("candidate asset IDs must be unique and non-empty")
        if not self.shore_power_compatible and self.minimum_shore_energy_kwh > 0:
            raise ValueError("incompatible vessel cannot require shore energy")
        return self


class BerthAssetEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    berth_id: str = Field(min_length=2, max_length=128)
    available_from: datetime
    available_until: datetime
    maximum_vessel_length_m: float = Field(gt=0)
    maximum_simultaneous_cranes: int = Field(ge=1, le=8)
    shore_power_available: bool
    shore_power_capacity_kw: float = Field(ge=0)

    @field_validator("available_from", "available_until")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        return _require_timezone(value, "berth availability timestamp")

    @model_validator(mode="after")
    def ordered_availability(self) -> "BerthAssetEvidence":
        if self.available_until <= self.available_from:
            raise ValueError("berth available_until must be after available_from")
        if not self.shore_power_available and self.shore_power_capacity_kw > 0:
            raise ValueError("berth without shore power cannot declare shore capacity")
        return self


class CraneAssetEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    crane_id: str = Field(min_length=2, max_length=128)
    compatible_berth_ids: list[str] = Field(min_length=1)
    available_from: datetime
    available_until: datetime
    moves_per_hour: float = Field(gt=0)
    active_power_kw: float = Field(gt=0)

    @field_validator("available_from", "available_until")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        return _require_timezone(value, "crane availability timestamp")

    @model_validator(mode="after")
    def ordered_availability(self) -> "CraneAssetEvidence":
        if self.available_until <= self.available_from:
            raise ValueError("crane available_until must be after available_from")
        if len(self.compatible_berth_ids) != len(set(self.compatible_berth_ids)):
            raise ValueError("compatible_berth_ids must be unique")
        return self


class YardBlockEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    yard_block_id: str = Field(min_length=2, max_length=128)
    capacity_teu: float = Field(gt=0)
    initial_occupancy_teu: float = Field(ge=0)
    reefer_plug_capacity: int = Field(ge=0)
    handling_energy_kwh_per_teu: float = Field(ge=0)

    @model_validator(mode="after")
    def initial_capacity(self) -> "YardBlockEvidence":
        if self.initial_occupancy_teu > self.capacity_teu:
            raise ValueError("initial yard occupancy exceeds capacity")
        return self


class TruckGateEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    gate_id: str = Field(min_length=2, max_length=128)
    maximum_teu_per_slot: float = Field(gt=0)
    service_energy_kwh_per_teu: float = Field(ge=0)


class TruckAppointmentEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    appointment_id: str = Field(min_length=3, max_length=160)
    vessel_call_id: str = Field(min_length=3, max_length=160)
    direction: Literal["export_dropoff", "import_pickup"]
    window_start: datetime
    window_end: datetime
    teu: float = Field(gt=0)
    yard_block_id: str = Field(min_length=2, max_length=128)
    candidate_gate_ids: list[str] = Field(min_length=1)

    @field_validator("window_start", "window_end")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        return _require_timezone(value, "truck appointment timestamp")

    @model_validator(mode="after")
    def ordered_window(self) -> "TruckAppointmentEvidence":
        if self.window_end <= self.window_start:
            raise ValueError("truck appointment window_end must be after window_start")
        if len(self.candidate_gate_ids) != len(set(self.candidate_gate_ids)):
            raise ValueError("candidate_gate_ids must be unique")
        return self


class ReeferBatchEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    batch_id: str = Field(min_length=3, max_length=160)
    vessel_call_id: str = Field(min_length=3, max_length=160)
    yard_block_id: str = Field(min_length=2, max_length=128)
    connected_from: datetime
    connected_until: datetime
    container_count: int = Field(gt=0)
    power_kw_per_container: float = Field(gt=0)
    uninterrupted_service_required: bool = True

    @field_validator("connected_from", "connected_until")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        return _require_timezone(value, "reefer connection timestamp")

    @model_validator(mode="after")
    def ordered_connection(self) -> "ReeferBatchEvidence":
        if self.connected_until <= self.connected_from:
            raise ValueError("reefer connected_until must be after connected_from")
        return self


class EnergySlotEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slot_index: int = Field(ge=0, le=95)
    start_at: datetime
    base_terminal_load_kw: float = Field(ge=0)
    renewable_available_kw: float = Field(ge=0)
    grid_import_limit_kw: float = Field(gt=0)
    electricity_price_cny_per_kwh: float = Field(ge=0)
    grid_carbon_kg_per_kwh: float = Field(ge=0)

    @field_validator("start_at")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        return _require_timezone(value, "energy slot start_at")


class StorageAssetEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    storage_id: str = Field(min_length=2, max_length=128)
    usable_capacity_kwh: float = Field(gt=0)
    initial_soc_pct: float = Field(ge=0, le=100)
    minimum_soc_pct: float = Field(ge=0, le=100)
    maximum_soc_pct: float = Field(ge=0, le=100)
    terminal_minimum_soc_pct: float = Field(ge=0, le=100)
    maximum_charge_kw: float = Field(gt=0)
    maximum_discharge_kw: float = Field(gt=0)
    charge_efficiency: float = Field(gt=0, le=1)
    discharge_efficiency: float = Field(gt=0, le=1)

    @model_validator(mode="after")
    def coherent_soc_limits(self) -> "StorageAssetEvidence":
        if not (
            self.minimum_soc_pct
            <= self.initial_soc_pct
            <= self.maximum_soc_pct
        ):
            raise ValueError("initial SOC must be within storage limits")
        if not (
            self.minimum_soc_pct
            <= self.terminal_minimum_soc_pct
            <= self.maximum_soc_pct
        ):
            raise ValueError("terminal minimum SOC must be within storage limits")
        return self


class OperationsEnergyPlanningRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["operations-energy-plan-input.v1"] = (
        "operations-energy-plan-input.v1"
    )
    plan_id: str = Field(min_length=3, max_length=160)
    site_id: str = Field(min_length=2, max_length=128)
    requested_at: datetime
    requested_by: str = Field(min_length=2, max_length=128)
    horizon: PlanningHorizon
    policy: JointPlanningPolicy
    source_attestations: list[SourceAttestationEvidence] = Field(min_length=8)
    vessel_calls: list[VesselCallEvidence] = Field(min_length=1, max_length=20)
    berths: list[BerthAssetEvidence] = Field(min_length=1, max_length=20)
    cranes: list[CraneAssetEvidence] = Field(min_length=1, max_length=80)
    yard_blocks: list[YardBlockEvidence] = Field(min_length=1, max_length=100)
    truck_gates: list[TruckGateEvidence] = Field(min_length=1, max_length=20)
    truck_appointments: list[TruckAppointmentEvidence] = Field(min_length=1, max_length=500)
    reefer_batches: list[ReeferBatchEvidence] = Field(min_length=1, max_length=500)
    energy_slots: list[EnergySlotEvidence] = Field(min_length=2, max_length=96)
    storage: StorageAssetEvidence

    @field_validator("requested_at")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        return _require_timezone(value, "requested_at")


class OperationsEnergyPlanningReport(BaseModel):
    schema_version: str
    report_id: str
    mode: str
    status: str
    source_readiness: dict[str, Any]
    horizon: dict[str, Any]
    vessel_assignments: list[dict[str, Any]]
    crane_tasks: list[dict[str, Any]]
    truck_schedule: list[dict[str, Any]]
    slot_plan: list[dict[str, Any]]
    constraint_summary: dict[str, Any]
    kpis: dict[str, Any]
    gates: list[dict[str, Any]]
    assurance: dict[str, Any]
    production_boundary: dict[str, bool]
    input_evidence_sha256: str | None = None
    evidence_sha256: str
