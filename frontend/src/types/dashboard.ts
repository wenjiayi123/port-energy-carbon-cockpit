export interface KpiCard {
  key: string;
  label: string;
  value: number;
  unit: string;
  delta: number;
}

export interface DispatchTrajectoryPoint {
  step: number;
  time: string;
  event: string;
  period: string;
  source_id: string;
  vessel_id: string;
  berth_id: string;
  crane_count: number;
  yard_truck_count: number;
  shore_power_connected: boolean;
  energy_kwh: number;
  carbon_kg: number;
  delay_minutes: number;
  processed_teu: number;
  queue_teu: number;
  load_kw: number;
  peak_violation_kw: number;
  cost_cny: number;
  grid_carbon_kg: number;
  fuel_carbon_kg: number;
  decision_reason: string;
}

export interface StrategyComparisonRow {
  strategy: string;
  total_energy_kwh: number;
  total_carbon_kg: number;
  carbon_intensity_kg_per_teu: number;
  shore_power_usage_rate: number;
  delay_cost_cny: number;
  total_cost_cny: number;
  trajectory: DispatchTrajectoryPoint[];
}

export interface CarbonModelSummary {
  model_version: string;
  total_carbon_kg: number;
  total_carbon_ton: number;
  handled_teu: number;
  carbon_intensity_kg_per_teu: number;
  shore_power_reduction_kg: number;
  source_breakdown_kg: Record<string, number>;
  scope_breakdown_kg: Record<string, number>;
  scope1_auxiliary_fuel_kg: number;
  scope2_location_based_kg: number;
  scope2_market_based_kg: number | null;
  scope2_method: string;
  market_based_status: string;
  factor_quality: Record<string, unknown>;
  uncertainty_note: string;
  assurance_status: string;
  data_source: string;
  dataset_sha256: string;
  calculation_method: string;
}

export interface PortEmissionSourceCategory {
  source_id: string;
  label_zh: string;
  label_en: string;
  actor: string;
  availability: string;
  activity_data_status: string;
  inventory_boundary: string;
  ghg_scope: string;
  legacy_scope: string | null;
  co2e_kg: number | null;
  pollutants_kg: Record<string, number | null>;
  factor_ids: string[];
  evidence_class: string;
  assurance_status: string;
  missing_evidence: string[];
}

export interface PortEmissionsInventory {
  schema_version: string;
  inventory_kind: string;
  reporting_boundary: Record<string, any>;
  methodology: Record<string, any>;
  dataset_id: string;
  dataset_sha256: string;
  source_categories: PortEmissionSourceCategory[];
  factor_register: Array<Record<string, any>>;
  totals: Record<string, any>;
  coverage: Record<string, any>;
  assurance: Record<string, any>;
  production_boundary: Record<string, boolean>;
  evidence_sha256: string;
}

export interface MeasurementVerificationReport {
  schema_version: string;
  report_id: string;
  mode: string;
  status: string;
  project: Record<string, any>;
  periods: Record<string, any>;
  baseline_model: Record<string, any>;
  data_quality: Record<string, any>;
  adjustments: Record<string, any>;
  uncertainty: Record<string, any>;
  gates: Array<Record<string, any>>;
  results: Record<string, any>;
  assurance: Record<string, any>;
  production_boundary: Record<string, boolean>;
  input_evidence_sha256: string | null;
  evidence_sha256: string;
}

export interface CarbonAssetComplianceReport {
  schema_version: string;
  report_id: string;
  mode: string;
  status: string;
  program: Record<string, any>;
  account: Record<string, any>;
  positions: Record<string, any>;
  settlement: Record<string, any>;
  ledger: Array<Record<string, any>>;
  gates: Array<Record<string, any>>;
  assurance: Record<string, any>;
  production_boundary: Record<string, boolean>;
  input_evidence_sha256: string | null;
  evidence_sha256: string;
}

