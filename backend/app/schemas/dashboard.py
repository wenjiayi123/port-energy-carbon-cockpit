from typing import Any

from pydantic import BaseModel, Field

from app.schemas.algorithm_production import AlgorithmProductionQualificationReport
from app.schemas.carbon_assets import CarbonAssetComplianceReport
from app.schemas.commercial_settlement import CommercialSettlementReport
from app.schemas.energy_carbon_management import EnergyCarbonManagementReport
from app.schemas.electrical_network import ElectricalNetworkAssessmentReport
from app.schemas.enterprise_security import EnterpriseSecurityReport
from app.schemas.measurement_verification import MeasurementVerificationReport
from app.schemas.operations_energy_planning import OperationsEnergyPlanningReport
from app.schemas.port_collaboration import PortCollaborationReport
from app.schemas.site_cutover import SiteCutoverReport


class KpiCard(BaseModel):
    key: str
    label: str
    value: float
    unit: str
    delta: float = 0.0


class DispatchTrajectoryPoint(BaseModel):
    step: int
    time: str
    event: str
    period: str
    source_id: str
    vessel_id: str
    berth_id: str
    crane_count: int
    yard_truck_count: int
    shore_power_connected: bool
    energy_kwh: float
    carbon_kg: float
    delay_minutes: float
    processed_teu: float
    queue_teu: float
    load_kw: float
    peak_violation_kw: float
    cost_cny: float
    grid_carbon_kg: float
    fuel_carbon_kg: float
    decision_reason: str


class StrategyComparison(BaseModel):
    strategy: str
    total_energy_kwh: float
    total_carbon_kg: float
    carbon_intensity_kg_per_teu: float
    shore_power_usage_rate: float
    delay_cost_cny: float
    total_cost_cny: float
    trajectory: list[DispatchTrajectoryPoint]


class CarbonMarket(BaseModel):
    carbon_price_cny_per_ton: float
    quota_ton: float
    emission_ton: float
    baseline_emission_ton: float
    quota_gap_ton: float
    baseline_quota_gap_ton: float
    carbon_cost_cny: float
    baseline_carbon_cost_cny: float
    carbon_cost_saving_cny: float
    abatement_ton: float
    abatement_value_cny: float
    quota_utilization_rate: float
    baseline_quota_utilization_rate: float
    optimized_total_cost_cny: float
    baseline_total_cost_cny: float
    total_cost_saving_cny: float
    optimization_advice: str
    quota_basis: str
    price_basis: str


class CarbonModelSummary(BaseModel):
    model_version: str
    total_carbon_kg: float
    total_carbon_ton: float
    handled_teu: float
    carbon_intensity_kg_per_teu: float
    shore_power_reduction_kg: float
    source_breakdown_kg: dict[str, float]
    scope_breakdown_kg: dict[str, float]
    scope1_auxiliary_fuel_kg: float
    scope2_location_based_kg: float
    scope2_market_based_kg: float | None = None
    scope2_method: str
    market_based_status: str
    factor_quality: dict[str, Any]
    uncertainty_note: str
    assurance_status: str
    data_source: str = ""
    dataset_sha256: str = ""
    calculation_method: str = ""


class PortEmissionSourceCategory(BaseModel):
    source_id: str
    label_zh: str
    label_en: str
    actor: str
    availability: str
    activity_data_status: str
    inventory_boundary: str
    ghg_scope: str
    legacy_scope: str | None = None
    co2e_kg: float | None = None
    pollutants_kg: dict[str, float | None]
    factor_ids: list[str]
    evidence_class: str
    assurance_status: str
    missing_evidence: list[str]


class EmissionFactorRecord(BaseModel):
    factor_id: str
    substance: str
    value: float | None = None
    unit: str
    value_mode: str
    source_name: str
    source_url: str | None = None
    dataset_version: str
    quality: str
    status: str


class PortEmissionsInventory(BaseModel):
    schema_version: str
    inventory_kind: str
    reporting_boundary: dict[str, Any]
    methodology: dict[str, Any]
    dataset_id: str
    dataset_sha256: str
    source_categories: list[PortEmissionSourceCategory]
    factor_register: list[EmissionFactorRecord]
    totals: dict[str, Any]
    coverage: dict[str, Any]
    assurance: dict[str, Any]
    production_boundary: dict[str, bool]
    evidence_sha256: str


class OperationalAlert(BaseModel):
    code: str
    severity: str
    title_zh: str
    title_en: str
    detail_zh: str
    detail_en: str
    source: str
    value: float | None = None
    threshold: float | None = None


class TimeSeriesPoint(BaseModel):
    time: str
    traditional_carbon_kg: float
    marl_carbon_kg: float
    traditional_energy_kwh: float
    marl_energy_kwh: float


class RlRewardTracePoint(BaseModel):
    step: int
    reward: float
    carbon_penalty: float
    delay_penalty: float
    energy_penalty: float
    shore_power_bonus: float


class RlEnvironmentSummary(BaseModel):
    status: str
    environment_id: str
    dataset_id: str
    dataset_path: str
    dataset_sha256: str
    action_policy: str
    episode_steps: int
    total_reward: float
    average_reward: float
    terminated: bool
    truncated: bool
    observation_keys: list[str]
    reward_trace: list[RlRewardTracePoint]


class DashboardSnapshot(BaseModel):
    scenario_id: str
    green_preference: float = Field(ge=0, le=1)
    kpis: list[KpiCard]
    strategies: list[StrategyComparison]
    carbon_market: CarbonMarket
    carbon_model: CarbonModelSummary
    carbon_inventory: PortEmissionsInventory
    measurement_verification: MeasurementVerificationReport
    carbon_assets: CarbonAssetComplianceReport
    commercial_settlement: CommercialSettlementReport
    port_collaboration: PortCollaborationReport
    enterprise_security: EnterpriseSecurityReport
    energy_carbon_management: EnergyCarbonManagementReport
    operations_energy_plan: OperationsEnergyPlanningReport
    electrical_network: ElectricalNetworkAssessmentReport
    algorithm_production: AlgorithmProductionQualificationReport
    site_cutover_readiness: SiteCutoverReport
    timeseries: list[TimeSeriesPoint]
    rl_environment: RlEnvironmentSummary
    data_quality: dict[str, Any]
    data_drift: dict[str, Any]
    alerts: list[OperationalAlert]
    governance: dict[str, Any]


class TimeSeriesResponse(BaseModel):
    scenario_id: str
    points: list[TimeSeriesPoint]


class RecomputeRequest(BaseModel):
    scenario_id: str = "port_la_2025_public_benchmark"
    green_preference: float = Field(default=0.5, ge=0, le=1)
    carbon_price_cny_per_ton: float = Field(default=85.0, ge=0)
