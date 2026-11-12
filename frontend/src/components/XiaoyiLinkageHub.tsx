import { useEffect, useMemo, useRef, useState } from 'react';
import { fetchJson } from '../lib/api';
import {
  Activity,
  Bot,
  CheckCircle2,
  CircleAlert,
  Gauge,
  ListChecks,
  Pause,
  Play,
  Radio,
  RotateCw,
  Send,
  ServerCog,
  ShieldCheck,
  ShipWheel,
  SlidersHorizontal,
  Sparkles,
  Square,
  X,
} from 'lucide-react';

type JsonMap = Record<string, any>;
type JsonRequestInit = Omit<RequestInit, 'body'> & { body?: unknown; timeoutMs?: number };

interface PendingPacket {
  action?: JsonMap;
  will_execute?: JsonMap;
  human_confirmation?: JsonMap;
  execution_result?: JsonMap;
  recommendation?: JsonMap | null;
  matched?: boolean;
}

interface LogItem {
  id: number;
  time: string;
  kind: string;
  message: string;
}

type ExecutionStatus = 'idle' | 'thinking' | 'pending_confirmation' | 'executing' | 'completed' | 'failed';
type AutomationMode = 'idle' | 'manual' | 'xiaoyi';
type StageModalKind = 'info' | 'ok' | 'confirm' | 'running' | 'done';

interface ExecutionDetail {
  actionId: string;
  label: string;
  group: string;
  instruction: string;
  buttonLabel: string;
  apiMethod: string;
  apiPath: string;
  confirmationRequired: boolean;
  status: ExecutionStatus;
  statusLabel: string;
  resultSummary: string;
  resultCode: string;
  updatedAt: string;
}

interface AutomationStep {
  id: string;
  label: string;
  detail: string;
}

type ClickStepStatus = 'pending' | 'locating' | 'clicking' | 'done' | 'failed';

interface ClickSequenceStep {
  selector: string;
  label: string;
  status: ClickStepStatus;
}

interface StageModalState {
  kind: StageModalKind;
  stepIndex: number;
  eyebrow: string;
  title: string;
  description: string;
  details: Array<{ label: string; value: string }>;
  progress: number;
  progressLabel: string;
}

type TopPanelId = 'runtime' | 'simulation' | 'marl' | 'carbon' | 'shore' | 'api';

interface XiaoyiLinkageHubProps {
  currentGreenPreference?: number;
  currentCarbonPrice?: number;
  externalOpenToken?: number;
  externalTrainingToken?: number;
  externalTrainingObjectiveId?: string;
  externalCommandToken?: number;
  externalCommandText?: string;
  onSetGreenPreference?: (value: number, label: string) => void;
  onSyncDashboard?: (reason?: string) => Promise<void> | void;
  onOpenTopPanel?: (panel: TopPanelId) => Promise<void> | void;
  onRunApiCheck?: () => Promise<void> | void;
}

interface CommandCatalogItem {
  id: string;
  label: string;
  command: string;
  group: string;
  buttonId?: string;
}

interface CommandShortcutItem {
  id: string;
  label: string;
  group: string;
  command: string;
  actionId: string;
  description: string;
  objectiveId?: string;
  badge?: string;
}

interface TrainingObjective {
  id: string;
  label: string;
  command: string;
  algorithm: string;
  totalSteps: number;
  horizonMin: number;
  rewardWeights: Record<string, number>;
  reason: string;
}

interface RlAlgorithmOption {
  id: string;
  label: string;
  tag: string;
  description: string;
  defaults: {
    total_steps: number;
    batch_size: number;
    learning_rate: number;
    gamma: number;
    tau: number;
    entropy_coef: number;
  };
}

interface TrainingParams {
  algorithm: string;
  data_file: string;
  scenario: string;
  asset_group: string;
  horizon_min: number;
  step_min: number;
  total_steps: number;
  batch_size: number;
  learning_rate: number;
  gamma: number;
  tau: number;
  entropy_coef: number;
  guardrail_mode: string;
  seed: number;
  eval_interval: number;
  checkpoint_interval: number;
  reward_weights: Record<string, number>;
}

type NumericTrainingParamKey = {
  [K in keyof TrainingParams]: TrainingParams[K] extends number ? K : never;
}[keyof TrainingParams];

interface TrainingDataFile {
  id: string;
  label: string;
  path: string;
  scenario: string;
  assetGroup: string;
  description: string;
}

const trainingObjectives = [
  {
    id: 'carbon_min',
    label: '碳排最低目标',
    command: '小鸥，开始训练碳排最低目标',
    algorithm: 'sac',
    totalSteps: 220000,
    horizonMin: 720,
    rewardWeights: { carbon: 0.42, shore_power: 0.24, cost: 0.14, delay: 0.0, safety: 0.20, peak: 0.0, storage: 0.08 },
    reason: '优先压低碳排并保留安全护栏。',
  },
  {
    id: 'cost_carbon_balance',
    label: '成本与碳排均衡',
    command: '小鸥，开始训练成本与碳排均衡目标',
    algorithm: 'td3',
    totalSteps: 180000,
    horizonMin: 540,
    rewardWeights: { carbon: 0.30, shore_power: 0.0, cost: 0.32, delay: 0.18, safety: 0.20, peak: 0.0, storage: 0.08 },
    reason: '用双评论家和延迟策略更新学习连续资源配比。',
  },
  {
    id: 'shore_power_priority',
    label: '岸电优先目标',
    command: '小鸥，开始训练岸电优先目标',
    algorithm: 'sac',
    totalSteps: 200000,
    horizonMin: 720,
    rewardWeights: { carbon: 0.24, shore_power: 0.44, cost: 0.0, delay: 0.12, safety: 0.20, peak: 0.0, storage: 0.08 },
    reason: '优先把靠泊窗口和岸电窗口匹配起来。',
  },
  {
    id: 'peak_smoothing',
    label: '峰值负荷平滑',
    command: '小鸥，开始训练峰值负荷平滑目标',
    algorithm: 'ppo',
    totalSteps: 160000,
    horizonMin: 360,
    rewardWeights: { carbon: 0.18, shore_power: 0.0, cost: 0.20, delay: 0.0, safety: 0.22, peak: 0.40, storage: 0.08 },
    reason: '削减岸电和设备作业叠加峰值。',
  },
  {
    id: 'low_risk_validation',
    label: '低风险试运行',
    command: '小鸥，开始训练低风险试运行目标',
    algorithm: 'ppo',
    totalSteps: 90000,
    horizonMin: 240,
    rewardWeights: { carbon: 0.22, shore_power: 0.0, cost: 0.18, delay: 0.18, safety: 0.42, peak: 0.0, storage: 0.08 },
    reason: 'v6 使用连续残差策略与硬约束投影；PPO 用于低风险连续策略对照，DQN 仅保留给 v1–v5 历史环境。',
  },
] satisfies TrainingObjective[];

const rlAlgorithms: RlAlgorithmOption[] = [
  {
    id: 'mpc',
    label: 'MPC 模型预测控制',
    tag: 'Control Baseline',
    description: '控制理论基线：四步有限时域内对可行岸电、装卸资源与储能组合做约束束搜索，不拟合神经网络。',
    defaults: { total_steps: 0, batch_size: 1, learning_rate: 0, gamma: 1, tau: 0, entropy_coef: 0 },
  },
  {
    id: 'ppo',
    label: 'PPO',
    tag: 'On-policy',
    description: '适合峰值负荷平滑和约束型调度的同策略算法。',
    defaults: { total_steps: 160000, batch_size: 256, learning_rate: 0.00025, gamma: 0.995, tau: 0.005, entropy_coef: 0.01 },
  },
  {
    id: 'sac',
    label: 'SAC',
    tag: 'Continuous',
    description: '适合连续权重调度，常用于低碳、岸电和资源配比联合优化。',
    defaults: { total_steps: 220000, batch_size: 256, learning_rate: 0.0003, gamma: 0.995, tau: 0.005, entropy_coef: 0 },
  },
  {
    id: 'td3',
    label: 'TD3',
    tag: 'Continuous',
    description: '连续动作强化学习：双评论家抑制过高估计，延迟策略更新提高稳定性。',
    defaults: { total_steps: 180000, batch_size: 256, learning_rate: 0.001, gamma: 0.99, tau: 0.005, entropy_coef: 0 },
  },
  {
    id: 'dqn',
    label: 'DQN',
    tag: 'Discrete',
    description: '离散动作强化学习：v1–v3 为 81 个组合，v4 为 729 个组合，v5 为 243 个覆盖十类资源包络的策划模板。',
    defaults: { total_steps: 120000, batch_size: 128, learning_rate: 0.0001, gamma: 0.99, tau: 0, entropy_coef: 0 },
  },
];

const trainingDataFiles: TrainingDataFile[] = [
  { id: 'port_la_2020_2024_hybrid_rl_hourly', label: 'v6 分层混合智能公开锚点集', path: 'port_la_2020_2024_hybrid_rl_hourly', scenario: 'port_la_hybrid_rl_benchmark', assetGroup: 'vessel_berth_crane_yard_truck_energy_maintenance', description: '43,848小时公开船舶/吞吐/电网锚点 + 明示的可替换工程情景；106维因果观测、10个有界控制残差、6个运筹优先级。现场接入时按同列合同替换，不冒充生产遥测。' },
  { id: 'port_la_2020_2024_operational_flex_hourly', label: 'v5 全业务柔性调度公开锚点集', path: 'port_la_2020_2024_operational_flex_hourly', scenario: 'port_la_operational_flex_benchmark', assetGroup: 'shore_crane_yard_storage_regulatory_agv_reefer_building_dr', description: '43,848小时公开船舶/吞吐/电网锚点 + 可替换的自动导引车、冷藏箱、楼宇、需求响应、设备健康、预约与监管工程情景；73维观测、10维动作，补足字段不冒充现场遥测。' },
  { id: 'port_la_2020_2024_vessel_activity_hourly', label: '洛杉矶港官方逐日船舶活动增强集', path: 'port_la_2020_2024_vessel_activity_hourly', scenario: 'port_la_vessel_activity_benchmark', assetGroup: 'berth_shore_power_yard_truck', description: '43,848小时能碳序列 + 1,238条港方逐日船舶活动记录；2020–2022训练、2023验证、2024测试，非报告日明确标记为插值。' },
  { id: 'port_la_2020_2025_hourly', label: '洛杉矶港 × EIA 2020–2025 小时基准', path: 'port_la_2020_2025_hourly', scenario: 'port_la_public_benchmark', assetGroup: 'berth_shore_power_yard_truck', description: '洛杉矶港72个月度TEU锚点 + EIA LADWP 52,608小时电力/碳信号；2020–2023训练、2024验证、2025测试，源数据覆盖率98.32%。' },
];

const rewardWeightLabels: Record<string, string> = {
  carbon: '碳排',
  shore_power: '岸电',
  cost: '成本',
  delay: '延误',
  safety: '安全',
  peak: '峰值',
  storage: '储能终端 SOC',
  agv_service: '自动导引车充电履约',
  reefer_safety: '冷藏箱热安全',
  demand_response: '需求响应交付',
  equipment_health: '设备健康保护',
  jit_service: '准时到港',
  green_berth: '绿色泊位',
  crane_schedule: '岸桥任务排序',
  yard_slotting: '堆场箱位',
  truck_flow: '集卡闸口',
  maintenance_risk: '预测性检修',
};

const legacyRewardWeightKeys = new Set(['carbon', 'shore_power', 'cost', 'delay', 'safety', 'peak', 'storage']);
const flexRewardDefaults: Record<string, number> = {
  agv_service: 0.06,
  reefer_safety: 0.07,
  demand_response: 0.05,
  equipment_health: 0.03,
};
const flexRewardWeightKeys = new Set([
  ...legacyRewardWeightKeys,
  ...Object.keys(flexRewardDefaults),
]);
const hybridRewardDefaults: Record<string, number> = {
  carbon: 0.12,
  shore_power: 0.04,
  cost: 0.12,
  delay: 0.10,
  safety: 0.18,
  peak: 0.06,
  storage: 0.04,
  agv_service: 0.05,
  reefer_safety: 0.06,
  demand_response: 0.04,
  equipment_health: 0.03,
  jit_service: 0.035,
  green_berth: 0.025,
  crane_schedule: 0.025,
  yard_slotting: 0.025,
  truck_flow: 0.025,
  maintenance_risk: 0.025,
};
const hybridRewardWeightKeys = new Set(Object.keys(hybridRewardDefaults));

const hybridStateContract = [
  ['19维', '能源与因果预测', '负荷、岸电、储能、电价与碳强度'],
  ['6维', '船舶作业', '到港、靠泊、吞吐与延误状态'],
  ['10维', '气象与资产可用性', '风、温度、设备健康与检修窗口'],
  ['13维', '监管与安全', '碳配额、安全边界与服务约束'],
  ['25维', '灵活作业', 'AGV、冷藏箱、楼宇、需求响应与设备健康'],
  ['33维', '混合调度状态', '船—泊—桥—场—车—能—检修跨时段状态'],
] as const;

const hybridActionContract = [
  ['10维连续残差', '岸电、岸桥、堆场、储能、检查准备、恢复优先级、AGV充电、冷藏箱服务、楼宇灵活负荷、需求响应'],
  ['6维运筹优先级', '准时到港、绿色泊位、岸桥任务、堆场箱位、集卡闸口、预测性检修'],
] as const;

function alignRewardWeightsForDataset(
  weights: Record<string, number>,
  datasetId: string,
) {
  if (datasetId === 'port_la_2020_2024_hybrid_rl_hourly') {
    return Object.fromEntries(
      Object.entries({ ...hybridRewardDefaults, ...weights })
        .filter(([key]) => hybridRewardWeightKeys.has(key))
        .map(([key, value]) => [key, Number(value)]),
    );
  }
  if (datasetId === 'port_la_2020_2024_operational_flex_hourly') {
    return Object.fromEntries(
      Object.entries({ ...flexRewardDefaults, ...weights })
        .filter(([key]) => flexRewardWeightKeys.has(key))
        .map(([key, value]) => [key, Number(value)]),
    );
  }
  return Object.fromEntries(
    Object.entries(weights).filter(([key]) => legacyRewardWeightKeys.has(key)),
  );
}

const trainingParamFields: Array<{ key: NumericTrainingParamKey; label: string; min: number; max?: number; step: string }> = [
  { key: 'total_steps', label: '训练总步数', min: 0, max: 5000000, step: '1000' },
  { key: 'horizon_min', label: '训练 horizon(min)', min: 240, max: 1440, step: '60' },
  { key: 'batch_size', label: 'batch size', min: 1, max: 1024, step: '1' },
  { key: 'learning_rate', label: 'learning rate', min: 0, max: 0.01, step: '0.00001' },
  { key: 'gamma', label: 'gamma', min: 0.8, max: 1, step: '0.001' },
  { key: 'tau', label: 'tau', min: 0, max: 0.05, step: '0.001' },
  { key: 'entropy_coef', label: 'entropy coef', min: 0, max: 0.1, step: '0.001' },
  { key: 'seed', label: '随机种子', min: 1, max: 99999999, step: '1' },
  { key: 'eval_interval', label: '评估间隔 step', min: 100, max: 100000, step: '100' },
  { key: 'checkpoint_interval', label: '检查点间隔 step', min: 1000, max: 200000, step: '1000' },
];

function createTrainingParams(profile: TrainingObjective): TrainingParams {
  const algorithm = rlAlgorithms.find((item) => item.id === profile.algorithm) ?? rlAlgorithms[0];
  const dataFile = trainingDataFiles[0];
  return {
    algorithm: profile.algorithm,
    data_file: dataFile.path,
    scenario: dataFile.scenario,
    asset_group: dataFile.assetGroup,
    horizon_min: profile.horizonMin,
    step_min: 60,
    total_steps: profile.totalSteps,
    batch_size: algorithm.defaults.batch_size,
    learning_rate: algorithm.defaults.learning_rate,
    gamma: algorithm.defaults.gamma,
    tau: algorithm.defaults.tau,
    entropy_coef: algorithm.defaults.entropy_coef,
    guardrail_mode: 'strict',
    seed: 20260720,
    eval_interval: 5000,
    checkpoint_interval: 20000,
    reward_weights: alignRewardWeightsForDataset(profile.rewardWeights, dataFile.id),
  };
}

function displayNumber(value: number) {
  if (Number.isInteger(value) && Math.abs(value) >= 1000) {
    return value.toLocaleString('zh-CN');
  }
  return String(value);
}

function formatTrainingDuration(value: unknown) {
  const seconds = Number(value);
  if (!Number.isFinite(seconds) || seconds <= 0) return '等待启动';
  const rounded = Math.max(0, Math.round(seconds));
  const hours = Math.floor(rounded / 3600);
  const minutes = Math.floor((rounded % 3600) / 60);
  const secs = rounded % 60;
  if (hours > 0) return `${hours}h ${String(minutes).padStart(2, '0')}m`;
  if (minutes > 0) return `${minutes}m ${String(secs).padStart(2, '0')}s`;
  return `${secs}s`;
}