export interface CommercialSettlementReport {
  schema_version: string;
  report_id: string;
  mode: string;
  status: string;
  source_readiness: Record<string, any>;
  billing: Record<string, any>;
  market_settlements: Record<string, any>;
  renewable_procurement: Record<string, any>;
  tenant_allocation: Record<string, any>;
  measurement_verification: Record<string, any>;
  investment_economics: Record<string, any>;
  gates: Array<Record<string, any>>;
  assurance: Record<string, any>;
  production_boundary: Record<string, boolean>;
  input_evidence_sha256: string | null;
  evidence_sha256: string;
}

export interface PortCollaborationReport {
  schema_version: string;
  report_id: string;
  mode: string;
  status: string;
  source_readiness: Record<string, any>;
  corridor: Record<string, any>;
  port_calls: Array<Record<string, any>>;
  jit_arrival: Record<string, any>;
  green_berth: Record<string, any>;
  shore_power: Record<string, any>;
  alternative_fuel: Record<string, any>;
  incentives: Record<string, any>;
  benefit_sharing: Record<string, any>;
  gates: Array<Record<string, any>>;
  assurance: Record<string, any>;
  production_boundary: Record<string, boolean>;
  input_evidence_sha256: string | null;
  evidence_sha256: string;
}

export interface EnterpriseSecurityReport {
  schema_version: string;
  report_id: string;
  mode: string;
  status: string;
  source_readiness: Record<string, any>;
  current_repository_controls: Record<string, any>;
  identity_and_access: Record<string, any>;
  tenant_isolation: Record<string, any>;
  messaging_and_timeseries: Record<string, any>;
  availability_and_recovery: Record<string, any>;
  audit_and_monitoring: Record<string, any>;
  pki_and_key_management: Record<string, any>;
  ot_security: Record<string, any>;
  gates: Array<Record<string, any>>;
  assurance: Record<string, any>;
  production_boundary: Record<string, boolean>;
  input_evidence_sha256: string | null;
  evidence_sha256: string;
}

export interface SiteCutoverReport {
  schema_version: string;
  report_id: string;
  mode: string;
  status: string;
  source_readiness: Record<string, any>;
  domain_evidence: Array<Record<string, any>>;
  site_consistency: Record<string, any>;
  operational_acceptance: Record<string, any>;
  approval_summary: Record<string, any>;
  gates: Array<Record<string, any>>;
  assurance: Record<string, any>;
  production_boundary: Record<string, boolean>;
  approval_subject_sha256: string | null;
  input_evidence_sha256: string | null;
  evidence_sha256: string;
}

export interface EnergyCarbonManagementReport {
  schema_version: string;
  report_id: string;
  mode: string;
  status: string;
  standards: Record<string, any>;
  organization: Record<string, any>;
  pdca: Record<string, any>;
  performance: Record<string, any>;
  audit: Record<string, any>;
  gates: Array<Record<string, any>>;
  assurance: Record<string, any>;
  production_boundary: Record<string, boolean>;
  input_evidence_sha256: string | null;
  evidence_sha256: string;
}

export interface OperationsEnergyPlanningReport {
  schema_version: string;
  report_id: string;
  mode: string;
  status: string;
  source_readiness: Record<string, any>;
  horizon: Record<string, any>;
  vessel_assignments: Array<Record<string, any>>;
  crane_tasks: Array<Record<string, any>>;
  truck_schedule: Array<Record<string, any>>;
  slot_plan: Array<Record<string, any>>;
  constraint_summary: Record<string, any>;
  kpis: Record<string, any>;
  gates: Array<Record<string, any>>;
  assurance: Record<string, any>;
  production_boundary: Record<string, boolean>;
  input_evidence_sha256: string | null;
  evidence_sha256: string;
}

export interface ElectricalNetworkAssessmentReport {
  schema_version: string;
  report_id: string;
  mode: string;
  status: string;
  source_readiness: Record<string, any>;
  network_summary: Record<string, any>;
  bus_results: Array<Record<string, any>>;
  branch_results: Array<Record<string, any>>;
  harmonic_results: Array<Record<string, any>>;
  transformer_thermal_results: Array<Record<string, any>>;
  n_minus_one_results: Array<Record<string, any>>;
  island_results: Array<Record<string, any>>;
  charging_queue_results: Array<Record<string, any>>;
  storage_warranty_results: Array<Record<string, any>>;
  gates: Array<Record<string, any>>;
  assurance: Record<string, any>;
  production_boundary: Record<string, boolean>;
  input_evidence_sha256: string | null;
  evidence_sha256: string;
}

