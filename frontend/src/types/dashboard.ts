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
  timeseries: TimeSeriesPoint[];
  rl_environment: RlEnvironmentSummary;
  data_quality: Record<string, any>;
  data_drift: Record<string, any>;
  alerts: OperationalAlert[];
  governance: Record<string, any>;
}