function formatTrainingTime(value: unknown) {
  if (!value) return '等待启动';
  const date = new Date(String(value));
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function resolveAlgorithmProfile(algorithmId: string) {
  return rlAlgorithms.find((item) => item.id === algorithmId) ?? rlAlgorithms[0];
}

function resolveDataFileProfile(path: string) {
  return trainingDataFiles.find((item) => item.path === path) ?? {
    id: 'custom_csv',
    label: '自定义港口 CSV',
    path,
    scenario: '',
    assetGroup: '',
    description: '后端会在启动前校验列、数值、train/test 分区和数据集哈希。',
  };
}

function buildTrainingDraftConfig(profile: TrainingObjective, params: TrainingParams) {
  const algorithm = resolveAlgorithmProfile(params.algorithm);
  const dataFile = resolveDataFileProfile(params.data_file);
  return {
    objective_id: profile.id,
    objective_label: profile.label,
    objective_reason: profile.reason,
    algorithm: params.algorithm,
    algorithm_label: algorithm.label,
    algorithm_tag: algorithm.tag,
    data_file: params.data_file,
    data_label: dataFile.label,
    data_description: dataFile.description,
    scenario: params.scenario,
    asset_group: params.asset_group,
    horizon_min: Number(params.horizon_min),
    step_min: Number(params.step_min),
    total_steps: Number(params.total_steps),
    batch_size: Number(params.batch_size),
    learning_rate: Number(params.learning_rate),
    gamma: Number(params.gamma),
    tau: Number(params.tau),
    entropy_coef: Number(params.entropy_coef),
    guardrail_mode: params.guardrail_mode,
    seed: Number(params.seed),
    eval_interval: Number(params.eval_interval),
    checkpoint_interval: Number(params.checkpoint_interval),
    reward_weights: { ...params.reward_weights },
    reason: profile.reason,
    risk_controls: ['人工确认后启动训练', '策略产物仅进入 dry-run 验证', '上线前必须通过安全约束校验'],
    source: 'energy_carbon_cockpit',
  };
}

function buildTrainingRiskWarnings(params: TrainingParams) {
  const weights = params.reward_weights;
  const rewardTotal = Object.values(weights).reduce((sum, value) => sum + Number(value || 0), 0);
  const warnings = ['训练会占用本地 RL 训练进程与计算资源；当前策略产物不会直接生产下发。'];
  if (params.algorithm === 'mpc') {
    warnings.push('MPC 是控制理论基线，每步滚动求解而不拟合神经网络。');
  }
  if (params.total_steps >= 200000) {
    warnings.push('训练步数较高，建议先用 dry-run 确认数据、超参数和计算资源。');
  }
  if (Number(weights.safety ?? 0) < 0.2) {
    warnings.push('安全权重低于 0.20，可能弱化泊位/岸电/设备安全约束。');
  }
  if (Number(weights.peak ?? 0) > 0.35) {
    warnings.push('峰值负荷权重较高，可能牺牲部分船期效率以换取削峰。');
  }
  if (rewardTotal > 1.2) {
    warnings.push('奖励权重总和偏高，建议确认各目标之间不会互相拉扯。');
  }
  if (params.guardrail_mode !== 'strict') {
    warnings.push('护栏不是 strict，必须在上线验证中再次确认安全边界。');
  }
  return warnings;
}

const commandCatalog: CommandCatalogItem[] = [
  { id: 'open_runtime_panel', label: '打开实时闭环', command: '小鸥，打开实时闭环面板', group: '实时闭环', buttonId: 'btnXiaoyiOpenRuntimePanel' },
  { id: 'summarize_runtime_state', label: '总结实时态势', command: '小鸥，总结当前实时态势', group: '实时闭环', buttonId: 'btnXiaoyiRuntimeSummary' },
  { id: 'prepare_runtime_handover', label: '生成交班摘要', command: '小鸥，生成实时交班摘要', group: '实时闭环', buttonId: 'btnXiaoyiRuntimeHandover' },
  { id: 'triage_runtime_alerts', label: '研判实时异常', command: '小鸥，研判当前实时异常', group: '实时闭环', buttonId: 'btnXiaoyiRuntimeTriage' },
  { id: 'create_runtime_recommendation', label: '生成运行建议', command: '小鸥，生成当前运行建议', group: '实时闭环', buttonId: 'btnXiaoyiRuntimeRecommend' },
  { id: 'explain_runtime_recommendation', label: '解释最新建议', command: '小鸥，解释最新运行建议', group: '实时闭环', buttonId: 'btnXiaoyiRuntimeExplain' },
  { id: 'open_simulation_panel', label: '打开仿真面板', command: '小鸥，打开仿真在线面板', group: 'AI决策面板', buttonId: 'btnXiaoyiOpenSimulationPanel' },
  { id: 'open_marl_panel', label: '打开 RL 面板', command: '小鸥，打开 RL 策略面板', group: 'AI决策面板', buttonId: 'btnXiaoyiOpenMarlPanel' },
  { id: 'open_carbon_panel', label: '打开低碳面板', command: '小鸥，打开低碳优先面板', group: 'AI决策面板', buttonId: 'btnXiaoyiOpenCarbonPanel' },
  { id: 'open_shore_panel', label: '打开岸电面板', command: '小鸥，打开岸电联动面板', group: 'AI决策面板', buttonId: 'btnXiaoyiOpenShorePanel' },
  { id: 'open_api_panel', label: '打开 API 面板', command: '小鸥，打开 API 同步面板', group: 'AI决策面板', buttonId: 'btnXiaoyiOpenApiPanel' },
  { id: 'refresh_dashboard_snapshot', label: '刷新仿真', command: '小鸥，刷新仿真并重新同步仪表盘', group: 'AI决策面板', buttonId: 'btnXiaoyiRefreshDashboard' },
  { id: 'run_linkage_health_check', label: '健康检查', command: '小鸥，做一次联动健康检查', group: 'AI决策面板', buttonId: 'btnXiaoyiHealthCheck' },
  { id: 'check_sailing_status', label: '检查模拟器', command: '小鸥，检查航行模拟器状态', group: 'AI决策面板', buttonId: 'btnXiaoyiCheckSailingStatus' },
  { id: 'set_efficiency_priority', label: '效率优先', command: '小鸥，切到效率优先', group: '调度偏好', buttonId: 'btnXiaoyiPreferenceEfficiency' },
  { id: 'set_balanced_dispatch', label: '均衡调度', command: '小鸥，切到均衡调度', group: '调度偏好', buttonId: 'btnXiaoyiPreferenceBalanced' },
  { id: 'set_low_carbon_priority', label: '低碳优先', command: '小鸥，切到低碳优先', group: '调度偏好', buttonId: 'btnXiaoyiPreferenceLowCarbon' },
  { id: 'set_shore_power_preference', label: '岸电优先', command: '小鸥，切到岸电优先', group: '调度偏好', buttonId: 'btnXiaoyiPreferenceShorePower' },
  { id: 'start_xiaoyi_ai', label: '启动舷鸥 · GullMate', command: '小鸥，启动舷鸥 · GullMate', group: '舷鸥/RL/模拟器', buttonId: 'btnXiaoyiStart' },
  { id: 'start_rl_training', label: '启动 RL 训练', command: '小鸥，开始训练碳排最低目标', group: '舷鸥/RL/模拟器', buttonId: 'btnStartTraining' },
  { id: 'view_rl_training_status', label: '查看训练状态', command: '小鸥，查看训练状态', group: '舷鸥/RL/模拟器', buttonId: 'btnTrainingStatus' },
  { id: 'pause_rl_training', label: '暂停 RL 训练', command: '小鸥，暂停训练', group: '舷鸥/RL/模拟器', buttonId: 'btnPauseTraining' },
  { id: 'resume_rl_training', label: '继续 RL 训练', command: '小鸥，继续训练', group: '舷鸥/RL/模拟器', buttonId: 'btnPauseTraining' },
  { id: 'stop_rl_training', label: '停止 RL 训练', command: '小鸥，停止训练', group: '舷鸥/RL/模拟器', buttonId: 'btnStopTraining' },
  { id: 'run_policy_test', label: '读取登记策略测试', command: '小鸥，读取训练后登记策略测试', group: '舷鸥/RL/模拟器', buttonId: 'btnPolicyTest' },
  { id: 'verify_policy_for_online', label: '上线验证 dry-run', command: '小鸥，验证这个策略能不能上线', group: '舷鸥/RL/模拟器', buttonId: 'btnVerifyPolicy' },
  { id: 'open_sailing_simulator', label: '启动航行模拟器', command: '小鸥，启动航行模拟器', group: '舷鸥/RL/模拟器', buttonId: 'btnSailingLaunch' },
  { id: 'start_navigation_demo', label: '启动航线演示', command: '小鸥，启动航线演示', group: '舷鸥/RL/模拟器', buttonId: 'btnSailingDemo' },
  { id: 'switch_ship_view', label: '切换船舶视角', command: '小鸥，切换船舶视角', group: '舷鸥/RL/模拟器', buttonId: 'btnShipView' },
  { id: 'run_sailing_rl_smoke_test', label: '运行 smoke test', command: '小鸥，运行航行 smoke test', group: '舷鸥/RL/模拟器', buttonId: 'btnSailingSmoke' },
];

const clickableActions = new Set(commandCatalog.map((item) => item.id));

const preferenceActions: Record<string, { value: number; label: string; panel: TopPanelId }> = {
  set_efficiency_priority: { value: 0.25, label: '效率优先', panel: 'carbon' },
  set_balanced_dispatch: { value: 0.5, label: '均衡调度', panel: 'carbon' },
  set_low_carbon_priority: { value: 0.82, label: '低碳优先', panel: 'carbon' },
  set_shore_power_preference: { value: 0.88, label: '岸电优先', panel: 'shore' },
};

const topPanelActions: Record<string, TopPanelId> = {
  open_runtime_panel: 'runtime',
  open_simulation_panel: 'simulation',
  open_marl_panel: 'marl',
  open_carbon_panel: 'carbon',
  open_shore_panel: 'shore',
  open_api_panel: 'api',
};

const actionContracts: Record<string, { method: string; path: string; confirmationRequired: boolean }> = {
  open_runtime_panel: { method: 'LOCAL', path: 'front-end:open-top-panel', confirmationRequired: false },
  summarize_runtime_state: { method: 'POST', path: '/api/assistant/actions/execute', confirmationRequired: false },
  prepare_runtime_handover: { method: 'POST', path: '/api/assistant/actions/execute', confirmationRequired: false },
  triage_runtime_alerts: { method: 'POST', path: '/api/assistant/actions/execute', confirmationRequired: false },
  create_runtime_recommendation: { method: 'POST', path: '/api/runtime/decisions', confirmationRequired: true },
  explain_runtime_recommendation: { method: 'POST', path: '/api/assistant/actions/execute', confirmationRequired: false },
  open_simulation_panel: { method: 'LOCAL', path: 'front-end:open-top-panel', confirmationRequired: false },
  open_marl_panel: { method: 'LOCAL', path: 'front-end:open-top-panel', confirmationRequired: false },
  open_carbon_panel: { method: 'LOCAL', path: 'front-end:open-top-panel', confirmationRequired: false },
  open_shore_panel: { method: 'LOCAL', path: 'front-end:open-top-panel', confirmationRequired: false },
  open_api_panel: { method: 'LOCAL', path: 'front-end:open-top-panel', confirmationRequired: false },
  refresh_dashboard_snapshot: { method: 'POST', path: '/api/optimization/recompute', confirmationRequired: false },
  run_linkage_health_check: { method: 'GET', path: '/api/linkage/health', confirmationRequired: false },
  check_sailing_status: { method: 'GET', path: '/api/sailing/status', confirmationRequired: false },
  set_efficiency_priority: { method: 'POST', path: '/api/optimization/recompute', confirmationRequired: false },
  set_balanced_dispatch: { method: 'POST', path: '/api/optimization/recompute', confirmationRequired: false },
  set_low_carbon_priority: { method: 'POST', path: '/api/optimization/recompute', confirmationRequired: false },
  set_shore_power_preference: { method: 'POST', path: '/api/optimization/recompute', confirmationRequired: false },
  start_xiaoyi_ai: { method: 'POST', path: '/api/xiaoyi/launch', confirmationRequired: true },
  start_rl_training: { method: 'POST', path: '/api/rl/train/start', confirmationRequired: true },
  view_rl_training_status: { method: 'GET', path: '/api/rl/train/status', confirmationRequired: false },
  pause_rl_training: { method: 'POST', path: '/api/rl/train/pause', confirmationRequired: false },
  resume_rl_training: { method: 'POST', path: '/api/rl/train/resume', confirmationRequired: false },
  stop_rl_training: { method: 'POST', path: '/api/rl/train/stop', confirmationRequired: false },
  run_policy_test: { method: 'GET', path: '/api/rl/registry', confirmationRequired: false },
  verify_policy_for_online: { method: 'POST', path: '/api/rlops/policies/verify + /api/rl/dispatch', confirmationRequired: false },
  open_sailing_simulator: { method: 'POST', path: '/api/sailing/launch', confirmationRequired: true },
  start_navigation_demo: { method: 'POST', path: '/api/sailing/actions/execute', confirmationRequired: true },
  switch_ship_view: { method: 'POST', path: '/api/sailing/actions/execute', confirmationRequired: true },
  run_sailing_rl_smoke_test: { method: 'POST', path: '/api/sailing/actions/execute', confirmationRequired: true },
};

const actionPreludeSteps: Record<string, Array<{ selector: string; label: string }>> = {
  create_runtime_recommendation: [{ selector: '#btnXiaoyiOpenRuntimePanel', label: '打开实时闭环面板 / Open runtime panel' }],
  refresh_dashboard_snapshot: [{ selector: '#btnXiaoyiOpenApiPanel', label: '打开 API 同步面板 / Open API panel' }],
  run_linkage_health_check: [{ selector: '#btnXiaoyiOpenApiPanel', label: '打开 API 同步面板 / Open API panel' }],
  check_sailing_status: [{ selector: '#btnXiaoyiOpenSimulationPanel', label: '打开仿真在线面板 / Open simulation panel' }],
  set_efficiency_priority: [{ selector: '#btnXiaoyiOpenCarbonPanel', label: '打开低碳决策面板 / Open carbon panel' }],
  set_balanced_dispatch: [{ selector: '#btnXiaoyiOpenCarbonPanel', label: '打开低碳决策面板 / Open carbon panel' }],
  set_low_carbon_priority: [{ selector: '#btnXiaoyiOpenCarbonPanel', label: '打开低碳决策面板 / Open carbon panel' }],
  set_shore_power_preference: [{ selector: '#btnXiaoyiOpenShorePanel', label: '打开岸电联动面板 / Open shore-power panel' }],
  view_rl_training_status: [{ selector: '#btnXiaoyiOpenMarlPanel', label: '打开 RL 策略面板 / Open RL panel' }],
  pause_rl_training: [{ selector: '#btnXiaoyiOpenMarlPanel', label: '打开 RL 策略面板 / Open RL panel' }],
  resume_rl_training: [{ selector: '#btnXiaoyiOpenMarlPanel', label: '打开 RL 策略面板 / Open RL panel' }],
  stop_rl_training: [{ selector: '#btnXiaoyiOpenMarlPanel', label: '打开 RL 策略面板 / Open RL panel' }],
  run_policy_test: [{ selector: '#btnXiaoyiOpenMarlPanel', label: '打开 RL 策略面板 / Open RL panel' }],
  verify_policy_for_online: [{ selector: '#btnXiaoyiOpenMarlPanel', label: '打开 RL 策略面板 / Open RL panel' }],
  open_sailing_simulator: [{ selector: '#btnXiaoyiOpenSimulationPanel', label: '打开仿真在线面板 / Open simulation panel' }],
};

function now() {
  return new Date().toLocaleTimeString('zh-CN', { hour12: false });
}

function pretty(data: unknown) {
  return JSON.stringify(data, null, 2);
}

function wait(ms: number) {
  return new Promise((resolve) => {
    window.setTimeout(resolve, ms);
  });
}

function chartPoints(series: JsonMap[], key: string, width = 520, height = 150, padding = 12) {
  const points = series.flatMap((item, index) => {
    const value = item[key];
    return typeof value === 'number' && Number.isFinite(value) ? [{ value, index }] : [];
  });
  if (!points.length) return '';
  const minimum = Math.min(...points.map((item) => item.value));
  const maximum = Math.max(...points.map((item) => item.value));
  const range = Math.max(0.0001, maximum - minimum);
  return points.map(({ value, index }) => {
    const x = padding + index / Math.max(1, series.length - 1) * (width - padding * 2);
    const y = maximum === minimum
      ? height / 2
      : height - padding - (value - minimum) / range * (height - padding * 2);
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(' ');
}

function chartAreaPoints(series: JsonMap[], key: string, width = 760, height = 230, padding = 18) {
  const line = chartPoints(series, key, width, height, padding);
  return line ? `${padding},${height - padding} ${line} ${width - padding},${height - padding}` : '';
}

function compactMetric(value: unknown, digits = 3) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return '—';
  return numeric.toFixed(digits).replace(/0+$/, '').replace(/\.$/, '');
}

async function api(path: string, options: JsonRequestInit = {}) {
  return fetchJson(path, {
    ...options,
    timeoutMs: options.timeoutMs ?? 6500,
    cache: 'no-store',
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
  }) as Promise<JsonMap>;
}

let cachedTrainingHistory: JsonMap | null = null;
let trainingHistoryPromise: Promise<JsonMap> | null = null;

function loadTrainingHistoryEvidence() {
  if (cachedTrainingHistory) return Promise.resolve(cachedTrainingHistory);
  if (!trainingHistoryPromise) {
    trainingHistoryPromise = api('/api/rl/training/history', { timeoutMs: 7000 })
      .then((data) => {
        cachedTrainingHistory = data;
        return data;
      })
      .finally(() => { trainingHistoryPromise = null; });
  }
  return trainingHistoryPromise;
}

function statusLabel(data: JsonMap | null, path: string[], fallback: string) {
  let current: any = data;
  for (const key of path) {
    current = current?.[key];
  }
  return typeof current === 'string' ? current : fallback;
}

export function XiaoyiLinkageHub({
  currentGreenPreference = 0.5,
  currentCarbonPrice = 85,
  externalOpenToken = 0,
  externalTrainingToken = 0,
  externalTrainingObjectiveId = 'carbon_min',
  externalCommandToken = 0,
  externalCommandText = '',
  onSetGreenPreference,
  onSyncDashboard,
  onOpenTopPanel,
  onRunApiCheck,
}: XiaoyiLinkageHubProps) {
  const [open, setOpen] = useState(false);
  const [command, setCommand] = useState('');
  const [selectedAction, setSelectedAction] = useState('');
  const [selectedObjective, setSelectedObjective] = useState(trainingObjectives[0].id);
  const [trainingParams, setTrainingParams] = useState<TrainingParams>(() => createTrainingParams(trainingObjectives[0]));
  const [commandCenterOpen, setCommandCenterOpen] = useState(false);
  const [commandSearch, setCommandSearch] = useState('');
  const [activeCommandGroup, setActiveCommandGroup] = useState('全部');
  const [trainingStudioOpen, setTrainingStudioOpen] = useState(false);
  const [trainingReviewOpen, setTrainingReviewOpen] = useState(false);
  const [trainingHistoryOpen, setTrainingHistoryOpen] = useState(false);
  const [trainingStatusOpen, setTrainingStatusOpen] = useState(false);
  const [trainingContractOpen, setTrainingContractOpen] = useState(false);
  const [trainingHistory, setTrainingHistory] = useState<JsonMap | null>(null);
  const [trainingHistoryLoading, setTrainingHistoryLoading] = useState(false);
  const [trainingHistoryError, setTrainingHistoryError] = useState('');
  const [selectedHistoryObjective, setSelectedHistoryObjective] = useState('carbon_min');
  const [historyAutoPlay, setHistoryAutoPlay] = useState(true);
  const [automationMode, setAutomationMode] = useState<AutomationMode>('idle');
  const [automationStepIndex, setAutomationStepIndex] = useState(0);
  const [stageModal, setStageModal] = useState<StageModalState | null>(null);
  const [clickSequence, setClickSequence] = useState<ClickSequenceStep[]>([]);
  const [answer, setAnswer] = useState('');
  const [packet, setPacket] = useState('等待指令。');
  const [pendingPacket, setPendingPacket] = useState<PendingPacket | null>(null);
  const [health, setHealth] = useState<JsonMap | null>(null);
  const [trainingStatus, setTrainingStatus] = useState<JsonMap | null>(null);
  const [sailingStatus, setSailingStatus] = useState<JsonMap | null>(null);
  const [actionRegistry, setActionRegistry] = useState<JsonMap | null>(null);
  const [logs, setLogs] = useState<LogItem[]>([]);
  const [busy, setBusy] = useState(false);
  const [executionDetail, setExecutionDetail] = useState<ExecutionDetail>({
    actionId: 'idle',
    label: '等待舷鸥指令',
    group: 'AI调度',
    instruction: '等待输入或点击右侧指令清单。',
    buttonLabel: '未选择',
    apiMethod: '—',
    apiPath: '—',
    confirmationRequired: false,
    status: 'idle',
    statusLabel: 'READY',
    resultSummary: '执行详情会展示识别意图、按钮/接口、确认状态和返回结果。',
    resultCode: 'waiting',
    updatedAt: now(),
  });
  const [position, setPosition] = useState(() => ({
    x: Math.max(16, window.innerWidth - 88),
    y: Math.max(80, window.innerHeight - 108),
  }));
  const [showOrbGreeting, setShowOrbGreeting] = useState(true);
  const orbRef = useRef<HTMLButtonElement | null>(null);
  const dragRef = useRef<{ dx: number; dy: number; moved: boolean } | null>(null);
  const suppressOrbClickRef = useRef(false);
  const xiaoyiTrainingRunRef = useRef(false);
  const logSequenceRef = useRef(0);
  const actionRunningRef = useRef(false);
  const xiaoyiStartupPendingRef = useRef(false);
  const historyRequestVersionRef = useRef(0);

  useEffect(() => {
    if (externalOpenToken > 0) {
      setOpen(true);
    }
  }, [externalOpenToken]);

  useEffect(() => {
    if (externalTrainingToken > 0) {
      const profile = trainingObjectives.find((item) => item.id === externalTrainingObjectiveId) ?? trainingObjectives[0];
      setOpen(true);
      setTrainingStudioOpen(true);
      setTrainingReviewOpen(false);
      setSelectedAction('start_rl_training');
      setSelectedObjective(profile.id);
      setTrainingParams(createTrainingParams(profile));
      setCommand(profile.command);
    }
  }, [externalTrainingObjectiveId, externalTrainingToken]);

  useEffect(() => {
    if (externalCommandToken <= 0) return;
    const matchedObjective = trainingObjectives.find((item) => item.command === externalCommandText);
    setOpen(true);
    setCommand(externalCommandText);
    setSelectedAction('');
    setPendingPacket(null);
    if (matchedObjective) {
      setSelectedObjective(matchedObjective.id);
      setTrainingParams(createTrainingParams(matchedObjective));
    }
  }, [externalCommandText, externalCommandToken]);

  useEffect(() => {
    const resetDemoAction = (event: Event) => {
      const detail = (event as CustomEvent<{ stepId?: string; mode?: string }>).detail ?? {};
      const stepId = detail.stepId ?? '';
      const resetAll = detail.mode === 'all' || stepId === 'all';
      historyRequestVersionRef.current += 1;
      actionRunningRef.current = false;
      setBusy(false);
      setTrainingHistoryLoading(false);
      setTrainingHistoryError('');
      if (resetAll || stepId === 'status') setTrainingStatusOpen(false);
      if (resetAll || stepId === 'history') setTrainingHistoryOpen(false);
      if (resetAll || stepId === 'training-contract') setTrainingContractOpen(false);
      if (resetAll || detail.mode === 'skip') {
        setTrainingStudioOpen(false);
        setTrainingReviewOpen(false);
        setStageModal(null);
      } else if (stepId !== 'confirm-training') {
        setStageModal(null);
      }
      setClickSequence([]);
      setPendingPacket(null);
      if (resetAll) setAutomationMode('idle');
      setPacket('演示步骤已复位，可立即重试。');
      setAnswer('当前演示动作已释放；不会继续占用引导条。');
    };
    const completeDemo = () => {
      // Close presentation surfaces without changing the learner or audit receipts.
      setOpen(false);
      setTrainingStudioOpen(false);
      setTrainingReviewOpen(false);
      setTrainingStatusOpen(false);
      setTrainingHistoryOpen(false);
      setTrainingContractOpen(false);
      setStageModal(null);
    };
    window.addEventListener('demo-guide:complete', completeDemo);
    window.addEventListener('demo-guide:reset-action', resetDemoAction);
    return () => {
      window.removeEventListener('demo-guide:reset-action', resetDemoAction);
      window.removeEventListener('demo-guide:complete', completeDemo);
    };
  }, []);

  useEffect(() => {
    if (!trainingHistoryOpen || trainingHistoryLoading || !historyAutoPlay) return;
    const objectiveItems = Array.isArray(trainingHistory?.business_evidence?.objective_history)
      ? trainingHistory.business_evidence.objective_history as JsonMap[]
      : [];
    if (objectiveItems.length < 2) return;
    const timer = window.setInterval(() => {
      setSelectedHistoryObjective((current) => {
        const currentIndex = objectiveItems.findIndex((item) => item.id === current);
        return String(objectiveItems[(currentIndex + 1) % objectiveItems.length]?.id ?? objectiveItems[0].id);
      });
    }, 3600);
    return () => window.clearInterval(timer);
  }, [historyAutoPlay, trainingHistory, trainingHistoryLoading, trainingHistoryOpen]);

  useEffect(() => {
    const timer = window.setTimeout(() => setShowOrbGreeting(false), 5200);
    return () => window.clearTimeout(timer);
  }, []);

  useEffect(() => {
    const clampOrbToViewport = () => {
      const orbWidth = orbRef.current?.offsetWidth ?? 110;
      const orbHeight = orbRef.current?.offsetHeight ?? 150;
      setPosition((current) => ({
        x: Math.max(10, Math.min(window.innerWidth - orbWidth - 10, current.x)),
        y: Math.max(10, Math.min(window.innerHeight - orbHeight - 10, current.y)),
      }));
    };

    clampOrbToViewport();
    window.addEventListener('resize', clampOrbToViewport);
    return () => window.removeEventListener('resize', clampOrbToViewport);
  }, []);

  const objective = useMemo(
    () => trainingObjectives.find((item) => item.id === selectedObjective) ?? trainingObjectives[0],
    [selectedObjective],
  );

  const selectedAlgorithmProfile = useMemo(
    () => resolveAlgorithmProfile(trainingParams.algorithm),
    [trainingParams.algorithm],
  );

  const selectedDataFileProfile = useMemo(
    () => resolveDataFileProfile(trainingParams.data_file),
    [trainingParams.data_file],
  );

  const trainingDraftConfig = useMemo(
    () => buildTrainingDraftConfig(objective, trainingParams),
    [objective, trainingParams],
  );

  const trainingRiskWarnings = useMemo(() => buildTrainingRiskWarnings(trainingParams), [trainingParams]);

  useEffect(() => {
    const restoreTrainingConfirmation = () => {
      actionRunningRef.current = false;
      setBusy(false);
      setOpen(true);
      setTrainingStudioOpen(true);
      setTrainingReviewOpen(true);
      setAutomationMode((current) => current === 'xiaoyi' ? 'xiaoyi' : 'manual');
      setAutomationStepIndex(5);
      setStageModal({
        kind: 'confirm',
        stepIndex: 5,
        eyebrow: 'STEP 6 · 等待人工确认',
        title: '请人工确认训练信息',
        description: '确认面板已由演示保底自动恢复；请复核目标、算法、数据和风险后再启动。',
        details: [
          { label: '优化目标', value: objective.label },
          { label: '算法 / 数据', value: `${selectedAlgorithmProfile.label} / ${selectedDataFileProfile.label}` },
          { label: '人工动作', value: '请确认无误后开始训练' },
        ],
        progress: 100,
        progressLabel: '确认面板已恢复，等待人工确认',
      });
      setExecution('start_rl_training', 'pending_confirmation', objective.command, {
        resultSummary: `“${objective.label}”训练方案已恢复，等待人工确认。`,
        resultCode: pretty(trainingDraftConfig).slice(0, 900),
      });
    };
    window.addEventListener('demo-guide:restore-training-confirm', restoreTrainingConfirmation);
    return () => window.removeEventListener('demo-guide:restore-training-confirm', restoreTrainingConfirmation);
  }, [objective, selectedAlgorithmProfile, selectedDataFileProfile, trainingDraftConfig]);

  const automationSteps = useMemo<AutomationStep[]>(() => [
    { id: 'intent', label: '识别目标', detail: objective.label },
    { id: 'objective', label: '选择优化目标', detail: objective.id },
    { id: 'algorithm', label: '匹配算法/数据', detail: `${selectedAlgorithmProfile.label} · ${selectedDataFileProfile.label}` },
    { id: 'open_ui', label: '打开配置 UI', detail: '展开训练参数与 reward weights' },
    { id: 'risk', label: '生成风险审查', detail: `${trainingRiskWarnings.length} 条风险提示` },
    { id: 'confirm', label: '等待人工确认', detail: trainingReviewOpen ? '需要点击确认开始训练' : '可继续调整参数' },
    { id: 'launch', label: '调用训练接口', detail: '/api/rl/train/start' },
  ], [objective, selectedAlgorithmProfile, selectedDataFileProfile, trainingReviewOpen, trainingRiskWarnings.length]);

  const outputLocator = useMemo(() => {
    if (stageModal) {
      return {
        surface: '阶段弹窗 UI',
        title: stageModal.title,
        detail: `${stageModal.eyebrow} · ${stageModal.description}`,
        tone: stageModal.kind,
      };
    }
    if (trainingStudioOpen) {
      return {
        surface: 'RL 训练配置工作台',
        title: trainingReviewOpen ? '训练前人工确认' : '训练参数调整',
        detail: `${objective.label} · ${selectedAlgorithmProfile.label} · ${selectedDataFileProfile.label}`,
        tone: trainingReviewOpen ? 'confirm' : 'info',
      };
    }
    return {
      surface: 'AI 调度执行详情',
      title: executionDetail.label,
      detail: executionDetail.resultSummary,
      tone: executionDetail.status === 'completed' ? 'done' : executionDetail.status === 'pending_confirmation' ? 'confirm' : executionDetail.status === 'executing' ? 'running' : 'info',
    };
  }, [executionDetail, objective, selectedAlgorithmProfile, selectedDataFileProfile, stageModal, trainingReviewOpen, trainingStudioOpen]);

  const commandShortcuts = useMemo<CommandShortcutItem[]>(() => {
    const objectiveTrainingCommands = trainingObjectives.map((profile) => ({
      id: `train_${profile.id}`,
      label: `训练：${profile.label}`,
      group: '优化目标训练',
      command: profile.command,
      actionId: 'start_rl_training',
      objectiveId: profile.id,
      badge: resolveAlgorithmProfile(profile.algorithm).label,
      description: `${resolveAlgorithmProfile(profile.algorithm).tag} · ${displayNumber(profile.totalSteps)} steps · ${profile.reason}`,
    }));
    const baseCommands = commandCatalog.map((item) => ({
      id: item.id,
      label: item.label,
      group: item.group === '舷鸥/RL/模拟器' ? '联动执行' : item.group,
      command: catalogCommand(item),
      actionId: item.id,
      badge: actionContracts[item.id]?.method ?? 'LOCAL',
      description: `${item.group} · ${catalogCommand(item)}`,
    }));
    return [...objectiveTrainingCommands, ...baseCommands];
  }, [objective]);

  const commandGroups = useMemo(() => ['全部', ...Array.from(new Set(commandShortcuts.map((item) => item.group)))], [commandShortcuts]);

  const filteredCommandShortcuts = useMemo(() => {
    const query = commandSearch.trim().toLowerCase();
    return commandShortcuts.filter((item) => {
      const groupOk = activeCommandGroup === '全部' || item.group === activeCommandGroup;
      const text = `${item.label} ${item.group} ${item.command} ${item.description}`.toLowerCase();
      return groupOk && (!query || text.includes(query));
    });
  }, [activeCommandGroup, commandSearch, commandShortcuts]);

  useEffect(() => {
    const profile = trainingObjectives.find((item) => item.id === selectedObjective) ?? trainingObjectives[0];
    const recommended = createTrainingParams(profile);
    setTrainingParams((current) => ({
      ...current,
      algorithm: recommended.algorithm,
      horizon_min: recommended.horizon_min,
      total_steps: recommended.total_steps,
      batch_size: recommended.batch_size,
      learning_rate: recommended.learning_rate,
      gamma: recommended.gamma,
      tau: recommended.tau,
      entropy_coef: recommended.entropy_coef,
      reward_weights: alignRewardWeightsForDataset(profile.rewardWeights, current.data_file),
    }));
  }, [selectedObjective]);

  useEffect(() => {
    const prepareQuickDemo = () => {
      setTrainingParams(current => ({...current,total_steps:320,batch_size:32,eval_interval:160,checkpoint_interval:1000}));
      setStageModal(current => current ? {...current, details:[...current.details.filter(item => item.label !== '演示训练步数'), {label:'演示训练步数',value:'320 步真实训练；仅验证链路，正式价值读取封存评测'}]} : current);
      addLog('RL/DEMO','320-step real training pipeline; not convergence or business-value evidence');
    };
    window.addEventListener('demo-guide:prepare-quick-training',prepareQuickDemo);
    return () => window.removeEventListener('demo-guide:prepare-quick-training',prepareQuickDemo);
  }, []);

  function addLog(kind: string, message: string) {
    logSequenceRef.current += 1;
    // Capture the id before React batches updater functions. Reading the ref
    // inside the updater made several rapid log entries share the final id,
    // producing duplicate React keys and unnecessary re-renders during demos.
    const id = logSequenceRef.current;
    setLogs((items) => [{ id, time: now(), kind, message }, ...items].slice(0, 18));
  }

  function applyCommandShortcut(shortcut: CommandShortcutItem) {
    const profile = shortcut.objectiveId ? trainingObjectives.find((item) => item.id === shortcut.objectiveId) : null;
    if (profile) {
      setSelectedObjective(profile.id);
      setTrainingParams(createTrainingParams(profile));
    }
    setCommand(shortcut.command);
    setSelectedAction(shortcut.actionId);
    setCommandCenterOpen(false);
  }

  async function judgeCommandShortcut(shortcut: CommandShortcutItem) {
    applyCommandShortcut(shortcut);
    await askXiaoyi(shortcut.command, shortcut.actionId, false);
  }

  async function executeCommandShortcut(shortcut: CommandShortcutItem) {
    applyCommandShortcut(shortcut);
    const profile = shortcut.objectiveId ? trainingObjectives.find((item) => item.id === shortcut.objectiveId) : null;
    if (profile) {
      await startTraining(profile);
      return;
    }
    await executeCatalogAction(shortcut.actionId, shortcut.command);
  }

  function selectTrainingObjective(objectiveId: string) {
    setTrainingReviewOpen(false);
    const next = trainingObjectives.find((item) => item.id === objectiveId) ?? trainingObjectives[0];
    setSelectedObjective(next.id);
    setSelectedAction('start_rl_training');
    setCommand(next.command);
  }

  function applyAlgorithm(algorithmId: string) {
    setTrainingReviewOpen(false);
    const requested = trainingParams.data_file === 'port_la_2020_2024_hybrid_rl_hourly' && algorithmId === 'dqn'
      ? 'ppo'
      : algorithmId;
    const algorithm = rlAlgorithms.find((item) => item.id === requested) ?? rlAlgorithms[0];
    setTrainingParams((current) => ({
      ...current,
      algorithm: algorithm.id,
      total_steps: algorithm.defaults.total_steps,
      batch_size: algorithm.defaults.batch_size,
      learning_rate: algorithm.defaults.learning_rate,
      gamma: algorithm.defaults.gamma,
      tau: algorithm.defaults.tau,
      entropy_coef: algorithm.defaults.entropy_coef,
    }));
  }

  function updateTrainingNumber(key: NumericTrainingParamKey, value: string) {
    setTrainingReviewOpen(false);
    const next = Number(value);
    setTrainingParams((current) => ({ ...current, [key]: Number.isFinite(next) ? next : 0 }));
  }

  function updateRewardWeight(key: string, value: string) {
    setTrainingReviewOpen(false);
    const next = Number(value);
    setTrainingParams((current) => ({
      ...current,
      reward_weights: { ...current.reward_weights, [key]: Number.isFinite(next) ? next : 0 },
    }));
  }

  function openTrainingStudio(review = false, mode: AutomationMode = 'manual') {
    setTrainingStudioOpen(true);
    setTrainingReviewOpen(review);
    setAutomationMode(mode);
    setAutomationStepIndex(review ? 5 : 3);
  }

  function pulseElement(selector: string, duration = 900) {
    const target = document.querySelector<HTMLElement>(selector);
    if (!target) return;
    target.scrollIntoView({ block: 'center', inline: 'nearest', behavior: 'smooth' });
    target.classList.add('linkage-autoclick-target');
    window.setTimeout(() => target.classList.remove('linkage-autoclick-target'), duration);
  }

  function buildTrainingStageModal(stepIndex: number, kind: StageModalKind = 'ok'): StageModalState {
    const currentStep = automationSteps[Math.min(stepIndex, automationSteps.length - 1)] ?? automationSteps[0];
    const detailMap: Record<number, Array<{ label: string; value: string }>> = {
      0: [
        { label: '识别意图', value: objective.command },
        { label: '动作类型', value: '启动 RL 训练' },
        { label: '输出位置', value: 'RL 训练配置工作台' },
      ],
      1: [
        { label: '优化目标', value: objective.label },
        { label: '目标编号', value: objective.id },
        { label: '确认结果', value: '目标匹配无误' },
      ],
      2: [
        { label: '推荐算法', value: `${selectedAlgorithmProfile.label} · ${selectedAlgorithmProfile.tag}` },
        { label: '训练数据', value: selectedDataFileProfile.label },
        { label: '文件路径', value: trainingParams.data_file },
      ],
      3: [
        { label: '参数窗口', value: '已打开独立 UI' },
        { label: '训练步数', value: `${displayNumber(trainingParams.total_steps)} steps` },
        { label: '安全护栏', value: trainingParams.guardrail_mode },
      ],
      4: [
        { label: '风险提示数量', value: `${trainingRiskWarnings.length} 条` },
        { label: '上线约束', value: '训练结果仅进入 dry-run 验证' },
        { label: '确认结果', value: '风险审查已生成' },
      ],
      5: [
        { label: '优化目标', value: objective.label },
        { label: '算法 / 数据', value: `${selectedAlgorithmProfile.label} / ${selectedDataFileProfile.label}` },
        { label: '人工动作', value: '请确认无误后开始训练' },
      ],
      6: [
        { label: '调用接口', value: 'POST /api/rl/train/start' },
        { label: '训练配置', value: `${trainingDraftConfig.objective_id} · ${trainingDraftConfig.algorithm}` },
        { label: '返回位置', value: 'AI 调度执行详情 + 训练状态' },
      ],
    };
    return {
      kind,
      stepIndex,
      eyebrow: `STEP ${stepIndex + 1} · ${currentStep.label}`,
      title: kind === 'confirm' ? '请人工确认训练信息' : `${currentStep.label}已确认无误`,
      description: kind === 'confirm'
        ? '舷鸥已完成前序核验，请人工复核全部训练信息后再启动。'
        : `舷鸥已完成“${currentStep.label}”，当前阶段信息已核验无误。`,
      details: detailMap[stepIndex] ?? [{ label: currentStep.label, value: currentStep.detail }],
      progress: kind === 'running' ? 32 : 100,
      progressLabel: kind === 'confirm'
        ? '等待人工确认'
        : kind === 'running'
          ? '训练接口调用中'
          : kind === 'done'
            ? '执行链路完成'
            : '阶段核验完成',
    };
  }

  async function animateStageModal(stage: StageModalState, duration = 900, label = '舷鸥正在核验本阶段信息') {
    const initialProgress = stage.kind === 'running' ? 18 : 6;
    setAutomationStepIndex(stage.stepIndex);
    setStageModal({ ...stage, progress: duration > 0 ? initialProgress : 100, progressLabel: duration > 0 ? label : '阶段核验完成' });
    if (duration <= 0) return;
    // A single state transition lets CSS render the progress sweep without a
    // chain of short timers. Background browser tabs clamp every short timer
    // to about one second, which previously stretched this sequence to tens
    // of seconds during a live demo.
    window.setTimeout(() => {
      setStageModal((current) => {
        if (!current || current.stepIndex !== stage.stepIndex || current.kind !== stage.kind) return current;
        return {
          ...current,
          progress: 100,
          progressLabel: '本阶段确认无误',
        };
      });
    }, Math.min(220, Math.max(40, duration / 3)));
    await wait(duration);
  }

  async function showStageModal(stepIndex: number, kind: StageModalKind = 'ok', duration = 900) {
    await animateStageModal(buildTrainingStageModal(stepIndex, kind), duration);
  }

  function actionMeta(actionId: string, instruction = '') {
    const item = commandCatalog.find((entry) => entry.id === actionId);
    const contract = actionContracts[actionId] ?? { method: 'POST', path: '/api/assistant/actions/execute', confirmationRequired: false };
    return {
      item,
      contract,
      label: item?.label ?? (actionId || '普通问答'),
      group: item?.group ?? '舷鸥问答',
      instruction: instruction || item?.command || command.trim() || '等待输入',
      buttonLabel: item?.label ?? '后台动作',
    };
  }

  function setExecution(actionId: string, status: ExecutionStatus, instruction = '', overrides: Partial<ExecutionDetail> = {}) {
    const meta = actionMeta(actionId, instruction);
    const statusLabelMap: Record<ExecutionStatus, string> = {
      idle: 'READY',
      thinking: 'INTENT',
      pending_confirmation: 'CONFIRM',
      executing: 'RUNNING',
      completed: 'DONE',
      failed: 'FAILED',
    };
    setExecutionDetail((current) => ({
      ...current,
      actionId,
      label: meta.label,
      group: meta.group,
      instruction: meta.instruction,
      buttonLabel: meta.buttonLabel,
      apiMethod: meta.contract.method,
      apiPath: meta.contract.path,
      confirmationRequired: meta.contract.confirmationRequired,
      status,
      statusLabel: statusLabelMap[status],
      updatedAt: now(),
      ...overrides,
    }));
  }

  function completeExecution(actionId: string, resultSummary: string, result: unknown, instruction = '') {
    const payload = result && typeof result === 'object' ? result as Record<string, any> : {};
    const statuses = [
      payload.status,
      payload.result?.status,
      payload.execution?.status,
      payload.execution_result?.status,
      payload.verify?.status,
      payload.dispatch?.status,
    ].map((value) => String(value ?? '').toLowerCase());
    const failed = payload.ok === false || payload.verify?.ok === false || statuses.some((status) => ['failed', 'error', 'blocked', 'unavailable', 'timeout', 'timed_out', 'budget_exceeded'].some((prefix) => status === prefix || status.startsWith(`${prefix}_`)));
    setExecution(actionId, failed ? 'failed' : 'completed', instruction, {
      resultSummary,
      resultCode: pretty(result).slice(0, 900),
    });
    if (failed) throw new Error(payload.detail ?? payload.error ?? payload.execution?.error ?? payload.execution_result?.message ?? payload.execution_result?.result?.error ?? payload.execution_result?.result?.reason ?? payload.result?.message ?? resultSummary);
  }

  function failExecution(actionId: string, error: unknown, instruction = '') {
    setExecution(actionId, 'failed', instruction, {
      resultSummary: `执行失败：${String(error)}`,
      resultCode: String(error),
    });
  }

  async function runUiAction(actionId: string, task: () => Promise<unknown>) {
    // A direct page click can arrive just before the preceding action's
    // finally block releases the lock. Queue that click briefly instead of
    // dropping it silently, otherwise the page and demo guide can diverge.
    let lockWaitMs = 0;
    while (actionRunningRef.current && lockWaitMs < 600) {
      await wait(30);
      lockWaitMs += 30;
    }
    if (actionRunningRef.current) {
      setPacket('上一步仍在收尾，请重试当前按钮。');
      setAnswer('当前动作没有丢失：上一步仍在收尾，按钮已重新解锁，可立即再点一次。');
      return;
    }
    actionRunningRef.current = true;
    setBusy(true);
    if (!['start_xiaoyi_ai', 'refresh_linkage_status'].includes(actionId)) xiaoyiStartupPendingRef.current = false;
    setPendingPacket(null);
    try {
      await task();
    } catch (error) {
      failExecution(actionId, error, command);
      setPendingPacket(null);
      setStageModal(null);
      setPacket(`执行失败：${String(error)}`);
      setAnswer(`执行失败：${String(error)}。请检查参数或联动服务后重试。`);
      addLog('ACTION/ERROR', `${actionId} · ${String(error)}`);
    } finally {
      actionRunningRef.current = false;
      setBusy(false);
    }
  }

  async function typeAnswer(text: string) {
    setAnswer('正在读取工具结果并核验来源边界…');
    await wait(45);
    setAnswer(text);
  }

  async function refreshAll() {
    const [nextHealth, nextTraining, nextSailing, nextRegistry] = await Promise.all([
      api('/api/linkage/health').catch((error) => ({ summary: { runtime: '后端离线', xiaoyi: '舷鸥状态未能核验', rl: '训练状态未能核验', sailing: '模拟器状态未能核验' }, error: String(error) })),
      api('/api/rl/train/status').catch((error) => ({ status: 'offline', error: String(error) })),
      api('/api/sailing/status').catch((error) => ({ label: '航行模拟器待检查', error: String(error) })),
      api('/api/rl/actions/registry').catch((error) => ({ count: commandCatalog.length, error: String(error) })),
    ]);
    setHealth(nextHealth);
    const xiaoyi = (nextHealth as JsonMap).systems?.xiaoyi_ai;
    if (xiaoyiStartupPendingRef.current && xiaoyi?.online === true) {
      xiaoyiStartupPendingRef.current = false;
      completeExecution('start_xiaoyi_ai', '舷鸥健康检查已通过，服务在线。', xiaoyi, '小鸥，启动舷鸥 · GullMate');
    }
    setTrainingStatus(nextTraining);
    setSailingStatus(nextSailing);
    setActionRegistry(nextRegistry);
  }

  useEffect(() => {
    refreshAll();
    // Linkage health validates local integrations and RL capabilities, so it is
    // intentionally sampled at a lower cadence than the lightweight live
    // training status. Re-scanning it every few seconds can starve operator
    // actions while large registered datasets are being verified.
    const timer = window.setInterval(refreshAll, 60000);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    const timer = window.setInterval(async () => {
      const nextTraining = await api('/api/rl/train/status').catch((error) => ({ status: 'offline', error: String(error) }));
      setTrainingStatus(nextTraining);
    }, 1200);
    return () => window.clearInterval(timer);
  }, []);

  function resolvePayload(dryRun: boolean, confirm = false) {
    const payload: JsonMap = {
      instruction: command.trim(),
      dry_run: dryRun,
      source: 'energy_carbon_cockpit',
    };
    if (selectedAction) payload.action_id = selectedAction;
    if (confirm) payload.confirm = true;
    if ((selectedAction || pendingPacket?.action?.id) === 'start_rl_training') {
      payload.objective_id = selectedObjective;
      payload.config = trainingDraftConfig;
    }
    return payload;
  }

  async function askXiaoyi(prefill?: string, actionId?: string, autoExecute = true) {
    const nextCommand = prefill ?? command.trim();
    if (prefill !== undefined) setCommand(prefill);
    if (actionId !== undefined) setSelectedAction(actionId);
    if (!nextCommand && !actionId && !selectedAction) {
      await typeAnswer('请输入一句指令，或者选择一个动作。');
      return;
    }
    setExecution((actionId ?? selectedAction) || 'xiaoyi_intent', 'thinking', nextCommand, {
      resultSummary: '舷鸥正在识别意图并匹配可执行动作。',
      resultCode: 'intent_matching',
    });
    setPendingPacket(null);
    setPacket('舷鸥正在判断动作...');
    const payload = {
      ...resolvePayload(true, false),
      instruction: nextCommand,
      action_id: (actionId ?? selectedAction) || undefined,
    };
    try {
      const data = await api('/api/assistant/actions/execute', { method: 'POST', body: payload });
      setPacket(pretty(data));
      if (!data.matched) {
        const chat = await api('/api/xiaoyi/chat', { method: 'POST', body: { question: nextCommand, mode: 'brief', top_k: 5 } });
        const text = chat.result?.answer || chat.answer || '舷鸥已接收问题，但暂未返回可展示答案。';
        completeExecution('xiaoyi_chat', '未匹配到联动按钮，已转为舷鸥普通问答。', chat, nextCommand);
        await typeAnswer(text);
        addLog('GullMate', '普通问答已交给舷鸥');
        return;
      }
      setPendingPacket(data);
      const action = data.action ?? {};
      const will = data.will_execute ?? {};
      const recommendation = data.recommendation;
      const recommendedObjective = recommendation?.config?.objective_id ?? recommendation?.objective_id;
      if (action.id === 'start_rl_training' && typeof recommendedObjective === 'string') {
        setSelectedObjective(recommendedObjective);
      }
      setExecution(String(action.id ?? 'matched_action'), data.human_confirmation?.required ? 'pending_confirmation' : 'completed', nextCommand, {
        label: String(action.label ?? '待确认动作'),
        buttonLabel: String(will.button?.label ?? action.button_label ?? '后台动作'),
        apiMethod: String(will.backend_request?.method ?? action.backend_request?.method ?? actionContracts[String(action.id ?? '')]?.method ?? 'POST'),
        apiPath: String(will.backend_request?.path ?? action.backend_request?.path ?? actionContracts[String(action.id ?? '')]?.path ?? '/api/assistant/actions/execute'),
        confirmationRequired: Boolean(data.human_confirmation?.required),
        resultSummary: data.human_confirmation?.required ? '动作已识别，等待人工确认后执行。' : '动作已识别，可直接查询或 dry-run。',
        resultCode: pretty(data).slice(0, 900),
      });
      const lines = [
        `已识别：${action.label ?? '待确认动作'}`,
        will.button?.label ? `将执行按钮：${will.button.label}` : '将执行后台联动动作。',
        will.backend_request?.path ? `将调用接口：${will.backend_request.method ?? 'POST'} ${will.backend_request.path}` : '',
        recommendation?.config ? `推荐算法：${String(recommendation.config.algorithm ?? '').toUpperCase()}，训练步数：${recommendation.config.total_steps}` : '',
        data.human_confirmation?.required ? '需要人工确认后执行。' : '可直接查询或 dry-run。',
      ].filter(Boolean);
      await typeAnswer(lines.join('\n'));
      addLog('GullMate', `动作识别：${action.id ?? 'unknown'}`);
      if (autoExecute && !data.human_confirmation?.required) {
        await wait(80);
        const clicked = await clickMappedButton(data);
        if (!clicked) {
          await typeAnswer('动作已经识别，但当前页面没有找到可点击按钮。请在指令中心重新执行。');
        }
      }
    } catch (error) {
      failExecution((actionId ?? selectedAction) || 'xiaoyi_intent', error, nextCommand);
      setPendingPacket(null);
      setPacket(`执行失败：${String(error)}`);
      setAnswer(`执行失败：${String(error)}。请检查训练参数或联动服务后重试。`);
      addLog('XIAOYI/ERROR', String(error));
    }
  }

  async function runXiaoyiTrainingSequence(packetData: PendingPacket, target: HTMLButtonElement, label: string) {
    const instruction = command || String(packetData.action?.label ?? objective.command);
    setTrainingStudioOpen(true);
    setTrainingReviewOpen(false);
    setAutomationMode('xiaoyi');
    setAutomationStepIndex(0);
    setExecution('start_rl_training', 'executing', instruction, {
      buttonLabel: label,
      resultSummary: '舷鸥正在逐步配置训练任务，并准备弹出人工确认面板。',
      resultCode: pretty({ objective: selectedObjective, algorithm: trainingParams.algorithm, data_file: trainingParams.data_file }).slice(0, 900),
    });
    addLog('XIAOYI/AUTO', '识别训练意图，开始自动配置。');
    await showStageModal(0, 'ok', 90);
    await typeAnswer('舷鸥开始执行训练准备流程：先识别优化目标，再选择算法和数据文件，最后打开训练确认面板。');
    const scriptedSteps = [
      { step: 1, selector: '#trainingObjectiveSelect', log: `选择优化目标：${objective.label}` },
      { step: 2, selector: '#trainingAlgorithmSelect', log: `匹配算法与数据：${selectedAlgorithmProfile.label} / ${selectedDataFileProfile.label}` },
      { step: 3, selector: '#btnStartTraining', log: '点击启动训练，弹出训练前确认 UI。' },
    ];
    for (const item of scriptedSteps) {
      setAutomationStepIndex(item.step);
      pulseElement(item.selector, 700);
      addLog('XIAOYI/CLICK', item.log);
      await showStageModal(item.step, 'ok', 110);
    }
    target.classList.add('linkage-autoclick-target');
    xiaoyiTrainingRunRef.current = true;
    await startTraining();
    window.setTimeout(() => target.classList.remove('linkage-autoclick-target'), 1400);
    return true;
  }

  async function clickMappedButton(packetData: PendingPacket) {
    const actionId = String(packetData.action?.id ?? packetData.will_execute?.action_id ?? '');
    const requiredState: Record<string, string[]> = { pause_rl_training: ['running'], resume_rl_training: ['paused'], stop_rl_training: ['running', 'paused'] };
    if (requiredState[actionId] && !requiredState[actionId].includes(String(trainingStatus?.status))) {
      throw new Error('训练状态不满足此动作，请先刷新训练状态。');
    }
    const selector = String(packetData.will_execute?.button?.selector ?? packetData.action?.button_selector ?? '');
    if (!clickableActions.has(actionId) || !selector) return false;
    const preludeSteps = actionPreludeSteps[actionId] ?? [];
    const target = document.querySelector<HTMLButtonElement>(selector);
    if (!target && !preludeSteps.length) return false;
    const label = String(packetData.will_execute?.button?.label ?? packetData.action?.button_label ?? target?.textContent ?? actionId);
    if (actionId === 'start_rl_training') {
      if (!target) return false;
      return runXiaoyiTrainingSequence(packetData, target, label);
    }
    const steps = [
      ...preludeSteps,
      { selector, label: `${label} / Execute action` },
    ].filter((step, index, items) => items.findIndex((item) => item.selector === step.selector) === index);
    setClickSequence(steps.map((step) => ({ ...step, status: 'pending' })));
    setExecution(actionId, 'executing', command || String(packetData.action?.label ?? ''), {
      buttonLabel: label,
      resultSummary: `舷鸥已规划 ${steps.length} 步页面操作，正在依次定位并点击。`,
      resultCode: steps.map((step) => step.selector).join(' -> '),
    });
    for (let index = 0; index < steps.length; index += 1) {
      const step = steps[index];
      setClickSequence((items) => items.map((item, itemIndex) => itemIndex === index ? { ...item, status: 'locating' } : item));
      const stepTarget = document.querySelector<HTMLButtonElement>(step.selector);
      const isLocalAction = commandCatalog.some((item) => `#${item.buttonId}` === step.selector);
      if (!stepTarget || (stepTarget.disabled && !isLocalAction)) {
        setClickSequence((items) => items.map((item, itemIndex) => itemIndex === index ? { ...item, status: 'failed' } : item));
        setExecution(actionId, 'failed', command || String(packetData.action?.label ?? ''), {
          buttonLabel: step.label,
          resultSummary: `第 ${index + 1} 步不可执行：按钮不存在或当前不可用。`,
          resultCode: step.selector,
        });
        setAnswer(`执行暂停：${step.label} 当前不可用，请先完成前置状态。`);
        addLog('XIAOYI/CLICK', `第 ${index + 1} 步失败：${step.label}`);
        return true;
      }
      stepTarget.scrollIntoView({ block: 'center', inline: 'nearest', behavior: 'smooth' });
      stepTarget.classList.add('linkage-autoclick-target');
      setClickSequence((items) => items.map((item, itemIndex) => itemIndex === index ? { ...item, status: 'clicking' } : item));
      setAnswer(`正在执行 ${index + 1}/${steps.length}：${step.label}`);
      addLog('XIAOYI/CLICK', `步骤 ${index + 1}/${steps.length}：${step.label}`);
      await wait(100);
      try {
        const mappedAction = index === steps.length - 1 ? actionId : commandCatalog.find((item) => `#${item.buttonId}` === step.selector)?.id;
        if (!mappedAction) throw new Error(`按钮没有绑定可等待的执行处理：${step.selector}`);
        await executeCatalogAction(mappedAction, commandCatalog.find((item) => item.id === mappedAction)?.command ?? command);
      } catch (error) {
        setClickSequence((items) => items.map((item, itemIndex) => itemIndex === index ? { ...item, status: 'failed' } : item));
        throw error;
      } finally {
        stepTarget.classList.remove('linkage-autoclick-target');
      }
      setClickSequence((items) => items.map((item, itemIndex) => itemIndex === index ? { ...item, status: 'done' } : item));
    }
    setPendingPacket(null);
    addLog('XIAOYI/CLICK', `${actionId} · ${steps.length} steps completed`);
    return true;
  }

  async function confirmAction() {
    if (!pendingPacket) return;
    if (await clickMappedButton(pendingPacket)) return;
    const payload = resolvePayload(false, true);
    payload.action_id = pendingPacket.action?.id;
    setExecution(String(payload.action_id ?? 'confirmed_action'), 'executing', command, {
      resultSummary: '人工确认已收到，正在调用联动执行接口。',
    });
    const data = await api('/api/assistant/actions/execute', { method: 'POST', body: payload });
    setPacket(pretty(data));
    completeExecution(String(payload.action_id ?? 'confirmed_action'), `执行结果：${data.execution_result?.status ?? '完成'}。`, data, command);
    await typeAnswer(`执行结果：${data.execution_result?.status ?? '完成'}。`);
    addLog('EXEC', `${payload.action_id} · ${data.execution_result?.status ?? 'done'}`);
    setPendingPacket(null);
    await refreshAll();
  }

  async function launchXiaoyi() {
    setExecution('start_xiaoyi_ai', 'executing', '小鸥，启动舷鸥 · GullMate', {
      resultSummary: '正在启动舷鸥本地服务。',
    });
    setPacket('正在启动舷鸥 · GullMate...');
    const data = await api('/api/xiaoyi/launch', { method: 'POST', body: { confirm: true, source: 'energy_carbon_cockpit' } });
    setPacket(pretty(data));
    const starting = data.result?.status === 'starting';
    xiaoyiStartupPendingRef.current = starting;
    if (starting) {
      setExecution('start_xiaoyi_ai', 'executing', '小鸥，启动舷鸥 · GullMate', { resultSummary: '舷鸥进程已启动，健康检查尚未通过；请稍后刷新状态。', resultCode: pretty(data).slice(0, 900) });
    } else {
      completeExecution('start_xiaoyi_ai', `执行结果：${data.result?.status ?? '完成'}。`, data, '小鸥，启动舷鸥 · GullMate');
    }
    await typeAnswer(`${starting ? '舷鸥正在启动，等待健康检查通过；可稍后刷新状态。' : `执行结果：${data.result?.status ?? '完成'}。`}\n舷鸥地址：${data.status?.base_url ?? 'http://127.0.0.1:8010'}`);
    addLog('GullMate', `start_xiaoyi_ai · ${data.result?.status ?? 'done'}`);
    await refreshAll();
  }

  function validateTrainingParams(params: TrainingParams) {
    for (const field of trainingParamFields) {
      const value = params[field.key];
      if (!Number.isFinite(value) || value < field.min || (field.max !== undefined && value > field.max)) {
        throw new Error(`${field.label} 必须在 ${field.min}–${field.max ?? '∞'} 范围内。`);
      }
    }
    if (params.algorithm !== 'mpc' && (!Number.isInteger(params.total_steps) || params.total_steps < 32)) throw new Error('RL 训练总步数必须为 32–5,000,000 的整数。');
    for (const key of ['horizon_min', 'batch_size', 'seed', 'eval_interval', 'checkpoint_interval'] as const) {
      if (!Number.isInteger(params[key])) throw new Error(`${key} 必须为整数。`);
    }
    if (params.horizon_min % 60 !== 0) throw new Error('训练 horizon 必须为 60 分钟的整数倍。');
    if (params.algorithm !== 'mpc' && params.learning_rate <= 0) throw new Error('RL learning rate 必须大于 0。');
    if (!params.data_file.trim() || !params.scenario.trim() || !params.asset_group.trim()) throw new Error('训练数据、场景和资产组不能为空。');
    if (Object.values(params.reward_weights).some((value) => !Number.isFinite(value) || value < 0 || value > 1)) throw new Error('奖励权重必须在 0–1 范围内。');
  }

  async function startTraining(targetObjective = objective) {
    const targetParams = targetObjective.id === objective.id ? trainingParams : createTrainingParams(targetObjective);
    validateTrainingParams(targetParams);
    const targetConfig = buildTrainingDraftConfig(targetObjective, targetParams);
    const targetWarnings = buildTrainingRiskWarnings(targetParams);
    const targetAlgorithm = resolveAlgorithmProfile(targetParams.algorithm);
    const targetDataFile = resolveDataFileProfile(targetParams.data_file);
    const instruction = targetObjective.command;
    const startedByXiaoyi = xiaoyiTrainingRunRef.current;
    xiaoyiTrainingRunRef.current = false;
    if (targetObjective.id !== objective.id) {
      setSelectedObjective(targetObjective.id);
      setTrainingParams(targetParams);
    }
    setCommand(instruction);
    setSelectedAction('start_rl_training');
    setTrainingStudioOpen(true);
    setTrainingReviewOpen(true);
    setAutomationMode(startedByXiaoyi ? 'xiaoyi' : 'manual');
    setAutomationStepIndex(4);
    await animateStageModal({
      kind: 'ok',
      stepIndex: 4,
      eyebrow: 'STEP 5 · 生成风险审查',
      title: '生成风险审查已确认无误',
      description: '舷鸥已完成风险审查，当前阶段信息已核验无误。',
      details: [
        { label: '风险提示数量', value: `${targetWarnings.length} 条` },
        { label: '优化目标', value: targetObjective.label },
        { label: '上线约束', value: '训练结果仅进入 dry-run 验证' },
      ],
      progress: 100,
      progressLabel: '风险审查已生成',
    }, 130, '正在生成风险审查和训练摘要');
    const reviewPacket = {
      config: targetConfig,
      risk_warnings: targetWarnings,
      human_confirmation: true,
    };
    setPacket(pretty(reviewPacket));
    setExecution('start_rl_training', 'pending_confirmation', instruction, {
      resultSummary: `已生成“${targetObjective.label}”训练方案，等待人工确认算法、数据和风险。`,
      resultCode: pretty(reviewPacket).slice(0, 900),
    });
    await typeAnswer(`已生成 ${targetObjective.label} 训练方案。\n请在训练前确认面板检查算法、数据文件、全部训练参数和风险警告，然后决定是否开始。`);
    setAutomationStepIndex(5);
    setStageModal({
      kind: 'confirm',
      stepIndex: 5,
      eyebrow: 'STEP 6 · 等待人工确认',
      title: '请人工确认训练信息',
      description: '舷鸥已完成前序核验，请人工复核全部训练信息后再启动。',
      details: [
        { label: '优化目标', value: targetObjective.label },
        { label: '算法 / 数据', value: `${targetAlgorithm.label} / ${targetDataFile.label}` },
        { label: '人工动作', value: '请确认无误后开始训练' },
      ],
      progress: 100,
      progressLabel: '前序阶段全部完成，等待人工确认',
    });
    addLog('RL/REVIEW', `training_review · ${targetObjective.label}`);
  }

  async function confirmStartTraining() {
    validateTrainingParams(trainingParams);
    const instruction = objective.command;
    setCommand(instruction);
    setSelectedAction('start_rl_training');
    setAutomationMode(automationMode === 'xiaoyi' ? 'xiaoyi' : 'manual');
    setAutomationStepIndex(6);
    await animateStageModal(buildTrainingStageModal(6, 'running'), 140, '正在调用训练启动接口');
    setExecution('start_rl_training', 'executing', instruction, {
      resultSummary: '人工确认已收到，正在启动 RL 训练任务。',
      resultCode: pretty(trainingDraftConfig).slice(0, 900),
    });
    const data = await api('/api/rl/train/start', {
      method: 'POST',
      body: {
        confirm: true,
        instruction,
        objective_id: objective.id,
        config: trainingDraftConfig,
        risk_warnings: trainingRiskWarnings,
        source: 'energy_carbon_cockpit',
      },
    });
    setPacket(pretty(data));
    setTrainingReviewOpen(false);
    setTrainingStudioOpen(false);
    setTrainingStatus(data.result ?? data);
    completeExecution('start_rl_training', `训练已启动：${objective.label}。`, data, instruction);
    setStageModal({
      kind: 'done',
      stepIndex: 6,
      eyebrow: 'TRAINING STARTED',
      title: '训练任务已启动',
      description: '舷鸥已完成全部核验并调用训练接口，训练状态已刷新。',
      details: [
        { label: '优化目标', value: objective.label },
        { label: '策略版本', value: String((data.result ?? data)?.policy_version ?? '等待生成') },
        { label: '状态位置', value: 'RL 训练 / 策略 与 AI 调度执行详情' },
      ],
      progress: 100,
      progressLabel: '训练任务已进入后台运行',
    });
    await typeAnswer(`训练已启动：${objective.label}。\n算法=${selectedAlgorithmProfile.label}，数据=${selectedDataFileProfile.label}，训练步数=${displayNumber(trainingDraftConfig.total_steps)}。`);
    addLog('RL', `start_rl_training · ${objective.label}`);
    void refreshAll();
  }

  async function openTrainingHistory() {
    setTrainingHistoryOpen(true);
    setSelectedHistoryObjective('carbon_min');
    setHistoryAutoPlay(true);
    if (trainingHistoryLoading) return;
    if (cachedTrainingHistory) {
      setTrainingHistory(cachedTrainingHistory.run ?? cachedTrainingHistory);
      setTrainingHistoryLoading(false);
      setTrainingHistoryError('');
      addLog('RL/EVIDENCE', `历史收敛记录已从演示预热缓存载入：${cachedTrainingHistory.run?.run_id ?? 'offline-run'}`);
      return;
    }
    const requestVersion = historyRequestVersionRef.current + 1;
    historyRequestVersionRef.current = requestVersion;
    setTrainingHistoryLoading(true);
    setTrainingHistoryError('');
    try {
      const data = await loadTrainingHistoryEvidence();
      if (requestVersion !== historyRequestVersionRef.current) return;
      setTrainingHistory(data.run ?? data);
      addLog('RL/EVIDENCE', `历史收敛记录已载入：${data.run?.run_id ?? 'offline-run'}`);
    } catch (error) {
      if (requestVersion !== historyRequestVersionRef.current) return;
      setTrainingHistoryError(String(error));
      setTrainingHistory(null);
      failExecution('training_history', error, '查看历史收敛曲线');
    } finally {
      if (requestVersion === historyRequestVersionRef.current) setTrainingHistoryLoading(false);
    }
  }

  async function showTrainingStatus() {
    setTrainingStatusOpen(true);
    setExecution('view_rl_training_status', 'executing', '小鸥，查看训练状态', {
      resultSummary: '正在读取训练 step、reward、entropy 和策略版本。',
    });
    const data = await api('/api/rl/train/status');
    setTrainingStatus(data);
    setPacket(pretty(data));
    completeExecution('view_rl_training_status', `训练状态：${data.summary ?? data.status ?? '已刷新'}。`, data, '小鸥，查看训练状态');
    await typeAnswer(`训练状态：${data.summary ?? data.status}\nstep=${data.step ?? 0} reward=${data.reward ?? 0} entropy=${data.entropy ?? 0}\npolicy=${data.policy_version ?? '—'}`);
    addLog('RL', `status · ${data.status}`);
  }

  async function controlTraining(action: 'pause' | 'resume' | 'stop') {
    const actionId = action === 'pause' ? 'pause_rl_training' : action === 'resume' ? 'resume_rl_training' : 'stop_rl_training';
    const actionLabel = action === 'pause' ? '暂停训练' : action === 'resume' ? '继续训练' : '停止训练';
    const instruction = `小鸥，${actionLabel}`;
    setExecution(actionId, 'executing', instruction, {
      resultSummary: `正在调用训练控制接口：${actionLabel}。`,
    });
    try {
      const data = await api(`/api/rl/train/${action}`, { method: 'POST' });
      setTrainingStatus(data.result ?? data);
      setPacket(pretty(data));
      completeExecution(actionId, `${actionLabel}完成：${data.summary ?? data.status ?? '状态已更新'}。`, data, instruction);
      await typeAnswer(`${actionLabel}完成。\n${data.summary ?? data.status ?? '训练状态已更新。'}`);
      addLog('RL/CONTROL', `${actionId} · ${data.control_result ?? data.status ?? 'done'}`);
    } catch (error) {
      failExecution(actionId, error, instruction);
      setAnswer(`${actionLabel}失败：${String(error)}`);
      addLog('RL/CONTROL', `${actionId} · failed`);
      throw error;
    }
  }

  async function runPolicyTest() {
    const instruction = '小鸥，读取训练后登记策略测试';
    setExecution('run_policy_test', 'executing', instruction, {
      resultSummary: '正在读取通过制品完整性、数据一致性和安全门禁的登记留出集评测。',
    });
    const registry = await api('/api/rl/registry');
    const policies = Array.isArray(registry.policies) ? registry.policies as JsonMap[] : [];
    const usable = (policy: JsonMap) => (
      ['verified_offline', 'validated_offline'].includes(String(policy.stage))
      && policy.artifact_integrity === 'verified'
      && policy.evaluation_status === 'tested'
    );
    const requested = policies.find((policy) => policy.policy_id === trainingStatus?.job_id);
    const policy = (requested && usable(requested) ? requested : null)
      ?? policies.find((item) => item.stage === 'verified_offline' && usable(item))
      ?? policies.find(usable);
    if (!policy) throw new Error('no_registered_policy_test_evidence');
    const data = {
      status: 'tested',
      policy: {
        policy_id: policy.policy_id,
        policy_version: policy.policy_version,
        algorithm: policy.algorithm,
      },
      metrics: policy.evaluation_metrics,
    };
    setPacket(pretty(data));
    const carbonReduction = Number(data.metrics?.fixed_baseline_carbon_reduction_pct ?? data.metrics?.carbon_reduction_pct ?? 0).toFixed(1);
    const shorePowerGain = Number(data.metrics?.shore_power_gain_pct ?? 0).toFixed(1);
    const costSaving = Number(data.metrics?.fixed_baseline_cost_saving_pct ?? data.metrics?.cost_saving_pct ?? 0).toFixed(1);
    const safetyViolations = data.metrics?.safety_violations ?? 0;
    completeExecution('run_policy_test', `登记策略测试已读取：相对固定资源基线减排 ${carbonReduction}%，岸电提升 ${shorePowerGain} 个百分点，成本节省 ${costSaving}%，安全越界 ${safetyViolations}。`, data, instruction);
    await typeAnswer(`登记策略测试已读取。\n相对固定资源基线减排：${carbonReduction}%；岸电提升：${shorePowerGain} 个百分点；成本节省：${costSaving}%；安全越界：${safetyViolations}。`);
    addLog('RL', 'registered_policy_test · tested');
  }

  async function verifyPolicy() {
    setExecution('verify_policy_for_online', 'executing', '小鸥，验证这个策略能不能上线', {
      resultSummary: '正在读取已持久化的离线验证门禁，并执行调度干运行。',
    });
    const registry = await api('/api/rl/registry');
    const policies = Array.isArray(registry.policies) ? registry.policies as JsonMap[] : [];
    const policy = policies.find((item) => item.stage === 'verified_offline' && item.verification_status === 'verified');
    if (!policy?.policy_id) throw new Error('no_verified_offline_policy');
    const checks = [
      { name: 'artifact_integrity', passed: policy.artifact_integrity === 'verified' },
      { name: 'dataset_consistency', passed: policy.dataset_status === 'verified' },
      { name: 'held_out_evaluation', passed: policy.evaluation_status === 'tested' },
      { name: 'zero_safety_violations', passed: Number((policy.evaluation_metrics as JsonMap | undefined)?.safety_violations ?? -1) === 0 },
      { name: 'persisted_offline_verification', passed: policy.verification_status === 'verified' },
      { name: 'manual_dispatch_boundary', passed: registry.production_dispatch_enabled === false },
    ];
    const verify = {
      ok: checks.every((check) => check.passed),
      status: checks.every((check) => check.passed) ? 'verified' : 'blocked',
      policy_id: policy.policy_id,
      checks,
      risk_level: checks.every((check) => check.passed) ? 'low' : 'high',
      source: 'persisted_offline_registry_evidence',
    };
    const dispatch = await api('/api/rl/dispatch', { method: 'POST', body: { strategy_id: policy.policy_id, dry_run: true, source: 'energy_carbon_cockpit' } });
    setPacket(pretty({ verify, dispatch }));
    const verifyChecks = Array.isArray(verify.checks)
      ? verify.checks.map((check: JsonMap) => `${check.name ?? '未命名约束'} ${check.passed ? 'PASS' : 'BLOCK'}`).join('、')
      : '约束检查结果待返回';
    completeExecution('verify_policy_for_online', `上线验证完成：风险等级 ${verify.risk_level ?? 'low'}；${verifyChecks}；dry-run ${dispatch.dispatch_id ?? 'dryrun'} 已记录。`, { verify, dispatch }, '小鸥，验证这个策略能不能上线');
    await typeAnswer(`上线验证已完成：风险等级 ${verify.risk_level ?? 'low'}。\n约束检查：${verifyChecks}。\n已记录 dry-run：${dispatch.dispatch_id ?? 'dryrun'}，不会生产下发。`);
    addLog('RLOPS', 'verify + dispatch dry-run');
  }

  async function launchSailing() {
    setExecution('open_sailing_simulator', 'executing', '小鸥，启动航行模拟器', {
      resultSummary: '正在请求启动 Godot 航行模拟器主场景。',
    });
    const data = await api('/api/sailing/launch', { method: 'POST', body: { confirm: true, preset: 'main_scene', source: 'energy_carbon_cockpit' } });
    setPacket(pretty(data));
    completeExecution('open_sailing_simulator', `航行模拟器执行结果：${data.result?.status ?? '完成'}。`, data, '小鸥，启动航行模拟器');
    await typeAnswer(`航行模拟器执行结果：${data.result?.status ?? '完成'}。`);
    addLog('SAILING', `open_sailing_simulator · ${data.result?.status ?? 'done'}`);
    await refreshAll();
  }

  async function runSailingAction(actionId: string) {
    const instruction = commandCatalog.find((item) => item.id === actionId)?.command ?? actionId;
    setExecution(actionId, 'executing', instruction, {
      resultSummary: '正在调用航行模拟器动作接口。',
    });
    const data = await api('/api/sailing/actions/execute', {
      method: 'POST',
      // The native smoke process has a 35-second backend deadline.
      timeoutMs: actionId === 'run_sailing_rl_smoke_test' ? 45_000 : undefined,
      body: { action_id: actionId, dry_run: false, confirm: true, source: 'energy_carbon_cockpit' },
    });
    setPacket(pretty(data));
    completeExecution(actionId, `航行模拟器动作完成：${data.execution?.status ?? 'done'}。`, data, instruction);
    await typeAnswer(`航行模拟器动作完成：${data.execution?.status ?? 'done'}。`);
    addLog('SAILING', `${actionId} · ${data.execution?.status ?? 'done'}`);
    await refreshAll();
  }

  async function executeGateway(actionId: string, instruction: string, extra: JsonMap = {}) {
    setExecution(actionId, 'executing', instruction, {
      resultSummary: '正在通过舷鸥联动网关调用目标动作。',
    });
    const data = await api('/api/assistant/actions/execute', {
      method: 'POST',
      body: {
        action_id: actionId,
        instruction,
        dry_run: false,
        confirm: true,
        source: 'energy_carbon_cockpit',
        green_preference: currentGreenPreference,
        carbon_price_cny_per_ton: currentCarbonPrice,
        ...extra,
      },
    });
    setPacket(pretty(data));
    completeExecution(actionId, `网关执行结果：${data.execution_result?.status ?? 'done'}。`, data, instruction);
    return data;
  }

  async function openTopPanel(actionId: string, instruction: string) {
    const panel = topPanelActions[actionId];
    if (!panel) return;
    setCommand(instruction);
    setSelectedAction(actionId);
    // Opening a known local panel must be immediate. The gateway call records
    // the linkage/audit receipt in parallel and must not block the visible UI.
    const gatewayReceipt = executeGateway(actionId, instruction);
    // The drawer is a fixed overlay. Close it before handing focus to the
    // panel, otherwise the newly opened panel is rendered underneath it and
    // its controls cannot be clicked.
    setOpen(false);
    await onOpenTopPanel?.(panel);
    await typeAnswer(`已打开AI决策面板：${commandCatalog.find((item) => item.id === actionId)?.label ?? panel}。`);
    addLog('TOP-PANEL', `${actionId} · opened immediately`);
    void gatewayReceipt
      .then(() => addLog('TOP-PANEL/AUDIT', `${actionId} · gateway receipt recorded`))
      .catch((error) => addLog('TOP-PANEL/AUDIT', `${actionId} · ${String(error)}`));
  }

  async function applyPreference(actionId: string, instruction: string) {
    const preference = preferenceActions[actionId];
    if (!preference) return;
    setCommand(instruction);
    setSelectedAction(actionId);
    onSetGreenPreference?.(preference.value, preference.label);
    setOpen(false);
    await onOpenTopPanel?.(preference.panel);
    const data = await executeGateway(actionId, instruction, { green_preference: preference.value });
    const result = data.execution_result?.result ?? {};
    const reduction = Number(result.carbon_reduction_ton ?? 0).toFixed(1);
    const shoreGain = Number(result.shore_power_gain_pct ?? 0).toFixed(1);
    await typeAnswer(`已切换：${preference.label}。\n绿色偏好=${preference.value.toFixed(2)}，预计减排 ${reduction} t，岸电提升 ${shoreGain} 个百分点。`);
    addLog('PREFERENCE', `${actionId} · ${preference.value.toFixed(2)}`);
  }

  async function refreshDashboardFromXiaoyi(instruction: string) {
    setCommand(instruction);
    setSelectedAction('refresh_dashboard_snapshot');
    const data = await executeGateway('refresh_dashboard_snapshot', instruction);
    await onSyncDashboard?.('舷鸥已触发AI决策面板重新同步。');
    const summary = data.execution_result?.result?.summary ?? '仪表盘已按当前参数重新同步。';
    await typeAnswer(summary);
    addLog('TOP-PANEL', 'refresh_dashboard_snapshot · recomputed');
  }

  async function runHealthCheckFromXiaoyi(instruction: string) {
    setCommand(instruction);
    setSelectedAction('run_linkage_health_check');
    const data = await executeGateway('run_linkage_health_check', instruction);
    const result = data.execution_result?.result ?? {};
    setHealth(result);
    if (onOpenTopPanel) {
      setOpen(false);
      await onOpenTopPanel('api');
    } else {
      await onRunApiCheck?.();
    }
    const summary = result.summary ?? {};
    await typeAnswer(`健康检查完成：${summary.runtime ?? '实时闭环待检查'} / ${summary.xiaoyi ?? '舷鸥待检查'} / ${summary.rl ?? 'RL待检查'} / ${summary.sailing ?? '模拟器待检查'}`);
    addLog('TOP-PANEL', 'run_linkage_health_check · checked');
  }

  async function runRuntimeInsightFromXiaoyi(actionId: string, instruction: string) {
    setCommand(instruction);
    setSelectedAction(actionId);
    // Reveal the runtime surface first so “态势” has an immediate visual
    // response; grounded values continue loading into the answer area.
    setOpen(false);
    await onOpenTopPanel?.('runtime');
    const data = await executeGateway(actionId, instruction);
    const result = data.execution_result?.result ?? {};
    if (actionId === 'summarize_runtime_state') {
      const signals = result.signals ?? {};
      const forecastPoint = result.forecast?.points?.[0];
      await typeAnswer([
        result.summary ?? '实时态势已刷新。',
        `本步能耗 ${Number(result.current_kpis?.energy_kwh ?? 0).toFixed(1)} kWh，碳排 ${Number(result.current_kpis?.carbon_kg ?? 0).toFixed(1)} kg，服务完成率 ${Number(result.current_kpis?.service_fulfilment_pct ?? 0).toFixed(1)}%。`,
        forecastPoint ? `1 小时模型预测负荷 ${Number(forecastPoint.terminal_load_kw ?? 0).toFixed(0)} kW，碳因子 ${Number(forecastPoint.grid_carbon_kg_per_kwh ?? 0).toFixed(3)}。` : '预测被质量门禁关闭。',
        `来源：${signals.grid_import?.source_type ?? '待核验'}；当前仅为公开数据校准实时模拟，生产权限关闭。`,
      ].join('\n'));
    } else if (actionId === 'prepare_runtime_handover') {
      const handover = result.shift_handover ?? {};
      const latest = handover.latest_decision;
      await typeAnswer([
        result.summary ?? '交班摘要已生成。',
        `质量门禁 ${String(handover.quality_gate?.status ?? 'unknown').toUpperCase()}；当前场景 ${handover.runtime?.scenario_id ?? 'unknown'}。`,
        latest ? `最新建议 ${latest.decision_id}：${latest.status}，审批 ${latest.approval_count}/${latest.required_approvals}。` : '当前没有待交接的运行建议。',
        handover.operator_note ?? '请由下一班人工复核。',
      ].join('\n'));
    } else if (actionId === 'triage_runtime_alerts') {
      const actions = Array.isArray(result.operator_actions) ? result.operator_actions : [];
      await typeAnswer([result.summary ?? '异常研判完成。', ...actions.map((item: string, index: number) => `${index + 1}. ${item}`)].join('\n'));
    } else {
      const decision = result.decision;
      await typeAnswer([
        result.summary ?? '最新运行建议已读取。',
        decision ? `安全投影触发 ${decision.triggered_constraints?.length ?? 0} 条约束；相对强基线评分改善 ${Number(decision.predicted_impact?.score_improvement_vs_sop_pct ?? 0).toFixed(1)}%。` : '',
        result.operator_note ?? '舷鸥只做只读解释，不具备审批或执行权限。',
      ].filter(Boolean).join('\n'));
    }
    addLog('RUNTIME', `${actionId} · grounded`);
  }

  async function checkSailingStatusFromXiaoyi(instruction: string) {
    setCommand(instruction);
    setSelectedAction('check_sailing_status');
    const data = await executeGateway('check_sailing_status', instruction);
    const status = data.execution_result?.result?.sailing_status ?? {};
    setSailingStatus(status);
    setOpen(false);
    await onOpenTopPanel?.('simulation');
    await typeAnswer(status.process?.running ? `航行模拟器运行中：pid=${status.process.pid}` : status.label ?? '航行模拟器状态已刷新。');
    addLog('SAILING', 'check_sailing_status · checked');
  }

  async function runCatalogAction(actionId: string, instruction: string) {
    await runUiAction(actionId, () => executeCatalogAction(actionId, instruction));
  }

  async function executeCatalogAction(actionId: string, instruction: string) {
    if (topPanelActions[actionId]) {
      await openTopPanel(actionId, instruction);
      return;
    }
    if (preferenceActions[actionId]) {
      await applyPreference(actionId, instruction);
      return;
    }
    if (actionId === 'refresh_dashboard_snapshot') {
      await refreshDashboardFromXiaoyi(instruction);
      return;
    }
    if (actionId === 'run_linkage_health_check') {
      await runHealthCheckFromXiaoyi(instruction);
      return;
    }
    if (actionId === 'check_sailing_status') {
      await checkSailingStatusFromXiaoyi(instruction);
      return;
    }
    if (['summarize_runtime_state', 'prepare_runtime_handover', 'triage_runtime_alerts', 'explain_runtime_recommendation', 'create_runtime_recommendation'].includes(actionId)) {
      await runRuntimeInsightFromXiaoyi(actionId, instruction);
      return;
    }
    setCommand(instruction);
    setSelectedAction(actionId);
    if (actionId === 'start_xiaoyi_ai') {
      await launchXiaoyi();
    } else if (actionId === 'start_rl_training') {
      await startTraining();
    } else if (actionId === 'view_rl_training_status') {
      await showTrainingStatus();
    } else if (actionId === 'pause_rl_training') {
      await controlTraining('pause');
    } else if (actionId === 'resume_rl_training') {
      await controlTraining('resume');
    } else if (actionId === 'stop_rl_training') {
      await controlTraining('stop');
    } else if (actionId === 'run_policy_test') {
      await runPolicyTest();
    } else if (actionId === 'verify_policy_for_online') {
      await verifyPolicy();
    } else if (actionId === 'open_sailing_simulator') {
      await launchSailing();
    } else if (['start_navigation_demo', 'switch_ship_view', 'run_sailing_rl_smoke_test'].includes(actionId)) {
      await runSailingAction(actionId);
    } else {
      await askXiaoyi(instruction, actionId);
    }
  }

  function clearAssistant() {
    setCommand('');
    setSelectedAction('');
    setAnswer('');
    setPacket('等待指令。');
    setPendingPacket(null);
    setCommandCenterOpen(false);
    setCommandSearch('');
    setActiveCommandGroup('全部');
    setTrainingStudioOpen(false);
    setTrainingReviewOpen(false);
    setTrainingHistoryOpen(false);
    setAutomationMode('idle');
    setAutomationStepIndex(0);
    setStageModal(null);
    setClickSequence([]);
    setExecution('idle', 'idle', '等待输入或点击右侧指令清单。', {
      label: '等待舷鸥指令',
      group: 'AI调度',
      buttonLabel: '未选择',
      apiMethod: '—',
      apiPath: '—',
      confirmationRequired: false,
      resultSummary: '执行详情会展示识别意图、按钮/接口、确认状态和返回结果。',
      resultCode: 'waiting',
    });
  }

  function catalogCommand(item: CommandCatalogItem) {
    return item.id === 'start_rl_training' ? objective.command : item.command;
  }

  const trainingDurationSec = Number(trainingStatus?.estimated_duration_sec ?? trainingStatus?.duration_sec ?? 0);
  const trainingElapsedSec = Number(trainingStatus?.elapsed_sec ?? 0);
  const trainingState = String(trainingStatus?.status ?? 'idle');
  const trainingStateLabel = ({
    idle: '待命',
    running: '运行中',
    paused: '已暂停',
    stopped: '已停止',
    completed: '已完成',
    offline: '离线',
  } as Record<string, string>)[trainingState] ?? trainingState;
  const trainingCanPause = Boolean(trainingStatus?.can_pause ?? trainingState === 'running');
  const trainingCanResume = Boolean(trainingStatus?.can_resume ?? trainingState === 'paused');
  const trainingCanStop = Boolean(trainingStatus?.can_stop ?? ['running', 'paused'].includes(trainingState));
  const progress = Number(trainingStatus?.progress ?? 0);
  const visibleTrainingProgress = progress;
  const trainingProgressBarWidth = visibleTrainingProgress;
  const trainingProgressText = visibleTrainingProgress > 0 && visibleTrainingProgress < 1
    ? visibleTrainingProgress.toFixed(2)
    : visibleTrainingProgress.toFixed(1);
  const trainingRemainingSec = Number(trainingStatus?.remaining_sec ?? 0);
  const trainingEtaText = trainingStatus?.eta_at
    ? formatTrainingTime(trainingStatus.eta_at)
    : trainingState === 'paused'
      ? '暂停中'
      : trainingState === 'stopped'
        ? '已停止'
        : trainingState === 'completed'
          ? '已完成'
          : '等待启动';
  const trainingStartedText = formatTrainingTime(trainingStatus?.started_at);
  const trainingJobId = String(trainingStatus?.job_id ?? '等待启动');
  const trainingArtifactPath = String(trainingStatus?.artifact_path ?? '等待生成');
  const trainingStepRate = Number(trainingStatus?.step_rate_per_min ?? 0);
  const liveMetricSeries = Array.isArray(trainingStatus?.recent_metrics) ? trainingStatus.recent_metrics as JsonMap[] : [];
  const liveRewardPoints = chartPoints(liveMetricSeries, 'reward', 360, 92, 8);
  const liveActorLossPoints = chartPoints(liveMetricSeries, 'actor_loss', 360, 92, 8);
  const liveCriticLossPoints = chartPoints(liveMetricSeries, 'critic_loss', 360, 92, 8);
  const historySeries = Array.isArray(trainingHistory?.series) ? trainingHistory.series as JsonMap[] : [];
  const historyRewardPoints = chartPoints(historySeries, 'reward', 620, 190, 14);
  const historyRewardEmaPoints = chartPoints(historySeries, 'reward_ema', 620, 190, 14);
  const historyActorLossPoints = chartPoints(historySeries, 'actor_loss', 620, 190, 14);
  const historyCriticLossPoints = chartPoints(historySeries, 'critic_loss', 620, 190, 14);
  const historyEntropyPoints = chartPoints(historySeries, 'entropy', 620, 190, 14);
  const historySuccessPoints = chartPoints(historySeries, 'success_rate', 620, 190, 14);
  const latestHistoryValidation = [...historySeries].reverse().find((item) => typeof item.validation_return === 'number') ?? {};
  const firstHistoryPoint = historySeries[0] ?? {};
  const lastHistoryPoint = historySeries[historySeries.length - 1] ?? {};
  const businessEvidence = (trainingHistory?.business_evidence ?? {}) as JsonMap;
  const businessMetrics = (businessEvidence.metrics ?? {}) as JsonMap;
  const businessUncertainty = (businessEvidence.uncertainty ?? {}) as JsonMap;
  const objectiveHistory = Array.isArray(businessEvidence.objective_history)
    ? businessEvidence.objective_history as JsonMap[]
    : [];
  const activeObjectiveHistory = objectiveHistory.find((item) => item.id === selectedHistoryObjective)
    ?? objectiveHistory[0]
    ?? {};
  const activeObjectiveSeries = Array.isArray(activeObjectiveHistory.series)
    ? activeObjectiveHistory.series as JsonMap[]
    : [];
  const activeObjectivePoints = chartPoints(activeObjectiveSeries, 'value', 760, 230, 18);
  const activeObjectiveArea = chartAreaPoints(activeObjectiveSeries, 'value', 760, 230, 18);
  const objectiveTrainingRuns = Array.isArray(trainingHistory?.objective_training_runs)
    ? trainingHistory.objective_training_runs as JsonMap[]
    : [];
  const businessDatasetEvidence = (businessEvidence.dataset_evidence ?? {}) as JsonMap;
  const businessOfficialSources = Array.isArray(businessDatasetEvidence.official_sources)
    ? businessDatasetEvidence.official_sources as JsonMap[]
    : [];
  const businessDatasetQuality = (businessDatasetEvidence.quality ?? {}) as JsonMap;
  const businessDatasetSplit = (businessDatasetEvidence.split_policy ?? {}) as JsonMap;
  const carbonCi = (businessUncertainty.fixed_baseline_carbon_reduction_ci95 ?? {}) as JsonMap;
  const costCi = (businessUncertainty.fixed_baseline_cost_reduction_ci95 ?? {}) as JsonMap;
  const statusConfig = (trainingStatus?.config ?? {}) as JsonMap;
  const statusObjective = trainingObjectives.find((item) => item.id === statusConfig.objective_id);
  const statusAlgorithm = statusConfig.algorithm ? resolveAlgorithmProfile(String(statusConfig.algorithm)) : selectedAlgorithmProfile;

  return (
    <>
      <button
        ref={orbRef}
        className={`xiaoyi-orb${open ? ' has-drawer' : ''}${showOrbGreeting ? ' has-greeting' : ''}`}
        style={{ left: position.x, top: position.y }}
        type="button"
        title="打开舷鸥联动助手 / Open GullMate copilot"
        aria-label="打开舷鸥联动助手 / Open GullMate copilot"
        onPointerEnter={() => setShowOrbGreeting(true)}
        onPointerLeave={() => setShowOrbGreeting(false)}
        onFocus={() => setShowOrbGreeting(true)}
        onBlur={() => setShowOrbGreeting(false)}
        onPointerDown={(event) => {
          dragRef.current = { dx: event.clientX - position.x, dy: event.clientY - position.y, moved: false };
          suppressOrbClickRef.current = false;
          event.currentTarget.setPointerCapture(event.pointerId);
        }}
        onPointerMove={(event) => {
          if (!dragRef.current) return;
          const nextX = Math.max(10, Math.min(window.innerWidth - event.currentTarget.offsetWidth - 10, event.clientX - dragRef.current.dx));
          const nextY = Math.max(10, Math.min(window.innerHeight - event.currentTarget.offsetHeight - 10, event.clientY - dragRef.current.dy));
          if (Math.abs(nextX - position.x) > 3 || Math.abs(nextY - position.y) > 3) {
            dragRef.current.moved = true;
          }
          setPosition({
            x: nextX,
            y: nextY,
          });
        }}
        onPointerUp={(event) => {
          suppressOrbClickRef.current = Boolean(dragRef.current?.moved);
          dragRef.current = null;
          event.currentTarget.releasePointerCapture(event.pointerId);
        }}
        onPointerCancel={() => {
          dragRef.current = null;
        }}
        onClick={() => {
          if (suppressOrbClickRef.current) {
            suppressOrbClickRef.current = false;
            return;
          }
          setOpen(true);
        }}
      >
        <span className="xiaoyi-orb-speech" aria-hidden="true">
          <strong>您好！我是小鸥</strong>
          <small>您的港航智能助手 · MARITIME AI COPILOT</small>
          <span className="xiaoyi-orb-wave"><i /><i /><i /><i /><i /><i /><i /><i /><i /></span>
        </span>
        <img
          className="xiaoyi-orb-character"
          src="/assets/xiaoyi-maritime-officer.png"
          alt=""
          draggable={false}
        />
      </button>

      {open && (
        <section className="linkage-drawer" aria-label="舷鸥项目联动中枢">
          <div className="linkage-head">
            <div>
              <p>舷鸥 · GullMate · 能碳联动中枢 / Energy-Carbon Linkage Hub</p>
              <h2>把实时态势、预测建议、训练验证和审计接成一条链<small>One grounded flow for runtime insight, recommendations, training, validation, and audit.</small></h2>
            </div>
            <button id="btnCloseXiaoyi" className="icon-btn" type="button" onClick={() => setOpen(false)} aria-label="关闭舷鸥联动面板">
              <X size={18} />
            </button>
          </div>

          <div className="linkage-status-row">
            <span><Activity size={14} />{statusLabel(health, ['summary', 'runtime'], '实时闭环待检查')}</span>
            <span><Bot size={14} />{statusLabel(health, ['summary', 'xiaoyi'], '舷鸥待检查')}</span>
            <span><Gauge size={14} />{statusLabel(health, ['summary', 'rl'], 'RL待检查')}</span>
            <span><ShipWheel size={14} />{statusLabel(health, ['summary', 'sailing'], '航行模拟器待检查')}</span>
            <button type="button" disabled={busy} onClick={() => void runUiAction('refresh_linkage_status', refreshAll)}><RotateCw size={14} />刷新</button>
          </div>

          <div className={`output-locator ${outputLocator.tone}`}>
            <span><ServerCog size={15} />当前信息显示在</span>
            <b>{outputLocator.surface}</b>
            <em>{outputLocator.title} · {outputLocator.detail}</em>
          </div>

          <div className="linkage-grid">
            <div className="linkage-card assistant-card module-card module-assistant">
              <div className="linkage-card-title">
                <h3><Sparkles size={15} /> 舷鸥问答 / 指令 <small>GullMate Q&amp;A / COMMANDS</small></h3>
                <span className="module-chip">输入区 / INPUT · {busy ? 'typing' : 'ready'}</span>
              </div>
              <textarea
                id="xiaoyiCommandInput"
                value={command}
                disabled={busy}
                onChange={(event) => {
                  setCommand(event.target.value);
                  setSelectedAction('');
                  setPendingPacket(null);
                }}
                placeholder="例如：舷鸥，总结实时态势 / 舷鸥，生成交班摘要"
              />
              <select value={selectedAction} disabled={busy} onChange={(event) => { setSelectedAction(event.target.value); setPendingPacket(null); }}>
                <option value="">自动识别动作 / Auto-detect action</option>
                {commandCatalog.map((item) => (
                  <option value={item.id} key={item.id}>{item.group} · {item.label}</option>
                ))}
              </select>
              <div className="linkage-actions">
                <button id="btnXiaoyiStart" type="button" disabled={busy} onClick={() => void runUiAction('start_xiaoyi_ai', launchXiaoyi)}><Bot size={14} />启动舷鸥 / Start</button>
                <button id="btnXiaoyiRun" type="button" disabled={busy} onClick={() => void runUiAction('xiaoyi_intent', () => askXiaoyi())}><Send size={14} />识别并执行 / Run</button>
                <button id="btnXiaoyiConfirm" type="button" disabled={busy || !pendingPacket} onClick={() => void runUiAction('confirmed_action', confirmAction)}><Play size={14} />确认执行 / Confirm</button>
                <button id="btnXiaoyiClear" type="button" disabled={busy} onClick={clearAssistant}>清空 / Clear</button>
              </div>
              <div className="xiaoyi-command-targets" aria-label="舷鸥可视化按钮联动区 / GullMate visual action targets">
                <span><small>可视化按钮联动</small><b>VISUAL AUTO-CLICK TARGETS</b></span>
                <button id="btnXiaoyiOpenRuntimePanel" type="button" disabled={busy} onClick={() => void runCatalogAction('open_runtime_panel', '小鸥，打开实时闭环面板')}>实时 / Runtime</button>
                <button id="btnXiaoyiRuntimeSummary" type="button" disabled={busy} onClick={() => void runCatalogAction('summarize_runtime_state', '小鸥，总结当前实时态势')}>态势 / Summary</button>
                <button id="btnXiaoyiRuntimeHandover" type="button" disabled={busy} onClick={() => void runCatalogAction('prepare_runtime_handover', '小鸥，生成实时交班摘要')}>交班 / Handover</button>
                <button id="btnXiaoyiRuntimeTriage" type="button" disabled={busy} onClick={() => void runCatalogAction('triage_runtime_alerts', '小鸥，研判当前实时异常')}>研判 / Triage</button>
                <button id="btnXiaoyiRuntimeRecommend" type="button" disabled={busy} onClick={() => void runCatalogAction('create_runtime_recommendation', '小鸥，生成当前运行建议')}>建议 / Recommend</button>
                <button id="btnXiaoyiRuntimeExplain" type="button" disabled={busy} onClick={() => void runCatalogAction('explain_runtime_recommendation', '小鸥，解释最新运行建议')}>解释 / Explain</button>
                <button id="btnXiaoyiOpenSimulationPanel" type="button" disabled={busy} onClick={() => void runCatalogAction('open_simulation_panel', '小鸥，打开仿真在线面板')}>仿真 / Simulation</button>
                <button id="btnXiaoyiOpenMarlPanel" type="button" disabled={busy} onClick={() => void runCatalogAction('open_marl_panel', '小鸥，打开 RL 策略面板')}>RL / Policy</button>
                <button id="btnXiaoyiOpenCarbonPanel" type="button" disabled={busy} onClick={() => void runCatalogAction('open_carbon_panel', '小鸥，打开低碳优先面板')}>低碳 / Carbon</button>
                <button id="btnXiaoyiOpenShorePanel" type="button" disabled={busy} onClick={() => void runCatalogAction('open_shore_panel', '小鸥，打开岸电联动面板')}>岸电 / Shore</button>
                <button id="btnXiaoyiOpenApiPanel" type="button" disabled={busy} onClick={() => void runCatalogAction('open_api_panel', '小鸥，打开 API 同步面板')}>API / Health</button>
                <button id="btnXiaoyiRefreshDashboard" type="button" disabled={busy} onClick={() => void runCatalogAction('refresh_dashboard_snapshot', '小鸥，刷新仿真并重新同步仪表盘')}>刷新 / Refresh</button>
                <button id="btnXiaoyiHealthCheck" type="button" disabled={busy} onClick={() => void runCatalogAction('run_linkage_health_check', '小鸥，做一次联动健康检查')}>检查 / Check</button>
                <button id="btnXiaoyiCheckSailingStatus" type="button" disabled={busy} onClick={() => void runCatalogAction('check_sailing_status', '小鸥，检查航行模拟器状态')}>模拟器 / Simulator</button>
                <button id="btnXiaoyiPreferenceEfficiency" type="button" disabled={busy} onClick={() => void runCatalogAction('set_efficiency_priority', '小鸥，切到效率优先')}>效率 / Efficiency</button>
                <button id="btnXiaoyiPreferenceBalanced" type="button" disabled={busy} onClick={() => void runCatalogAction('set_balanced_dispatch', '小鸥，切到均衡调度')}>均衡 / Balanced</button>
                <button id="btnXiaoyiPreferenceLowCarbon" type="button" disabled={busy} onClick={() => void runCatalogAction('set_low_carbon_priority', '小鸥，切到低碳优先')}>低碳优先 / Low-carbon</button>
                <button id="btnXiaoyiPreferenceShorePower" type="button" disabled={busy} onClick={() => void runCatalogAction('set_shore_power_preference', '小鸥，切到岸电优先')}>岸电优先 / Shore first</button>
              </div>
              <div className="xiaoyi-answer">{answer}</div>
              <pre className="linkage-packet">{packet}</pre>
            </div>

            <div className="linkage-card rl-card module-card module-rl">
              <div className="linkage-card-title">
                <h3><Activity size={15} /> RL 训练 / 策略 <small>TRAINING / POLICY</small></h3>
                <span className={`module-chip training-state-${trainingState}`}>训练区 / TRAINING · {trainingStateLabel}</span>
              </div>
              <div className="training-config-label">
                <span>下次任务配置</span>
                <small>NEXT RUN CONFIG</small>
              </div>
              <div className="training-summary-panel">
                <span>
                  <small>优化目标</small>
                  <b>{objective.label}</b>
                  <em>{objective.reason}</em>
                </span>
                <span>
                  <small>算法 baseline</small>
                  <b>{selectedAlgorithmProfile.label}</b>
                  <em>{selectedAlgorithmProfile.tag} · {trainingParams.algorithm}</em>
                </span>
                <span>
                  <small>训练数据</small>
                  <b>{selectedDataFileProfile.label}</b>
                  <em>{trainingParams.data_file}</em>
                </span>
                <span>
                  <small>训练规模</small>
                  <b>{displayNumber(trainingParams.total_steps)} steps</b>
                  <em>{trainingParams.horizon_min}min · {trainingParams.guardrail_mode}</em>
                </span>
              </div>
              <div className="xiaoyi-algorithm-advisor" aria-label="舷鸥五算法训练顾问">
                <header>
                  <span><Bot size={13} />舷鸥训练顾问</span>
                  <b>五算法版本化环境契约</b>
                </header>
                <div>
                  {rlAlgorithms.map((algorithm) => (
                    <button
                      className={trainingParams.algorithm === algorithm.id ? 'active' : ''}
                      type="button"
                      key={algorithm.id}
                      disabled={trainingParams.data_file === 'port_la_2020_2024_hybrid_rl_hourly' && algorithm.id === 'dqn'}
                      title={trainingParams.data_file === 'port_la_2020_2024_hybrid_rl_hourly' && algorithm.id === 'dqn' ? 'v6 是 16 维连续动作环境，DQN 仅用于历史离散环境' : algorithm.description}
                      onClick={() => { if (!busy) applyAlgorithm(algorithm.id); }}
                    >
                      <b>{algorithm.label}</b>
                      <small>{algorithm.tag}</small>
                    </button>
                  ))}
                </div>
                <p>v6 默认采用“RL 战略残差 + 确定性控制/运筹投影”：16 个策略输出覆盖跨时段资源与船—泊—桥—场—车—能—检修协同；v1–v5 完整保留作纵向对照。</p>
              </div>
              <div className="training-progress-label">
                <span>训练进度</span>
                <b>{trainingProgressText}%</b>
              </div>
              <div className="training-progress">
                <div style={{ width: `${Math.min(100, Math.max(0, trainingProgressBarWidth))}%` }} />
              </div>
              <div className="training-runtime-panel">
                <span>
                  <small>预计总时长</small>
                  <b>{formatTrainingDuration(trainingDurationSec)}</b>
                </span>
                <span>
                  <small>已训练</small>
                  <b>{formatTrainingDuration(trainingElapsedSec)}</b>
                </span>
                <span>
                  <small>剩余时间</small>
                  <b>{formatTrainingDuration(trainingRemainingSec)}</b>
                </span>
                <span>
                  <small>预计完成</small>
                  <b>{trainingEtaText}</b>
                </span>
                <span>
                  <small>任务 ID</small>
                  <b>{trainingJobId}</b>
                </span>
                <span>
                  <small>开始时间</small>
                  <b>{trainingStartedText}</b>
                </span>
                <span className="wide">
                  <small>策略产物路径</small>
                  <b>{trainingArtifactPath}</b>
                </span>
                <span>
                  <small>训练速率</small>
                  <b>{trainingStepRate > 0 ? `${trainingStepRate} step/min` : '等待采样'}</b>
                </span>
              </div>
              <div className="training-metrics">
                <span>step <b>{trainingStatus?.step ?? 0}</b></span>
                <span>reward <b>{trainingStatus?.reward ?? 0}</b></span>
                <span>entropy <b>{trainingStatus?.entropy ?? 0}</b></span>
                <span>policy <b>{trainingStatus?.policy_version ?? '—'}</b></span>
              </div>
              <div className={`live-training-monitor ${trainingState === 'running' ? 'is-running' : ''}`}>
                <div className="live-training-head">
                  <span><i />实时训练指标 / LIVE TRAINING METRICS</span>
                  <em>{trainingStatus?.updated_at ? formatTrainingTime(trainingStatus.updated_at) : 'waiting'}</em>
                </div>
                <div className="live-training-chart">
                  <svg viewBox="0 0 360 92" preserveAspectRatio="none" aria-label="实时奖励值与损失滚动曲线">
                    {[18, 37, 56, 75].map((y) => <line x1="8" x2="352" y1={y} y2={y} key={y} />)}
                    {liveRewardPoints && <polyline className="reward-line" points={liveRewardPoints} />}
                    {liveActorLossPoints && <polyline className="actor-line" points={liveActorLossPoints} />}
                    {liveCriticLossPoints && <polyline className="critic-line" points={liveCriticLossPoints} />}
                  </svg>
                  <div className="live-chart-legend"><span className="reward">Reward</span><span className="actor">Actor loss</span><span className="critic">Critic loss</span></div>
                </div>
                <div className="live-training-values">
                  <span><small>Actor loss</small><b>{Number(trainingStatus?.actor_loss ?? 0).toFixed(4)}</b></span>
                  <span><small>Critic loss</small><b>{Number(trainingStatus?.critic_loss ?? 0).toFixed(4)}</b></span>
                  <span><small>KL divergence</small><b>{Number(trainingStatus?.kl_divergence ?? 0).toFixed(5)}</b></span>
                  <span><small>Success rate</small><b>{Number(trainingStatus?.success_rate ?? 0).toFixed(2)}%</b></span>
                  <span><small>Sampling</small><b>{Number(trainingStatus?.samples_per_sec ?? 0).toFixed(1)}/s</b></span>
                </div>
              </div>
              <div className="linkage-actions">
                <button id="btnOpenTrainingStudio" type="button" disabled={busy} onClick={() => openTrainingStudio(false)}><SlidersHorizontal size={14} />配置参数 / Configure</button>
                <button id="btnStartTraining" type="button" disabled={busy} onClick={() => void runUiAction('start_rl_training', () => startTraining())}><Play size={14} />启动训练 / Start</button>
                <button
                  id="btnPauseTraining"
                  type="button"
                  disabled={busy || (!trainingCanPause && !trainingCanResume)}
                  onClick={() => void runUiAction(trainingCanResume ? 'resume_rl_training' : 'pause_rl_training', () => controlTraining(trainingCanResume ? 'resume' : 'pause'))}
                >
                  {trainingCanResume ? <Play size={14} /> : <Pause size={14} />}
                  {trainingCanResume ? '继续训练 / Resume' : '暂停训练 / Pause'}
                </button>
                <button
                  id="btnStopTraining"
                  className="training-stop-action"
                  type="button"
                  disabled={busy || !trainingCanStop}
                  onClick={() => void runUiAction('stop_rl_training', () => controlTraining('stop'))}
                ><Square size={14} />停止 / Stop</button>
                <button id="btnTrainingStatus" type="button" disabled={busy} onClick={() => void runUiAction('view_rl_training_status', showTrainingStatus)}><Radio size={14} />状态 / Status</button>
                <button id="btnTrainingContract" type="button" disabled={busy} onClick={() => setTrainingContractOpen(true)}><ListChecks size={14} />训练契约 / MDP</button>
                <button id="btnTrainingHistory" type="button" disabled={busy} onClick={() => void openTrainingHistory()}><Gauge size={14} />历史收敛曲线 / Results</button>
                <button id="btnPolicyTest" type="button" disabled={busy} onClick={() => void runUiAction('run_policy_test', runPolicyTest)}><Gauge size={14} />登记测试 / Evidence</button>
                <button id="btnVerifyPolicy" type="button" disabled={busy} onClick={() => void runUiAction('verify_policy_for_online', verifyPolicy)}><ShieldCheck size={14} />上线验证 / Dry-run</button>
              </div>
              <pre className="mini-log">{(trainingStatus?.logs ?? ['等待训练指令。']).join('\n')}</pre>
            </div>

            <div className="linkage-card sailing-card module-card module-sailing">
              <div className="linkage-card-title">
                <h3><ShipWheel size={15} /> 航行模拟器 <small>SAILING SIMULATOR</small></h3>
                <span className="module-chip">模拟器区 / SIMULATOR · {sailingStatus?.process?.running ? `pid=${sailingStatus.process.pid}` : sailingStatus?.label ?? '待检查'}</span>
              </div>
              <div className="system-lines">
                <span>项目 <b>{sailingStatus?.project_root?.exists ? '已找到' : '未找到'}</b></span>
                <span>Godot <b>{sailingStatus?.godot_executable?.exists ? '可用' : '不可用'}</b></span>
                <span>模式 <b>{sailingStatus?.control_mode ?? 'launch'}</b></span>
              </div>
              <div className="linkage-actions stack">
                <button id="btnSailingLaunch" type="button" disabled={busy} onClick={() => void runUiAction('open_sailing_simulator', launchSailing)}><ShipWheel size={14} />启动模拟器 / Launch</button>
                <button id="btnSailingDemo" type="button" disabled={busy} onClick={() => void runUiAction('start_navigation_demo', () => runSailingAction('start_navigation_demo'))}>航线演示 / Route demo</button>
                <button id="btnShipView" type="button" disabled={busy} onClick={() => void runUiAction('switch_ship_view', () => runSailingAction('switch_ship_view'))}>船舶视角 / Ship view</button>
                <button id="btnSailingSmoke" type="button" disabled={busy} onClick={() => void runUiAction('run_sailing_rl_smoke_test', () => runSailingAction('run_sailing_rl_smoke_test'))}>Smoke test / 测试</button>
              </div>
              <div className="command-examples">
                <b>可说：</b>
                <span>启动模拟器</span>
                <span>开始训练岸电优先目标</span>
                <span>验证这个策略能不能上线</span>
              </div>
              <div className="linkage-log">
                {logs.length ? logs.map((item) => (
                  <p key={item.id}>
                    <small>{item.time} · {item.kind}</small>
                    <span>{item.message}</span>
                  </p>
                )) : <p><small>{now()} · READY</small><span>等待联动动作。</span></p>}
              </div>
            </div>

            <div className="linkage-card execution-card module-card module-execution">
              <div className="linkage-card-title">
                <h3><ServerCog size={15} /> AI 调度执行详情 <small>EXECUTION DETAIL</small></h3>
                <span className={`execution-state ${executionDetail.status}`}>{executionDetail.statusLabel}</span>
              </div>
              <div className="execution-flow">
                <span className={executionDetail.status !== 'idle' ? 'active' : ''}>识别 / Intent</span>
                <i />
                <span className={executionDetail.confirmationRequired ? 'active' : ''}>确认 / Confirm</span>
                <i />
                <span className={['executing', 'completed'].includes(executionDetail.status) ? 'active' : ''}>执行 / Execute</span>
                <i />
                <span className={executionDetail.status === 'completed' ? 'active' : ''}>结果 / Result</span>
              </div>
              {clickSequence.length > 0 && (
                <ol className="xiaoyi-click-sequence" aria-label="舷鸥逐步点击过程 / GullMate step-by-step click process">
                  {clickSequence.map((step, index) => (
                    <li className={`is-${step.status}`} key={`${step.selector}-${index}`}>
                      <b>{index + 1}</b><span>{step.label}</span><em>{step.status === 'pending' ? '等待 / Pending' : step.status === 'locating' ? '定位 / Locate' : step.status === 'clicking' ? '点击 / Click' : step.status === 'done' ? '完成 / Done' : '失败 / Failed'}</em>
                    </li>
                  ))}
                </ol>
              )}
              <div className="execution-detail-grid">
                <span>
                  <small>识别意图</small>
                  <b>{executionDetail.label}</b>
                  <em>{executionDetail.group} · {executionDetail.instruction}</em>
                </span>
                <span>
                  <small>按钮 / 接口</small>
                  <b>{executionDetail.buttonLabel}</b>
                  <em>{executionDetail.apiMethod} {executionDetail.apiPath}</em>
                </span>
                <span>
                  <small>人工确认</small>
                  <b>{executionDetail.confirmationRequired ? '需要确认' : '无需确认 / dry-run'}</b>
                  <em>{executionDetail.confirmationRequired ? '会等待用户点击确认或执行按钮' : '只读查询或本地安全执行'}</em>
                </span>
                <span>
                  <small>执行状态</small>
                  <b>{executionDetail.statusLabel}</b>
                  <em>{executionDetail.updatedAt}</em>
                </span>
              </div>
              <div className="execution-result-panel">
                <div>
                  {executionDetail.status === 'failed' ? <CircleAlert size={15} /> : <CheckCircle2 size={15} />}
                  <span>{executionDetail.resultSummary}</span>
                </div>
                <pre>{executionDetail.resultCode}</pre>
              </div>
            </div>

            <div className="linkage-card command-card module-card module-command">
              <div className="linkage-card-title">
                <h3><ListChecks size={15} /> 舷鸥指令中心</h3>
                <span className="module-chip">指令区 · {commandShortcuts.length} commands</span>
              </div>
              <div className="command-center-teaser">
                <span>
                  <small>优化目标训练</small>
                  <b>{trainingObjectives.length} 个目标已生成快捷指令</b>
                </span>
                <span>
                  <small>全部指令</small>
                  <b>{commandShortcuts.length} 条可搜索 / 可直接执行</b>
                </span>
                <button id="btnOpenCommandCenter" type="button" onClick={() => setCommandCenterOpen(true)}><ListChecks size={14} />打开指令中心</button>
              </div>
              <div className="objective-command-strip">
                {trainingObjectives.map((profile) => (
                  <button
                    key={profile.id}
                    type="button"
                    disabled={busy}
                    onClick={() => void runUiAction('start_rl_training', () => executeCommandShortcut({
                      id: `train_${profile.id}`,
                      label: `训练：${profile.label}`,
                      group: '优化目标训练',
                      command: profile.command,
                      actionId: 'start_rl_training',
                      objectiveId: profile.id,
                      badge: resolveAlgorithmProfile(profile.algorithm).label,
                      description: profile.reason,
                    }))}
                  >
                    {profile.label}
                  </button>
                ))}
              </div>
            </div>
          </div>
        </section>
      )}

      {trainingHistoryOpen && (
        <section className="training-history-backdrop" aria-label="历史强化学习训练结果">
          <div className="training-history-modal" role="dialog" aria-modal="true">
            <div className="training-history-head">
              <div>
                <p>PREVIOUS OFFLINE RL RUN · REPRODUCIBLE EVIDENCE</p>
                <h2>历史训练收敛结果 <small>Historical Training Convergence</small></h2>
              </div>
              <button id="btnCloseTrainingHistory" className="icon-btn" type="button" onClick={() => setTrainingHistoryOpen(false)} aria-label="关闭历史训练结果"><X size={18} /></button>
            </div>
            {trainingHistoryError && <div className="training-history-loading" role="alert">读取失败：{trainingHistoryError} <button type="button" onClick={() => void openTrainingHistory()}>重试读取</button></div>}
            {trainingHistoryLoading && (
              <div className="training-history-loading">
                <div className="history-loading-orbit"><i /><i /><i /><Activity size={24} /></div>
                <b>正在组装 RL 多目标价值证据</b>
                <span>learner 轨迹 → 独立测试集 → 业务指标</span>
                <div className="history-loading-track"><i /></div>
              </div>
            )}
            {trainingHistory && (
              <>
                <div className="training-evidence-banner">
                  <span><b>{trainingHistory.title}</b><small>{trainingHistory.title_en}</small></span>
                  <em>公开数据集 + 固定种子 / PUBLIC DATA + FIXED SEED</em>
                  <strong>非生产遥测 / NOT PRODUCTION TELEMETRY</strong>
                </div>
                {objectiveHistory.length > 0 && (
                  <section className="objective-history-stage" aria-label="RL 多目标业务价值历史">
                    <header>
                      <div>
                        <span><Sparkles size={15} />RL BUSINESS VALUE MATRIX</span>
                        <h3>RL 能优化哪些港口业务</h3>
                        <p>五个业务目标、五组历史曲线；点击卡片可切换大图与价值指标。</p>
                      </div>
                      <button type="button" className={historyAutoPlay ? 'is-running' : ''} onClick={() => setHistoryAutoPlay((value) => !value)}>
                        <Radio size={13} />{historyAutoPlay ? '自动轮播中' : '继续轮播'}
                      </button>
                    </header>
                    <div className="objective-history-grid">
                      {objectiveHistory.map((item) => {
                        const itemSeries = Array.isArray(item.series) ? item.series as JsonMap[] : [];
                        const itemPoints = chartPoints(itemSeries, 'value', 190, 66, 7);
                        const active = item.id === activeObjectiveHistory.id;
                        return (
                          <button
                            type="button"
                            className={active ? 'is-active' : ''}
                            style={{ borderColor: active ? String(item.accent) : undefined }}
                            onClick={() => {
                              setSelectedHistoryObjective(String(item.id));
                              setHistoryAutoPlay(false);
                            }}
                            key={String(item.id)}
                          >
                            <span><b>{item.label}</b><em>{item.algorithm}</em></span>
                            <svg viewBox="0 0 190 66" preserveAspectRatio="none" aria-label={`${item.label}历史业务曲线`}>
                              {[18, 34, 50].map((y) => <line x1="7" x2="183" y1={y} y2={y} key={y} />)}
                              <polyline points={itemPoints} style={{ stroke: String(item.accent) }} />
                            </svg>
                            <strong style={{ color: String(item.accent) }}>{compactMetric(item.value)}{item.unit}</strong>
                            <small>{item.metric_label}</small>
                          </button>
                        );
                      })}
                    </div>
                    <div className="objective-history-focus" style={{ borderColor: String(activeObjectiveHistory.accent ?? '#50edcb') }}>
                      <article className="objective-value-hero">
                        <span>当前目标 / ACTIVE OBJECTIVE</span>
                        <h4>{activeObjectiveHistory.label}</h4>
                        <strong style={{ color: String(activeObjectiveHistory.accent ?? '#50edcb') }}>
                          {compactMetric(activeObjectiveHistory.value)}<small>{activeObjectiveHistory.unit}</small>
                        </strong>
                        <b>{activeObjectiveHistory.metric_label}</b>
                        <p>{activeObjectiveHistory.business_scope}</p>
                        <footer><em>建议算法 {activeObjectiveHistory.algorithm}</em><em>实测策略 {businessEvidence.algorithm}</em></footer>
                      </article>
                      <article className="objective-value-chart">
                        <header><span>12 个月度历史测试曲线</span><small>{businessEvidence.history_windows ?? '—'} independent windows</small></header>
                        <svg viewBox="0 0 760 230" preserveAspectRatio="none" aria-label={`${activeObjectiveHistory.label}月度历史测试曲线`}>
                          <defs>
                            <linearGradient id="objectiveCurveArea" x1="0" y1="0" x2="0" y2="1">
                              <stop offset="0%" stopColor={String(activeObjectiveHistory.accent ?? '#50edcb')} stopOpacity="0.42" />
                              <stop offset="100%" stopColor={String(activeObjectiveHistory.accent ?? '#50edcb')} stopOpacity="0.02" />
                            </linearGradient>
                          </defs>
                          {[46, 92, 138, 184].map((y) => <line x1="18" x2="742" y1={y} y2={y} key={y} />)}
                          <polygon points={activeObjectiveArea} fill="url(#objectiveCurveArea)" />
                          <polyline className="objective-focus-line" points={activeObjectivePoints} style={{ stroke: String(activeObjectiveHistory.accent ?? '#50edcb') }} />
                        </svg>
                        <footer><span>{activeObjectiveSeries[0]?.period ?? 'TEST'}</span><em>{activeObjectiveHistory.metric_label}</em><span>{activeObjectiveSeries[activeObjectiveSeries.length - 1]?.period ?? 'TEST'}</span></footer>
                      </article>
                      <aside>
                        <span>BUSINESS VALUE</span>
                        {(activeObjectiveHistory.supporting_metrics ?? []).map((metric: JsonMap) => (
                          <div key={String(metric.label)}><small>{metric.label}</small><b>{compactMetric(metric.value)}{metric.unit}</b><i style={{ width: `${Math.min(100, Math.max(4, Math.abs(Number(metric.value) || 0)))}%`, background: String(activeObjectiveHistory.accent ?? '#50edcb') }} /></div>
                        ))}
                        <p>五个视图来自同一已登记策略的独立测试集，不冒充五次独立训练。</p>
                      </aside>
                    </div>
                    {objectiveTrainingRuns.length > 0 && (
                      <div className="learner-objective-runs">
                        <header><span><Activity size={14} />已完成的真实 learner 目标轨迹</span><b>{objectiveTrainingRuns.length} runs · persisted callbacks</b></header>
                        <div>
                          {objectiveTrainingRuns.map((run) => {
                            const runSeries = Array.isArray(run.series) ? run.series as JsonMap[] : [];
                            const runPoints = chartPoints(runSeries, 'reward_ema', 330, 86, 8) || chartPoints(runSeries, 'reward', 330, 86, 8);
                            return (
                              <article key={String(run.run_id)}>
                                <span><b>{run.objective_label}</b><em>{run.algorithm} · {Number(run.total_steps).toLocaleString()} steps</em></span>
                                <svg viewBox="0 0 330 86" preserveAspectRatio="none" aria-label={`${run.objective_label} learner 收敛曲线`}>
                                  {[22, 43, 64].map((y) => <line x1="8" x2="322" y1={y} y2={y} key={y} />)}
                                  <polyline points={runPoints} />
                                </svg>
                                <small>{runSeries.length} callback points · {run.run_id}</small>
                              </article>
                            );
                          })}
                        </div>
                      </div>
                    )}
                  </section>
                )}
                {businessOfficialSources.length > 0 && (
                  <section className="official-dataset-proof" aria-label="训练与测试数据集官方来源">
                    <header>
                      <div><ShieldCheck size={16} /><span><b>数据集官方来源</b><small>OFFICIAL PUBLIC-DATA PROVENANCE</small></span></div>
                      <strong>{businessDatasetQuality.rows ? Number(businessDatasetQuality.rows).toLocaleString() : '—'} hourly rows · SHA {String(businessEvidence.dataset_sha256 ?? '').slice(0, 12)}</strong>
                    </header>
                    <h3>{businessDatasetEvidence.name}</h3>
                    <div className="official-source-grid">
                      {businessOfficialSources.map((source) => (
                        <a href={String(source.url)} target="_blank" rel="noreferrer" key={String(source.publisher)}>
                          <i />
                          <span><b>{source.publisher}</b><small>{source.role}</small></span>
                          <em>官方源 ↗</em>
                        </a>
                      ))}
                    </div>
                    <footer>
                      <span>TRAIN {businessDatasetSplit.train ?? '按时间划分'}</span>
                      <span>VALIDATION {businessDatasetSplit.validation ?? '按时间划分'}</span>
                      <span>TEST {businessDatasetSplit.test ?? businessEvidence.split}</span>
                      <strong>{businessDatasetEvidence.scope_note}</strong>
                    </footer>
                  </section>
                )}
                <div className="training-evidence-meta">
                  <span><small>Run ID</small><b>{trainingHistory.run_id}</b></span>
                  <span><small>Environment</small><b>{trainingHistory.environment}</b></span>
                  <span><small>Algorithm / Seed</small><b>{trainingHistory.algorithm} · {trainingHistory.seed}</b></span>
                  <span><small>Scale / Duration</small><b>{Number(trainingHistory.total_steps).toLocaleString()} steps · {Math.round(Number(trainingHistory.duration_sec) / 60)} min</b></span>
                  <span><small>Checkpoint</small><b>{trainingHistory.checkpoint}</b></span>
                </div>
                <div className="training-trace-proof">
                  <span><i />可视化记录 <b>{Number(trainingHistory.recorded_callback_points ?? historySeries.length).toLocaleString()}</b> 个 learner callback 点</span>
                  <small>优先选择已保存的最完整训练轨迹，避免新建任务只有 1 个点时“有数据但看不到曲线”。</small>
                </div>
                <div className="training-result-metrics">
                  <span><small>Best callback reward</small><b>{trainingHistory.metrics?.best_callback_reward ?? '—'}</b></span>
                  <span><small>Last-20 callback mean</small><b>{trainingHistory.metrics?.mean_last_20_callback_reward ?? '—'}</b></span>
                  <span><small>Reward EMA start</small><b>{Number(firstHistoryPoint.reward_ema ?? 0).toFixed(4)}</b></span>
                  <span><small>Reward EMA final</small><b>{Number(lastHistoryPoint.reward_ema ?? 0).toFixed(4)}</b></span>
                  <span><small>Validation return</small><b>{latestHistoryValidation.validation_return ?? '—'}</b></span>
                  <span className="safe"><small>Validation violations</small><b>{latestHistoryValidation.validation_safety_violations ?? '—'}</b></span>
                  <span><small>Callback points</small><b>{historySeries.length}</b></span>
                </div>
                <div className="training-history-charts">
                  <article>
                    <header><span>Episode Reward 收敛</span><small>raw return + EMA</small></header>
                    <svg viewBox="0 0 620 190" preserveAspectRatio="none" aria-label="历史训练奖励收敛曲线">
                      {[35, 72, 109, 146].map((y) => <line x1="14" x2="606" y1={y} y2={y} key={y} />)}
                      <polyline className="history-reward-raw" points={historyRewardPoints} />
                      <polyline className="history-reward-ema" points={historyRewardEmaPoints} />
                    </svg>
                    <footer><span className="raw">Episode return</span><span className="ema">EMA smoothed</span><em>0 → {Number(trainingHistory.total_steps).toLocaleString()} steps</em></footer>
                  </article>
                  <article>
                    <header><span>Actor / Critic Loss</span><small>optimization stability</small></header>
                    <svg viewBox="0 0 620 190" preserveAspectRatio="none" aria-label="历史训练损失收敛曲线">
                      {[35, 72, 109, 146].map((y) => <line x1="14" x2="606" y1={y} y2={y} key={y} />)}
                      <polyline className="history-actor-loss" points={historyActorLossPoints} />
                      <polyline className="history-critic-loss" points={historyCriticLossPoints} />
                    </svg>
                    <footer><span className="actor">Actor loss</span><span className="critic">Critic loss</span><em>来自 learner logger 的实测值</em></footer>
                  </article>
                  <article>
                    <header><span>探索与成功率</span><small>Entropy + success rate · normalized</small></header>
                    <svg viewBox="0 0 620 190" preserveAspectRatio="none" aria-label="历史训练探索度与成功率曲线">
                      {[35, 72, 109, 146].map((y) => <line x1="14" x2="606" y1={y} y2={y} key={y} />)}
                      <polyline className="history-entropy" points={historyEntropyPoints} />
                      <polyline className="history-success" points={historySuccessPoints} />
                    </svg>
                    <footer><span className="entropy">Entropy</span><span className="success">Constraint success</span><em>未记录的指标不绘制</em></footer>
                  </article>
                  <article className="checkpoint-evidence">
                    <header><span>Checkpoint 选择证据</span><small>evaluation checkpoints</small></header>
                    <div className="checkpoint-table">
                      {(trainingHistory.checkpoints ?? []).map((item: JsonMap, index: number) => (
                        <span key={`${item.step}-${item.path ?? index}`}>
                          <b>{Number(item.step).toLocaleString()}</b>
                          <em>validation {item.validation_return ?? '—'}</em>
                          <em>violations {item.validation_safety_violations ?? '—'}</em>
                          <small>{String(item.path ?? '').split('/').pop()}</small>
                        </span>
                      ))}
                    </div>
                    <p>本区只展示实际 learner callback、训练集无渲染评估和真实保存的 checkpoint；留出测试集必须在训练完成后单独测试才生成回放轨迹。</p>
                  </article>
                </div>
                {businessEvidence.strategy_id && (
                  <section className="business-evidence-panel" aria-label="独立留出集业务价值证据">
                    <header>
                      <span><ShieldCheck size={16} />独立留出集业务价值</span>
                      <b>{businessEvidence.algorithm} · TEST · {businessMetrics.test_episodes ?? '—'} episodes</b>
                    </header>
                    <p>本区来自最近已登记策略的独立测试集评估，与上方 DQN learner 收敛轨迹分开，不将两次实验冒充为同一次结果。</p>
                    <div>
                      <span><small>碳排降低 vs 固定资源基线</small><b>{Number(businessMetrics.fixed_baseline_carbon_reduction_pct ?? 0).toFixed(3)}%</b><em>95% CI {Number(carbonCi.ci95_low_pct ?? 0).toFixed(3)}–{Number(carbonCi.ci95_high_pct ?? 0).toFixed(3)}%</em></span>
                      <span><small>成本节省 vs 固定资源基线</small><b>{Number(businessMetrics.fixed_baseline_cost_saving_pct ?? 0).toFixed(3)}%</b><em>95% CI {Number(costCi.ci95_low_pct ?? 0).toFixed(3)}–{Number(costCi.ci95_high_pct ?? 0).toFixed(3)}%</em></span>
                      <span><small>峰值变化</small><b>{Number(businessMetrics.fixed_baseline_peak_change_pct ?? 0).toFixed(3)}%</b><em>负值代表降峰</em></span>
                      <span><small>约束成功率</small><b>{Number(businessMetrics.constraint_success_rate_pct ?? 0).toFixed(1)}%</b><em>safety violations {businessMetrics.safety_violations ?? '—'}</em></span>
                    </div>
                    <footer><span>{businessEvidence.policy_version}</span><span>{businessEvidence.dataset_id} / {businessEvidence.split}</span><strong>PRODUCTION DISPATCH: DISABLED</strong></footer>
                  </section>
                )}
              </>
            )}
          </div>
        </section>
      )}

      {trainingStatusOpen && (
        <section className="training-status-backdrop" aria-label="训练状态全景面板">
          <div className="training-status-modal" role="dialog" aria-modal="true">
            <div className="training-history-head">
              <div><p>LIVE TRAINING OBSERVABILITY</p><h2>当前训练状态 <small>Current Training Status</small></h2></div>
              <button id="btnCloseTrainingStatus" className="icon-btn" type="button" onClick={() => setTrainingStatusOpen(false)} aria-label="关闭训练状态"><X size={18} /></button>
            </div>
            <div className={`training-status-hero state-${trainingState}`}>
              <div className="training-status-ring" style={{ '--training-progress': `${Math.min(100, Math.max(0, trainingProgressBarWidth)) * 3.6}deg` } as React.CSSProperties}>
                <span><b>{trainingProgressText}%</b><small>{trainingStateLabel}</small></span>
              </div>
              <div>
                <span><i />{trainingState === 'running' ? '训练正在进行' : '训练任务快照'}</span>
                <h3>{statusObjective?.label ?? objective.label} · {statusAlgorithm.label}</h3>
                <p>{trainingStatus?.summary ?? '尚未启动新任务；面板保留已读取的最新状态。'}</p>
                <div className="training-status-track"><i style={{ width: `${Math.min(100, Math.max(0, trainingProgressBarWidth))}%` }} /></div>
              </div>
            </div>
            <div className="training-status-kpis">
              <span><small>STEP / TOTAL</small><b>{Number(trainingStatus?.step ?? 0).toLocaleString()} / {Number(trainingStatus?.total_steps ?? trainingParams.total_steps).toLocaleString()}</b></span>
              <span><small>REWARD</small><b>{Number(trainingStatus?.reward ?? 0).toFixed(4)}</b></span>
              <span><small>ENTROPY</small><b>{Number(trainingStatus?.entropy ?? 0).toFixed(4)}</b></span>
              <span><small>SUCCESS</small><b>{Number(trainingStatus?.success_rate ?? 0).toFixed(2)}%</b></span>
              <span><small>SAMPLING</small><b>{Number(trainingStatus?.samples_per_sec ?? trainingStatus?.sampling_steps_per_sec ?? 0).toFixed(1)}/s</b></span>
              <span><small>ETA</small><b>{trainingEtaText}</b></span>
            </div>
            <div className="training-status-body">
              <article>
                <header><span>实时学习曲线</span><small>{liveMetricSeries.length} recent points</small></header>
                <svg viewBox="0 0 620 190" preserveAspectRatio="none" aria-label="当前训练实时曲线">
                  {[35, 72, 109, 146].map((y) => <line x1="14" x2="606" y1={y} y2={y} key={y} />)}
                  {chartPoints(liveMetricSeries, 'reward', 620, 190, 14) && <polyline className="history-reward-ema" points={chartPoints(liveMetricSeries, 'reward', 620, 190, 14)} />}
                  {chartPoints(liveMetricSeries, 'actor_loss', 620, 190, 14) && <polyline className="history-actor-loss" points={chartPoints(liveMetricSeries, 'actor_loss', 620, 190, 14)} />}
                  {chartPoints(liveMetricSeries, 'critic_loss', 620, 190, 14) && <polyline className="history-critic-loss" points={chartPoints(liveMetricSeries, 'critic_loss', 620, 190, 14)} />}
                </svg>
              </article>
              <article className="training-status-details">
                <span><small>Job ID</small><b>{trainingJobId}</b></span>
                <span><small>Policy</small><b>{trainingStatus?.policy_version ?? '—'}</b></span>
                <span><small>Dataset</small><b>{statusConfig.dataset_id ?? statusConfig.data_file ?? trainingParams.data_file}</b></span>
                <span><small>Actor / Critic</small><b>{Number(trainingStatus?.actor_loss ?? 0).toFixed(4)} / {Number(trainingStatus?.critic_loss ?? 0).toFixed(4)}</b></span>
                <span><small>Started / ETA</small><b>{trainingStartedText} / {trainingEtaText}</b></span>
                <span><small>Authority</small><b>OFFLINE + DRY-RUN ONLY</b></span>
              </article>
            </div>
          </div>
        </section>
      )}

      {trainingContractOpen && (
        <section className="training-contract-backdrop" aria-label="训练数据集与 MDP 契约">
          <div className="training-contract-modal" role="dialog" aria-modal="true">
            <div className="training-history-head">
              <div><p>DATASET · STATE · ACTION · REWARD</p><h2>训练数据与 MDP 契约 <small>Training Contract</small></h2></div>
              <button id="btnCloseTrainingContract" className="icon-btn" type="button" onClick={() => setTrainingContractOpen(false)} aria-label="关闭训练契约"><X size={18} /></button>
            </div>
            <section className="contract-dataset-card">
              <header><span><ServerCog size={16} />当前训练数据集</span><b>43,848 hourly anchors</b></header>
              <h3>{selectedDataFileProfile.label}</h3>
              <code>{selectedDataFileProfile.path}</code>
              <p>{selectedDataFileProfile.description}</p>
              <footer><span>scenario: {selectedDataFileProfile.scenario}</span><span>asset group: {selectedDataFileProfile.assetGroup}</span><strong>公开锚点 + 可替换工程情景，非生产遥测</strong></footer>
            </section>
            <div className="contract-dimensions"><span><b>106</b><small>STATE</small></span><i>→</i><span><b>16</b><small>ACTION</small></span><i>→</i><span><b>{Object.keys(trainingParams.reward_weights).length}</b><small>REWARD TERMS</small></span></div>
            <div className="contract-columns">
              <article><header><b>State · 106维因果观测</b><small>只使用当前及过去可知信息</small></header>{hybridStateContract.map(([dimension, name, detail]) => <span key={name}><strong>{dimension}</strong><b>{name}</b><small>{detail}</small></span>)}</article>
              <article><header><b>Action · 16维连续输出</b><small>RL 残差 + 确定性硬约束投影</small></header>{hybridActionContract.map(([dimension, detail]) => <span key={dimension}><strong>{dimension}</strong><b>{dimension.includes('10') ? '资源控制' : '调度排序'}</b><small>{detail}</small></span>)}</article>
              <article className="contract-reward"><header><b>Reward · 多目标约束奖励</b><small>吞吐奖励 + 监管服务奖励 + 硬安全约束</small></header><div>{Object.entries(trainingParams.reward_weights).map(([key, value]) => <span key={key}><small>{rewardWeightLabels[key] ?? key}</small><b>{Number(value).toFixed(3)}</b><i style={{ width: `${Math.min(100, Number(value) * 240)}%` }} /></span>)}</div></article>
            </div>
            <footer className="contract-boundary"><ShieldCheck size={15} />策略不能绕过岸电、安全、设备与调度硬约束；演示仅生成离线策略、留出集证据和 dry-run，生产下发关闭。</footer>
          </div>
        </section>
      )}

      {trainingStudioOpen && (
        <section className="training-studio-backdrop" aria-label="强化学习训练配置工作台">
          <div className="training-studio-modal" role="dialog" aria-modal="true">
            <div className="training-studio-head">
              <div>
                <p>RL Training Studio · 舷鸥训练前确认</p>
                <h2>强化学习训练配置工作台</h2>
              </div>
              <div className="training-studio-head-actions">
                <span>{automationMode === 'xiaoyi' ? 'GullMate AUTO-CLICK' : trainingReviewOpen ? 'MANUAL CONFIRM' : 'PARAM EDIT'}</span>
                <button className="icon-btn" type="button" onClick={() => {
                  setTrainingStudioOpen(false);
                  setStageModal(null);
                }} aria-label="关闭训练配置工作台">
                  <X size={18} />
                </button>
              </div>
            </div>

            <div className={`xiaoyi-automation-console ${automationMode === 'xiaoyi' ? 'is-running' : ''}`}>
              <div className="automation-console-title">
                <span><Bot size={15} />舷鸥智能执行流程</span>
                <b>{automationSteps[Math.min(automationStepIndex, automationSteps.length - 1)]?.label ?? '等待动作'}</b>
              </div>
              <div className="automation-step-rail">
                {automationSteps.map((step, index) => (
                  <span
                    className={index < automationStepIndex ? 'done' : index === automationStepIndex ? 'active' : ''}
                    key={step.id}
                  >
                    <i>{index + 1}</i>
                    <b>{step.label}</b>
                    <small>{step.detail}</small>
                  </span>
                ))}
              </div>
            </div>

            <div className="training-studio-grid">
              <section className="training-studio-section training-studio-config">
                <div className="studio-section-title">
                  <h3><SlidersHorizontal size={15} />训练前参数调整</h3>
                  <span>{displayNumber(trainingParams.total_steps)} steps</span>
                </div>
                <div className="training-config-panel studio-select-grid">
                  <label>
                    <small>优化目标</small>
                    <select id="trainingObjectiveSelect" disabled={busy} value={selectedObjective} onChange={(event) => selectTrainingObjective(event.target.value)}>
                      {trainingObjectives.map((item) => (
                        <option value={item.id} key={item.id}>{item.label}</option>
                      ))}
                    </select>
                    <em>{objective.reason}</em>
                  </label>
                  <label>
                    <small>3种v6 RL / 1种历史RL / 1种控制基线</small>
                    <select id="trainingAlgorithmSelect" disabled={busy} value={trainingParams.algorithm} onChange={(event) => applyAlgorithm(event.target.value)}>
                      {rlAlgorithms.map((item) => (
                        <option
                          value={item.id}
                          key={item.id}
                          disabled={trainingParams.data_file === 'port_la_2020_2024_hybrid_rl_hourly' && item.id === 'dqn'}
                        >{item.label} · {item.tag}{trainingParams.data_file === 'port_la_2020_2024_hybrid_rl_hourly' && item.id === 'dqn' ? ' · v6不适用' : ''}</option>
                      ))}
                    </select>
                    <em>{selectedAlgorithmProfile.description}</em>
                  </label>
                  <label>
                    <small>训练数据文件</small>
                      <input
                        id="trainingDataSelect"
                        disabled={busy}
                        list="trainingDataOptions"
                        value={trainingParams.data_file}
                        onChange={(event) => {
                          setTrainingReviewOpen(false);
                          const value = event.target.value;
                          const dataFile = trainingDataFiles.find((item) => item.path === value);
                          setTrainingParams((current) => ({
                            ...current,
                            algorithm: value === 'port_la_2020_2024_hybrid_rl_hourly' && current.algorithm === 'dqn' ? 'ppo' : current.algorithm,
                            data_file: value,
                            scenario: dataFile?.scenario ?? current.scenario,
                            asset_group: dataFile?.assetGroup ?? current.asset_group,
                            reward_weights: alignRewardWeightsForDataset(current.reward_weights, value),
                          }));
                        }}
                      />
                      <datalist id="trainingDataOptions">
                        {trainingDataFiles.map((item) => (
                          <option value={item.path} key={item.id}>{item.label} · {item.path}</option>
                        ))}
                      </datalist>
                    <em>{selectedDataFileProfile.description} 也可输入后端已注册数据集 ID；绝对路径与任意 CSV 会被拒绝。</em>
                  </label>
                </div>

                <div className="training-string-grid studio-string-grid">
                  <label>
                    <small>仿真场景</small>
                    <input
                      value={trainingParams.scenario}
                      disabled={busy} onChange={(event) => { setTrainingReviewOpen(false); setTrainingParams((current) => ({ ...current, scenario: event.target.value })); }}
                    />
                  </label>
                  <label>
                    <small>资产组</small>
                    <input
                      value={trainingParams.asset_group}
                      disabled={busy} onChange={(event) => { setTrainingReviewOpen(false); setTrainingParams((current) => ({ ...current, asset_group: event.target.value })); }}
                    />
                  </label>
                  <label>
                    <small>安全护栏</small>
                      <input value="strict · dataset-declared environment constraints" readOnly />
                      <em>按数据包声明的 v1–v6 环境合同执行硬约束，固定 60 分钟 step；v6 的确定性投影不可被策略绕过。</em>
                  </label>
                </div>

                <div className="studio-subtitle">全部训练参数</div>
                <div className="training-param-grid studio-param-grid">
                  {trainingParamFields.map((field) => (
                    <label key={field.key}>
                      <small>{field.label}</small>
                      <input
                        type="number"
                        disabled={busy}
                        min={field.min}
                        max={field.max}
                        step={field.step}
                        value={trainingParams[field.key]}
                        onChange={(event) => updateTrainingNumber(field.key, event.target.value)}
                      />
                    </label>
                  ))}
                </div>

                <div className="studio-subtitle">Reward Weights</div>
                <div className="reward-weight-editor studio-reward-grid">
                  {Object.entries(rewardWeightLabels)
                    .filter(([key]) => (
                      trainingParams.data_file === 'port_la_2020_2024_hybrid_rl_hourly'
                        ? hybridRewardWeightKeys.has(key)
                        : trainingParams.data_file === 'port_la_2020_2024_operational_flex_hourly'
                          ? flexRewardWeightKeys.has(key)
                          : legacyRewardWeightKeys.has(key)
                    ))
                    .map(([key, label]) => (
                    <label key={key}>
                      <small>{label}</small>
                      <input
                        type="number"
                        disabled={busy}
                        min="0"
                        max="1"
                        step="0.01"
                        value={trainingParams.reward_weights[key] ?? 0}
                        onChange={(event) => updateRewardWeight(key, event.target.value)}
                      />
                    </label>
                    ))}
                </div>
              </section>

              <aside className="training-studio-section training-studio-review">
                <div className="studio-section-title">
                  <h3><ShieldCheck size={15} />训练前人工确认</h3>
                  <span>{trainingReviewOpen ? 'CONFIRM' : 'PREVIEW'}</span>
                </div>
                <div className="training-review-summary studio-review-summary">
                  <span>
                    <small>优化目标</small>
                    <b>{trainingDraftConfig.objective_label}</b>
                    <em>{trainingDraftConfig.objective_reason}</em>
                  </span>
                  <span>
                    <small>算法</small>
                    <b>{trainingDraftConfig.algorithm_label}</b>
                    <em>{trainingDraftConfig.algorithm_tag} · {trainingDraftConfig.algorithm}</em>
                  </span>
                  <span>
                    <small>训练数据</small>
                    <b>{trainingDraftConfig.data_label}</b>
                    <em>{trainingDraftConfig.data_file}</em>
                  </span>
                  <span>
                    <small>安全护栏</small>
                    <b>{trainingDraftConfig.guardrail_mode}</b>
                    <em>上线前必须通过 dry-run 验证</em>
                  </span>
                </div>
                <div className="training-review-grid studio-review-grid">
                  {[
                    ['objective_id', trainingDraftConfig.objective_id],
                    ['horizon_min', trainingDraftConfig.horizon_min],
                    ['step_min', trainingDraftConfig.step_min],
                    ['total_steps', trainingDraftConfig.total_steps],
                    ['batch_size', trainingDraftConfig.batch_size],
                    ['learning_rate', trainingDraftConfig.learning_rate],
                    ['gamma', trainingDraftConfig.gamma],
                    ['tau', trainingDraftConfig.tau],
                    ['entropy_coef', trainingDraftConfig.entropy_coef],
                    ['seed', trainingDraftConfig.seed],
                    ['eval_interval', trainingDraftConfig.eval_interval],
                    ['checkpoint_interval', trainingDraftConfig.checkpoint_interval],
                  ].map(([label, value]) => (
                    <span key={label}>
                      <small>{label}</small>
                      <b>{typeof value === 'number' ? displayNumber(value) : String(value)}</b>
                    </span>
                  ))}
                </div>
                <div className="training-review-rewards studio-review-rewards">
                  {Object.entries(trainingDraftConfig.reward_weights).map(([key, value]) => (
                    <span key={key}>
                      <small>{rewardWeightLabels[key] ?? key}</small>
                      <b>{Number(value).toFixed(2)}</b>
                    </span>
                  ))}
                </div>
                <div className="training-risk-list studio-risk-list">
                  {trainingRiskWarnings.map((warning) => (
                    <span key={warning}><CircleAlert size={13} />{warning}</span>
                  ))}
                </div>
                <div className="linkage-actions review-actions studio-actions">
                  <button type="button" onClick={() => {
                    setTrainingReviewOpen(false);
                    setAutomationStepIndex(3);
                    setStageModal(null);
                  }}>继续调整参数</button>
                  <button type="button" onClick={() => void runUiAction('start_rl_training', () => startTraining())}><ShieldCheck size={14} />生成确认面板</button>
                  <button id="btnConfirmTraining" type="button" disabled={busy || !trainingReviewOpen} onClick={() => void runUiAction('start_rl_training', confirmStartTraining)}><Play size={14} />确认开始训练</button>
                </div>
              </aside>
            </div>
          </div>
        </section>
      )}

      {commandCenterOpen && (
        <section className="command-center-backdrop" aria-label="舷鸥指令中心">
          <div className="command-center-modal" role="dialog" aria-modal="true">
            <div className="command-center-head">
              <div>
                <p>GullMate Command Center</p>
                <h2>舷鸥指令中心</h2>
              </div>
              <button className="icon-btn" type="button" onClick={() => setCommandCenterOpen(false)} aria-label="关闭舷鸥指令中心">
                <X size={18} />
              </button>
            </div>
            <div className="command-center-toolbar">
              <input
                value={commandSearch}
                onChange={(event) => setCommandSearch(event.target.value)}
                placeholder="搜索：实时 / 交班 / 岸电 / 训练 / 模拟器 / API"
              />
              <div className="command-center-tabs">
                {commandGroups.map((group) => (
                  <button className={activeCommandGroup === group ? 'active' : ''} key={group} type="button" onClick={() => setActiveCommandGroup(group)}>
                    {group}
                  </button>
                ))}
              </div>
            </div>

            <section className="command-center-section training-command-section">
              <div className="command-center-section-title">
                <h3><Activity size={15} />优化目标训练指令</h3>
                <span>点击执行后直接进入训练确认 UI</span>
              </div>
              <div className="training-command-grid">
                {trainingObjectives.map((profile) => {
                  const shortcut = commandShortcuts.find((item) => item.id === `train_${profile.id}`);
                  if (!shortcut) return null;
                  return (
                    <article className="training-command-card" key={profile.id}>
                      <span className="command-copy">
                        <small title={`${resolveAlgorithmProfile(profile.algorithm).label} · ${displayNumber(profile.totalSteps)} steps`}>
                          {resolveAlgorithmProfile(profile.algorithm).label} · {displayNumber(profile.totalSteps)} steps
                        </small>
                        <b title={profile.label}>{profile.label}</b>
                        <em title={profile.command}>{profile.command}</em>
                      </span>
                      <p title={profile.reason}>{profile.reason}</p>
                      <div className="command-card-actions" aria-label={`${profile.label} 指令操作`}>
                        <button type="button" title={`填入：${profile.command}`} onClick={() => applyCommandShortcut(shortcut)}><SlidersHorizontal size={13} />填入</button>
                        <button type="button" title={`判断：${profile.command}`} onClick={() => void runUiAction(shortcut.actionId, () => judgeCommandShortcut(shortcut))}><Bot size={13} />判断</button>
                        <button type="button" title={`执行：${profile.command}`} onClick={() => void runUiAction(shortcut.actionId, () => executeCommandShortcut(shortcut))}><Play size={13} />执行</button>
                      </div>
                    </article>
                  );
                })}
              </div>
            </section>

            <section className="command-center-section">
              <div className="command-center-section-title">
                <h3><ListChecks size={15} />全部可执行指令</h3>
                <span>{filteredCommandShortcuts.length} / {commandShortcuts.length}</span>
              </div>
              <div className="command-center-list">
                {filteredCommandShortcuts.length ? (
                  filteredCommandShortcuts.map((shortcut) => (
                    <article className={`command-center-row ${shortcut.objectiveId ? 'is-training' : ''}`} key={shortcut.id}>
                      <span className="command-copy">
                        <small title={`${shortcut.group} · ${shortcut.badge}`}>{shortcut.group} · {shortcut.badge}</small>
                        <b title={shortcut.label}>{shortcut.label}</b>
                        <em title={shortcut.command}>{shortcut.command}</em>
                      </span>
                      <p title={shortcut.description}>{shortcut.description}</p>
                      <div className="command-card-actions" aria-label={`${shortcut.label} 指令操作`}>
                        <button type="button" title={`填入：${shortcut.command}`} onClick={() => applyCommandShortcut(shortcut)}><SlidersHorizontal size={13} />填入</button>
                        <button type="button" title={`判断：${shortcut.command}`} onClick={() => void runUiAction(shortcut.actionId, () => judgeCommandShortcut(shortcut))}><Bot size={13} />判断</button>
                        <button type="button" title={`执行：${shortcut.command}`} onClick={() => void runUiAction(shortcut.actionId, () => executeCommandShortcut(shortcut))}><Play size={13} />执行</button>
                      </div>
                    </article>
                  ))
                ) : (
                  <div className="command-empty-state">
                    <b>没有匹配指令</b>
                    <span>换一个关键词或切回“全部”即可继续查看。</span>
                  </div>
                )}
              </div>
            </section>
          </div>
        </section>
      )}

      {stageModal && (
        <section className={`stage-modal-layer ${stageModal.kind}`} aria-label="舷鸥阶段确认弹窗">
          <div className="stage-modal-card">
            <div className="stage-modal-head">
              <span>{stageModal.eyebrow}</span>
              <b>{stageModal.kind === 'confirm' ? '需要人工确认' : stageModal.kind === 'done' ? '执行完成' : '确认无误'}</b>
            </div>
            <h3>{stageModal.title}</h3>
            <p>{stageModal.description}</p>
            <div className="stage-progress">
              <span className="stage-progress-track">
                <i style={{ width: `${Math.min(100, Math.max(0, stageModal.progress))}%` }} />
              </span>
              <small>{stageModal.progress}% · {stageModal.progressLabel}</small>
            </div>
            <div className="stage-modal-detail-grid">
              {stageModal.details.map((item) => (
                <span key={`${stageModal.stepIndex}-${item.label}`}>
                  <small>{item.label}</small>
                  <b>{item.value}</b>
                </span>
              ))}
            </div>
            {stageModal.kind === 'confirm' && (
              <div className="training-risk-list stage-risk-list">
                {trainingRiskWarnings.map((warning) => (
                  <span key={warning}><CircleAlert size={13} />{warning}</span>
                ))}
              </div>
            )}
            <div className="stage-modal-actions">
              {stageModal.kind === 'confirm' ? (
                <>
                  <button type="button" onClick={() => {
                    setStageModal(null);
                    setTrainingReviewOpen(false);
                    setAutomationStepIndex(3);
                  }}>返回修改参数</button>
                  <button id="btnStageConfirmTraining" type="button" disabled={busy || !trainingReviewOpen} onClick={() => void runUiAction('start_rl_training', confirmStartTraining)}><Play size={14} />确认无误，开始训练</button>
                </>
              ) : stageModal.kind === 'done' ? (
                <button id="btnTrainingStartedClose" type="button" onClick={() => setStageModal(null)}><CheckCircle2 size={14} />知道了</button>
              ) : (
                <span><CheckCircle2 size={14} />本阶段确认无误，舷鸥继续执行</span>
              )}
            </div>
          </div>
        </section>
      )}
    </>
  );
}