export interface AlgorithmProductionQualificationReport {
  schema_version: string;
  report_id: string;
  mode: string;
  status: string;
  source_readiness: Record<string, any>;
  qualification_summary: Record<string, any>;
  multi_seed_cross_season: Record<string, any>;
  probabilistic_forecast: Record<string, any>;
  ood_monitoring: Record<string, any>;
  explainability: Record<string, any>;
  action_reachability: Record<string, any>;
  realtime_performance: Record<string, any>;
  fault_campaign: Record<string, any>;
  human_oversight: Record<string, any>;
  champion_challenger: Record<string, any>;
  known_offline_evidence: Record<string, any>;
  gates: Array<Record<string, any>>;
  assurance: Record<string, any>;
  production_boundary: Record<string, boolean>;
  input_evidence_sha256: string | null;
  evidence_sha256: string;
}

export interface OperationalAlert {
  code: string;
  severity: 'critical' | 'warning' | 'info' | string;
  title_zh: string;
  title_en: string;
  detail_zh: string;
  detail_en: string;
  source: string;
  value: number | null;
  threshold: number | null;
}

export interface CarbonMarket {
  carbon_price_cny_per_ton: number;
  quota_ton: number;
  emission_ton: number;
  baseline_emission_ton: number;
  quota_gap_ton: number;
  baseline_quota_gap_ton: number;
  carbon_cost_cny: number;
  baseline_carbon_cost_cny: number;
  carbon_cost_saving_cny: number;
  abatement_ton: number;
  abatement_value_cny: number;
  quota_utilization_rate: number;
  baseline_quota_utilization_rate: number;
  optimized_total_cost_cny: number;
  baseline_total_cost_cny: number;
  total_cost_saving_cny: number;
  optimization_advice: string;
  quota_basis: string;
  price_basis: string;
}

export interface TimeSeriesPoint {
  time: string;
  traditional_carbon_kg: number;
  marl_carbon_kg: number;
  traditional_energy_kwh: number;
  marl_energy_kwh: number;
}

export interface RlRewardTracePoint {
  step: number;
  reward: number;
  carbon_penalty: number;
  delay_penalty: number;
  energy_penalty: number;
  shore_power_bonus: number;
}

export interface RlEnvironmentSummary {
  status: string;
  environment_id: string;
  dataset_id: string;
  dataset_path: string;
  dataset_sha256: string;
  action_policy: string;
  episode_steps: number;
  total_reward: number;
  average_reward: number;
  terminated: boolean;
  truncated: boolean;
  observation_keys: string[];
  reward_trace: RlRewardTracePoint[];
}

export interface DashboardSnapshot {
  scenario_id: string;
  green_preference: number;
  kpis: KpiCard[];
  strategies: StrategyComparisonRow[];
  carbon_market: CarbonMarket;
  carbon_model: CarbonModelSummary;
  carbon_inventory: PortEmissionsInventory;
  measurement_verification: MeasurementVerificationReport;
  carbon_assets: CarbonAssetComplianceReport;
  commercial_settlement: CommercialSettlementReport;
  port_collaboration: PortCollaborationReport;
  enterprise_security: EnterpriseSecurityReport;
  energy_carbon_management: EnergyCarbonManagementReport;
  operations_energy_plan: OperationsEnergyPlanningReport;
  electrical_network: ElectricalNetworkAssessmentReport;
  algorithm_production: AlgorithmProductionQualificationReport;
  site_cutover_readiness: SiteCutoverReport;
  timeseries: TimeSeriesPoint[];
  rl_environment: RlEnvironmentSummary;
  data_quality: Record<string, any>;
  data_drift: Record<string, any>;
  alerts: OperationalAlert[];
  governance: Record<string, any>;
}
