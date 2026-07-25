import { useEffect, useMemo, useRef, useState } from 'react';
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
type JsonRequestInit = Omit<RequestInit, 'body'> & { body?: unknown };

interface PendingPacket {
  action?: JsonMap;
  will_execute?: JsonMap;
  human_confirmation?: JsonMap;
  execution_result?: JsonMap;
  recommendation?: JsonMap | null;
  matched?: boolean;
}

interface LogItem {
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

type TopPanelId = 'simulation' | 'marl' | 'carbon' | 'shore' | 'api';

interface XiaoyiLinkageHubProps {
  currentGreenPreference?: number;
  currentCarbonPrice?: number;
  externalOpenToken?: number;
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
  description: string;
}

const trainingObjectives = [
  {
    id: 'carbon_min',
    label: '碳排最低目标',
    command: '小懿，开始训练碳排最低目标',
    algorithm: 'sac',
    totalSteps: 220000,
    horizonMin: 720,
    rewardWeights: { carbon: 0.42, shore_power: 0.24, cost: 0.14, delay: 0.0, safety: 0.20, peak: 0.0, storage: 0.08 },
    reason: '优先压低碳排并保留安全护栏。',
  },
  {
    id: 'cost_carbon_balance',
    label: '成本与碳排均衡',
    command: '小懿，开始训练成本与碳排均衡目标',
    algorithm: 'td3',
    totalSteps: 180000,
    horizonMin: 540,
    rewardWeights: { carbon: 0.30, shore_power: 0.0, cost: 0.32, delay: 0.18, safety: 0.20, peak: 0.0, storage: 0.08 },
    reason: '用双评论家和延迟策略更新学习连续资源配比。',
  },
  {
    id: 'shore_power_priority',
    label: '岸电优先目标',
    command: '小懿，开始训练岸电优先目标',
    algorithm: 'sac',
    totalSteps: 200000,
    horizonMin: 720,
    rewardWeights: { carbon: 0.24, shore_power: 0.44, cost: 0.0, delay: 0.12, safety: 0.20, peak: 0.0, storage: 0.08 },
    reason: '优先把靠泊窗口和岸电窗口匹配起来。',
  },
  {
    id: 'peak_smoothing',
    label: '峰值负荷平滑',
    command: '小懿，开始训练峰值负荷平滑目标',
    algorithm: 'ppo',
    totalSteps: 160000,
    horizonMin: 360,
    rewardWeights: { carbon: 0.18, shore_power: 0.0, cost: 0.20, delay: 0.0, safety: 0.22, peak: 0.40, storage: 0.08 },
    reason: '削减岸电和设备作业叠加峰值。',
  },
  {
    id: 'low_risk_validation',
    label: '低风险试运行',
    command: '小懿，开始训练低风险试运行目标',
    algorithm: 'dqn',
    totalSteps: 90000,
    horizonMin: 240,
    rewardWeights: { carbon: 0.22, shore_power: 0.0, cost: 0.18, delay: 0.18, safety: 0.42, peak: 0.0, storage: 0.08 },
    reason: '在 81 个可审计岸电、装卸资源与储能组合中学习离散调度动作。',
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
    description: '离散动作强化学习：在岸电、岸桥、堆场资源和储能的 81 个组合中学习 Q 值。',
    defaults: { total_steps: 120000, batch_size: 128, learning_rate: 0.0001, gamma: 0.99, tau: 0, entropy_coef: 0 },
  },
];

const trainingDataFiles: TrainingDataFile[] = [
  { id: 'port_la_2020_2024_vessel_activity_hourly', label: '洛杉矶港官方逐日船舶活动增强集', path: 'port_la_2020_2024_vessel_activity_hourly', description: '43,848小时能碳序列 + 1,238条港方逐日锚泊、靠泊、离港和在港时间记录；2020–2022训练、2023验证、2024测试，非报告日明确标记为插值。' },
  { id: 'port_la_2020_2025_hourly', label: '洛杉矶港 × EIA 2020–2025 小时基准', path: 'port_la_2020_2025_hourly', description: '洛杉矶港72个月度TEU锚点 + EIA LADWP 52,608小时电力/碳信号；2020–2023训练、2024验证、2025测试，源数据覆盖率98.32%。' },
];

const rewardWeightLabels: Record<string, string> = {
  carbon: '碳排',
  shore_power: '岸电',
  cost: '成本',
  delay: '延误',
  safety: '安全',
  peak: '峰值',
  storage: '储能终端 SOC',
};

const trainingParamFields: Array<{ key: NumericTrainingParamKey; label: string; min: number; max?: number; step: string }> = [
  { key: 'total_steps', label: '训练总步数', min: 0, max: 5000000, step: '1000' },
  { key: 'horizon_min', label: '训练 horizon(min)', min: 60, max: 1440, step: '30' },
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
  return {
    algorithm: profile.algorithm,
    data_file: trainingDataFiles[0].path,
    scenario: 'port_la_vessel_activity_benchmark',
    asset_group: 'berth_shore_power_yard_truck',
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
    reward_weights: { ...profile.rewardWeights },
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
  { id: 'open_simulation_panel', label: '打开仿真面板', command: '小懿，打开仿真在线面板', group: 'AI决策面板', buttonId: 'btnXiaoyiOpenSimulationPanel' },
  { id: 'open_marl_panel', label: '打开 RL 面板', command: '小懿，打开 RL 策略面板', group: 'AI决策面板', buttonId: 'btnXiaoyiOpenMarlPanel' },
  { id: 'open_carbon_panel', label: '打开低碳面板', command: '小懿，打开低碳优先面板', group: 'AI决策面板', buttonId: 'btnXiaoyiOpenCarbonPanel' },
  { id: 'open_shore_panel', label: '打开岸电面板', command: '小懿，打开岸电联动面板', group: 'AI决策面板', buttonId: 'btnXiaoyiOpenShorePanel' },
  { id: 'open_api_panel', label: '打开 API 面板', command: '小懿，打开 API 同步面板', group: 'AI决策面板', buttonId: 'btnXiaoyiOpenApiPanel' },
  { id: 'refresh_dashboard_snapshot', label: '刷新仿真', command: '小懿，刷新仿真并重新同步仪表盘', group: 'AI决策面板', buttonId: 'btnXiaoyiRefreshDashboard' },
  { id: 'run_linkage_health_check', label: '健康检查', command: '小懿，做一次联动健康检查', group: 'AI决策面板', buttonId: 'btnXiaoyiHealthCheck' },
  { id: 'check_sailing_status', label: '检查模拟器', command: '小懿，检查航行模拟器状态', group: 'AI决策面板', buttonId: 'btnXiaoyiCheckSailingStatus' },
  { id: 'set_efficiency_priority', label: '效率优先', command: '小懿，切到效率优先', group: '调度偏好', buttonId: 'btnXiaoyiPreferenceEfficiency' },
  { id: 'set_balanced_dispatch', label: '均衡调度', command: '小懿，切到均衡调度', group: '调度偏好', buttonId: 'btnXiaoyiPreferenceBalanced' },
  { id: 'set_low_carbon_priority', label: '低碳优先', command: '小懿，切到低碳优先', group: '调度偏好', buttonId: 'btnXiaoyiPreferenceLowCarbon' },
  { id: 'set_shore_power_preference', label: '岸电优先', command: '小懿，切到岸电优先', group: '调度偏好', buttonId: 'btnXiaoyiPreferenceShorePower' },
  { id: 'start_xiaoyi_ai', label: '启动小懿AI', command: '小懿，启动小懿AI', group: '小懿/RL/模拟器' },
  { id: 'start_rl_training', label: '启动 RL 训练', command: '小懿，开始训练碳排最低目标', group: '小懿/RL/模拟器' },
  { id: 'view_rl_training_status', label: '查看训练状态', command: '小懿，查看训练状态', group: '小懿/RL/模拟器' },
  { id: 'pause_rl_training', label: '暂停 RL 训练', command: '小懿，暂停训练', group: '小懿/RL/模拟器' },
  { id: 'resume_rl_training', label: '继续 RL 训练', command: '小懿，继续训练', group: '小懿/RL/模拟器' },
  { id: 'stop_rl_training', label: '停止 RL 训练', command: '小懿，停止训练', group: '小懿/RL/模拟器' },
  { id: 'run_policy_test', label: '运行策略测试', command: '小懿，运行训练后策略测试', group: '小懿/RL/模拟器' },
  { id: 'verify_policy_for_online', label: '上线验证 dry-run', command: '小懿，验证这个策略能不能上线', group: '小懿/RL/模拟器' },
  { id: 'open_sailing_simulator', label: '启动航行模拟器', command: '小懿，启动航行模拟器', group: '小懿/RL/模拟器' },
  { id: 'start_navigation_demo', label: '启动航线演示', command: '小懿，启动航线演示', group: '小懿/RL/模拟器' },
  { id: 'switch_ship_view', label: '切换船舶视角', command: '小懿，切换船舶视角', group: '小懿/RL/模拟器' },
  { id: 'run_sailing_rl_smoke_test', label: '运行 smoke test', command: '小懿，运行航行 smoke test', group: '小懿/RL/模拟器' },
];

const clickableActions = new Set(commandCatalog.map((item) => item.id));

const preferenceActions: Record<string, { value: number; label: string; panel: TopPanelId }> = {
  set_efficiency_priority: { value: 0.25, label: '效率优先', panel: 'carbon' },
  set_balanced_dispatch: { value: 0.5, label: '均衡调度', panel: 'carbon' },
  set_low_carbon_priority: { value: 0.82, label: '低碳优先', panel: 'carbon' },
  set_shore_power_preference: { value: 0.88, label: '岸电优先', panel: 'shore' },
};

const topPanelActions: Record<string, TopPanelId> = {
  open_simulation_panel: 'simulation',
  open_marl_panel: 'marl',
  open_carbon_panel: 'carbon',
  open_shore_panel: 'shore',
  open_api_panel: 'api',
};

const actionContracts: Record<string, { method: string; path: string; confirmationRequired: boolean }> = {
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
  run_policy_test: { method: 'POST', path: '/api/rl/simulate', confirmationRequired: false },
  verify_policy_for_online: { method: 'POST', path: '/api/rlops/policies/verify + /api/rl/dispatch', confirmationRequired: false },
  open_sailing_simulator: { method: 'POST', path: '/api/sailing/launch', confirmationRequired: true },
  start_navigation_demo: { method: 'POST', path: '/api/sailing/actions/execute', confirmationRequired: true },
  switch_ship_view: { method: 'POST', path: '/api/sailing/actions/execute', confirmationRequired: true },
  run_sailing_rl_smoke_test: { method: 'POST', path: '/api/sailing/actions/execute', confirmationRequired: true },
};

const actionPreludeSteps: Record<string, Array<{ selector: string; label: string }>> = {
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
  if (!series.length) return '';
  const values = series.map((item) => Number(item[key] ?? 0));
  const minimum = Math.min(...values);
  const maximum = Math.max(...values);
  const range = Math.max(0.0001, maximum - minimum);
  return values.map((value, index) => {
    const x = padding + (index / Math.max(1, values.length - 1)) * (width - padding * 2);
    const y = height - padding - ((value - minimum) / range) * (height - padding * 2);
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(' ');
}

async function api(path: string, options: JsonRequestInit = {}) {
  const response = await fetch(path, {
    ...options,
    cache: 'no-store',
    headers: options.body ? { 'Content-Type': 'application/json' } : options.headers,
    body: options.body ? JSON.stringify(options.body) : undefined,
  });
  const data = (await response.json().catch(() => ({}))) as JsonMap;
  if (!response.ok) {
    throw new Error(data.detail || response.statusText);
  }
  return data;
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
  const [trainingHistory, setTrainingHistory] = useState<JsonMap | null>(null);
  const [trainingHistoryLoading, setTrainingHistoryLoading] = useState(false);
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
    label: '等待小懿指令',
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
    x: Math.max(16, window.innerWidth - 126),
    y: Math.max(80, window.innerHeight - 166),
  }));
  const [showOrbGreeting, setShowOrbGreeting] = useState(true);
  const dragRef = useRef<{ dx: number; dy: number; moved: boolean } | null>(null);
  const suppressOrbClickRef = useRef(false);
  const xiaoyiTrainingRunRef = useRef(false);

  useEffect(() => {
    if (externalOpenToken > 0) {
      setOpen(true);
    }
  }, [externalOpenToken]);

  useEffect(() => {
    const timer = window.setTimeout(() => setShowOrbGreeting(false), 5200);
    return () => window.clearTimeout(timer);
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
      group: item.group === '小懿/RL/模拟器' ? '联动执行' : item.group,
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
      reward_weights: { ...recommended.reward_weights },
    }));
  }, [selectedObjective]);

  function addLog(kind: string, message: string) {
    setLogs((items) => [{ time: now(), kind, message }, ...items].slice(0, 18));
  }

  function applyCommandShortcut(shortcut: CommandShortcutItem) {
    const profile = shortcut.objectiveId ? trainingObjectives.find((item) => item.id === shortcut.objectiveId) : null;
    if (profile) {
      setSelectedObjective(profile.id);
      setTrainingParams((current) => ({ ...createTrainingParams(profile), data_file: current.data_file }));
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
    await runCatalogAction(shortcut.actionId, shortcut.command);
  }

  function selectTrainingObjective(objectiveId: string) {
    const next = trainingObjectives.find((item) => item.id === objectiveId) ?? trainingObjectives[0];
    setSelectedObjective(next.id);
    setSelectedAction('start_rl_training');
    setCommand(next.command);
  }

  function applyAlgorithm(algorithmId: string) {
    const algorithm = rlAlgorithms.find((item) => item.id === algorithmId) ?? rlAlgorithms[0];
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
    const next = Number(value);
    setTrainingParams((current) => ({ ...current, [key]: Number.isFinite(next) ? next : 0 }));
  }

  function updateRewardWeight(key: string, value: string) {
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
        ? '小懿已完成前序核验，请人工复核全部训练信息后再启动。'
        : `小懿已完成“${currentStep.label}”，当前阶段信息已核验无误。`,
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

  async function animateStageModal(stage: StageModalState, duration = 900, label = '小懿正在核验本阶段信息') {
    const initialProgress = stage.kind === 'running' ? 18 : 6;
    setAutomationStepIndex(stage.stepIndex);
    setStageModal({ ...stage, progress: duration > 0 ? initialProgress : 100, progressLabel: duration > 0 ? label : '阶段核验完成' });
    if (duration <= 0) return;
    const frames = Math.max(5, Math.ceil(duration / 150));
    for (let index = 1; index <= frames; index += 1) {
      await wait(duration / frames);
      const progressValue = Math.min(100, Math.round(initialProgress + ((100 - initialProgress) * index) / frames));
      setStageModal((current) => {
        if (!current || current.stepIndex !== stage.stepIndex || current.kind !== stage.kind) return current;
        return {
          ...current,
          progress: progressValue,
          progressLabel: progressValue >= 100 ? '本阶段确认无误' : `核验进度 ${progressValue}%`,
        };
      });
    }
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
      group: item?.group ?? '小懿问答',
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
    setExecution(actionId, 'completed', instruction, {
      resultSummary,
      resultCode: pretty(result).slice(0, 900),
    });
  }

  function failExecution(actionId: string, error: unknown, instruction = '') {
    setExecution(actionId, 'failed', instruction, {
      resultSummary: `执行失败：${String(error)}`,
      resultCode: String(error),
    });
  }

  async function typeAnswer(text: string) {
    setBusy(true);
    setAnswer('思考中...');
    await wait(2000);
    setAnswer('');
    for (const char of text) {
      setAnswer((current) => current + char);
      await wait(18);
    }
    setBusy(false);
  }

  async function refreshAll() {
    const [nextHealth, nextTraining, nextSailing, nextRegistry] = await Promise.all([
      api('/api/linkage/health').catch((error) => ({ error: String(error) })),
      api('/api/rl/train/status').catch((error) => ({ status: 'offline', error: String(error) })),
      api('/api/sailing/status').catch((error) => ({ label: '航行模拟器待检查', error: String(error) })),
      api('/api/rl/actions/registry').catch((error) => ({ count: commandCatalog.length, error: String(error) })),
    ]);
    setHealth(nextHealth);
    setTrainingStatus(nextTraining);
    setSailingStatus(nextSailing);
    setActionRegistry(nextRegistry);
  }

  useEffect(() => {
    refreshAll();
    const timer = window.setInterval(refreshAll, 7000);
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
      resultSummary: '小懿正在识别意图并匹配可执行动作。',
      resultCode: 'intent_matching',
    });
    setBusy(true);
    setPendingPacket(null);
    setPacket('小懿正在判断动作...');
    const payload = {
      ...resolvePayload(true, false),
      instruction: nextCommand,
      action_id: (actionId ?? selectedAction) || undefined,
    };
    const data = await api('/api/assistant/actions/execute', { method: 'POST', body: payload });
    setPacket(pretty(data));
    if (!data.matched) {
      const chat = await api('/api/xiaoyi/chat', { method: 'POST', body: { question: nextCommand, mode: 'brief', top_k: 5 } });
      const text = chat.result?.answer || chat.answer || '小懿已接收问题，但暂未返回可展示答案。';
      completeExecution('xiaoyi_chat', '未匹配到联动按钮，已转为小懿普通问答。', chat, nextCommand);
      await typeAnswer(text);
      addLog('XIAOYI', '普通问答已交给小懿');
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
    addLog('XIAOYI', `动作识别：${action.id ?? 'unknown'}`);
    if (autoExecute && !data.human_confirmation?.required) {
      await wait(420);
      const clicked = await clickMappedButton(data);
      if (!clicked) {
        await typeAnswer('动作已经识别，但当前页面没有找到可点击按钮。请在指令中心重新执行。');
      }
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
      resultSummary: '小懿正在逐步配置训练任务，并准备弹出人工确认面板。',
      resultCode: pretty({ objective: selectedObjective, algorithm: trainingParams.algorithm, data_file: trainingParams.data_file }).slice(0, 900),
    });
    addLog('XIAOYI/AUTO', '识别训练意图，开始自动配置。');
    await showStageModal(0, 'ok', 1150);
    await typeAnswer('小懿开始执行训练准备流程：先识别优化目标，再选择算法和数据文件，最后打开训练确认面板。');
    const scriptedSteps = [
      { step: 1, selector: '#trainingObjectiveSelect', log: `选择优化目标：${objective.label}` },
      { step: 2, selector: '#trainingAlgorithmSelect', log: `匹配算法：${selectedAlgorithmProfile.label}` },
      { step: 2, selector: '#trainingDataSelect', log: `确认训练数据：${selectedDataFileProfile.label}` },
      { step: 3, selector: '#btnStartTraining', log: '点击启动训练，弹出训练前确认 UI。' },
    ];
    for (const item of scriptedSteps) {
      setAutomationStepIndex(item.step);
      pulseElement(item.selector, 1250);
      addLog('XIAOYI/CLICK', item.log);
      await showStageModal(item.step, 'ok', 1250);
    }
    target.classList.add('linkage-autoclick-target');
    xiaoyiTrainingRunRef.current = true;
    target.click();
    window.setTimeout(() => target.classList.remove('linkage-autoclick-target'), 1400);
    return true;
  }

  async function clickMappedButton(packetData: PendingPacket) {
    const actionId = String(packetData.action?.id ?? packetData.will_execute?.action_id ?? '');
    const selector = String(packetData.will_execute?.button?.selector ?? packetData.action?.button_selector ?? '');
    if (!clickableActions.has(actionId) || !selector) return false;
    const target = document.querySelector<HTMLButtonElement>(selector);
    if (!target) return false;
    const label = String(packetData.will_execute?.button?.label ?? packetData.action?.button_label ?? target.textContent ?? actionId);
    if (actionId === 'start_rl_training') {
      return runXiaoyiTrainingSequence(packetData, target, label);
    }
    const steps = [
      ...(actionPreludeSteps[actionId] ?? []),
      { selector, label: `${label} / Execute action` },
    ].filter((step, index, items) => items.findIndex((item) => item.selector === step.selector) === index);
    setClickSequence(steps.map((step) => ({ ...step, status: 'pending' })));
    setExecution(actionId, 'executing', command || String(packetData.action?.label ?? ''), {
      buttonLabel: label,
      resultSummary: `小懿已规划 ${steps.length} 步页面操作，正在依次定位并点击。`,
      resultCode: steps.map((step) => step.selector).join(' -> '),
    });
    for (let index = 0; index < steps.length; index += 1) {
      const step = steps[index];
      setClickSequence((items) => items.map((item, itemIndex) => itemIndex === index ? { ...item, status: 'locating' } : item));
      const stepTarget = document.querySelector<HTMLButtonElement>(step.selector);
      if (!stepTarget || stepTarget.disabled) {
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
      await wait(620);
      stepTarget.click();
      await wait(720);
      stepTarget.classList.remove('linkage-autoclick-target');
      setClickSequence((items) => items.map((item, itemIndex) => itemIndex === index ? { ...item, status: 'done' } : item));
    }
    setAnswer(`已完成 ${steps.length} 步联动：${label}。执行结果已同步到驾驶舱。`);
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
    await refreshAll();
  }

  async function launchXiaoyi() {
    setExecution('start_xiaoyi_ai', 'executing', '小懿，启动小懿AI', {
      resultSummary: '正在启动小懿本地服务。',
    });
    setPacket('正在启动小懿AI...');
    const data = await api('/api/xiaoyi/launch', { method: 'POST', body: { confirm: true, source: 'energy_carbon_cockpit' } });
    setPacket(pretty(data));
    completeExecution('start_xiaoyi_ai', `执行结果：${data.result?.status ?? '完成'}。`, data, '小懿，启动小懿AI');
    await typeAnswer(`执行结果：${data.result?.status ?? '完成'}。\n小懿地址：${data.status?.base_url ?? 'http://127.0.0.1:8010'}`);
    addLog('XIAOYI', `start_xiaoyi_ai · ${data.result?.status ?? 'done'}`);
    await refreshAll();
  }

  async function startTraining(targetObjective = objective) {
    const targetParams = targetObjective.id === objective.id ? trainingParams : createTrainingParams(targetObjective);
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
      description: '小懿已完成风险审查，当前阶段信息已核验无误。',
      details: [
        { label: '风险提示数量', value: `${targetWarnings.length} 条` },
        { label: '优化目标', value: targetObjective.label },
        { label: '上线约束', value: '训练结果仅进入 dry-run 验证' },
      ],
      progress: 100,
      progressLabel: '风险审查已生成',
    }, 1200, '正在生成风险审查和训练摘要');
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
      description: '小懿已完成前序核验，请人工复核全部训练信息后再启动。',
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
    const instruction = objective.command;
    setCommand(instruction);
    setSelectedAction('start_rl_training');
    setAutomationMode(automationMode === 'xiaoyi' ? 'xiaoyi' : 'manual');
    setAutomationStepIndex(6);
    await animateStageModal(buildTrainingStageModal(6, 'running'), 950, '正在调用训练启动接口');
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
      description: '小懿已完成全部核验并调用训练接口，训练状态已刷新。',
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
    await refreshAll();
  }

  async function openTrainingHistory() {
    setTrainingHistoryOpen(true);
    if (trainingHistory) return;
    setTrainingHistoryLoading(true);
    try {
      const data = await api('/api/rl/training/history');
      setTrainingHistory(data.run ?? data);
      addLog('RL/EVIDENCE', `历史收敛记录已载入：${data.run?.run_id ?? 'offline-run'}`);
    } catch (error) {
      failExecution('training_history', error, '查看历史收敛曲线');
    } finally {
      setTrainingHistoryLoading(false);
    }
  }

  async function showTrainingStatus() {
    setExecution('view_rl_training_status', 'executing', '小懿，查看训练状态', {
      resultSummary: '正在读取训练 step、reward、entropy 和策略版本。',
    });
    const data = await api('/api/rl/train/status');
    setTrainingStatus(data);
    setPacket(pretty(data));
    completeExecution('view_rl_training_status', `训练状态：${data.summary ?? data.status ?? '已刷新'}。`, data, '小懿，查看训练状态');
    await typeAnswer(`训练状态：${data.summary ?? data.status}\nstep=${data.step ?? 0} reward=${data.reward ?? 0} entropy=${data.entropy ?? 0}\npolicy=${data.policy_version ?? '—'}`);
    addLog('RL', `status · ${data.status}`);
  }

  async function controlTraining(action: 'pause' | 'resume' | 'stop') {
    const actionId = action === 'pause' ? 'pause_rl_training' : action === 'resume' ? 'resume_rl_training' : 'stop_rl_training';
    const actionLabel = action === 'pause' ? '暂停训练' : action === 'resume' ? '继续训练' : '停止训练';
    const instruction = `小懿，${actionLabel}`;
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
    }
  }

  async function runPolicyTest() {
    setExecution('run_policy_test', 'executing', '小懿，运行训练后策略测试', {
      resultSummary: '正在调用最新策略产物做能碳 KPI 仿真评估。',
    });
    const data = await api('/api/rl/simulate', { method: 'POST', body: { strategy_id: 'auto:latest', source: 'energy_carbon_cockpit' } });
    setPacket(pretty(data));
    const carbonReduction = Number(data.metrics?.carbon_reduction_pct ?? 0).toFixed(1);
    const shorePowerGain = Number(data.metrics?.shore_power_gain_pct ?? 0).toFixed(1);
    const costSaving = Number(data.metrics?.cost_saving_pct ?? 0).toFixed(1);
    const safetyViolations = data.metrics?.safety_violations ?? 0;
    completeExecution('run_policy_test', `策略测试完成：减排 ${carbonReduction}%，岸电提升 ${shorePowerGain} 个百分点，成本节省 ${costSaving}%，安全越界 ${safetyViolations}。`, data, '小懿，运行训练后策略测试');
    await typeAnswer(`策略测试完成。\n减排：${carbonReduction}%；岸电提升：${shorePowerGain} 个百分点；成本节省：${costSaving}%；安全越界：${safetyViolations}。`);
    addLog('RL', 'policy_test · tested');
  }

  async function verifyPolicy() {
    setExecution('verify_policy_for_online', 'executing', '小懿，验证这个策略能不能上线', {
      resultSummary: '正在执行上线校验和 dispatch dry-run。',
    });
    const verify = await api('/api/rlops/policies/verify', { method: 'POST', body: { strategy_id: 'auto:latest' } });
    const dispatch = await api('/api/rl/dispatch', { method: 'POST', body: { strategy_id: 'auto:latest', dry_run: true } });
    setPacket(pretty({ verify, dispatch }));
    const verifyChecks = Array.isArray(verify.checks)
      ? verify.checks.map((check: JsonMap) => `${check.name ?? '未命名约束'} ${check.passed ? 'PASS' : 'BLOCK'}`).join('、')
      : '约束检查结果待返回';
    completeExecution('verify_policy_for_online', `上线验证完成：风险等级 ${verify.risk_level ?? 'low'}；${verifyChecks}；dry-run ${dispatch.dispatch_id ?? 'dryrun'} 已记录。`, { verify, dispatch }, '小懿，验证这个策略能不能上线');
    await typeAnswer(`上线验证已完成：风险等级 ${verify.risk_level ?? 'low'}。\n约束检查：${verifyChecks}。\n已记录 dry-run：${dispatch.dispatch_id ?? 'dryrun'}，不会生产下发。`);
    addLog('RLOPS', 'verify + dispatch dry-run');
  }

  async function launchSailing() {
    setExecution('open_sailing_simulator', 'executing', '小懿，启动航行模拟器', {
      resultSummary: '正在请求启动 Godot 航行模拟器主场景。',
    });
    const data = await api('/api/sailing/launch', { method: 'POST', body: { confirm: true, preset: 'main_scene', source: 'energy_carbon_cockpit' } });
    setPacket(pretty(data));
    completeExecution('open_sailing_simulator', `航行模拟器执行结果：${data.result?.status ?? '完成'}。`, data, '小懿，启动航行模拟器');
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
      resultSummary: '正在通过小懿联动网关调用目标动作。',
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
    await executeGateway(actionId, instruction);
    await onOpenTopPanel?.(panel);
    await typeAnswer(`已打开AI决策面板：${commandCatalog.find((item) => item.id === actionId)?.label ?? panel}。`);
    addLog('TOP-PANEL', `${actionId} · opened`);
  }

  async function applyPreference(actionId: string, instruction: string) {
    const preference = preferenceActions[actionId];
    if (!preference) return;
    setCommand(instruction);
    setSelectedAction(actionId);
    onSetGreenPreference?.(preference.value, preference.label);
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
    await onSyncDashboard?.('小懿已触发AI决策面板重新同步。');
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
      await onOpenTopPanel('api');
    } else {
      await onRunApiCheck?.();
    }
    const summary = result.summary ?? {};
    await typeAnswer(`健康检查完成：${summary.xiaoyi ?? '小懿待检查'} / ${summary.rl ?? 'RL待检查'} / ${summary.sailing ?? '模拟器待检查'}`);
    addLog('TOP-PANEL', 'run_linkage_health_check · checked');
  }

  async function checkSailingStatusFromXiaoyi(instruction: string) {
    setCommand(instruction);
    setSelectedAction('check_sailing_status');
    const data = await executeGateway('check_sailing_status', instruction);
    const status = data.execution_result?.result?.sailing_status ?? {};
    setSailingStatus(status);
    await onOpenTopPanel?.('simulation');
    await typeAnswer(status.process?.running ? `航行模拟器运行中：pid=${status.process.pid}` : status.label ?? '航行模拟器状态已刷新。');
    addLog('SAILING', 'check_sailing_status · checked');
  }

  async function runCatalogAction(actionId: string, instruction: string) {
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
      label: '等待小懿指令',
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

  return (
    <>
      <button
        className={`xiaoyi-orb${open ? ' has-drawer' : ''}${showOrbGreeting ? ' has-greeting' : ''}`}
        style={{ left: position.x, top: position.y }}
        type="button"
        title="打开小懿联动助手 / Open Xiaoyi AI copilot"
        aria-label="打开小懿联动助手 / Open Xiaoyi AI copilot"
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
          <strong>您好！我是小懿AI</strong>
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
        <section className="linkage-drawer" aria-label="小懿项目联动中枢">
          <div className="linkage-head">
            <div>
              <p>小懿AI · 能碳联动中枢 / Energy-Carbon Linkage Hub</p>
              <h2>把问答、训练、策略验证和航行模拟器接成一条链<small>One flow for Q&amp;A, training, policy validation, and sailing simulation.</small></h2>
            </div>
            <button className="icon-btn" type="button" onClick={() => setOpen(false)} aria-label="关闭小懿联动面板">
              <X size={18} />
            </button>
          </div>

          <div className="linkage-status-row">
            <span><Bot size={14} />{statusLabel(health, ['summary', 'xiaoyi'], '小懿待检查')}</span>
            <span><Gauge size={14} />{statusLabel(health, ['summary', 'rl'], 'RL待检查')}</span>
            <span><ShipWheel size={14} />{statusLabel(health, ['summary', 'sailing'], '航行模拟器待检查')}</span>
            <button type="button" onClick={refreshAll}><RotateCw size={14} />刷新</button>
          </div>

          <div className={`output-locator ${outputLocator.tone}`}>
            <span><ServerCog size={15} />当前信息显示在</span>
            <b>{outputLocator.surface}</b>
            <em>{outputLocator.title} · {outputLocator.detail}</em>
          </div>

          <div className="linkage-grid">
            <div className="linkage-card assistant-card module-card module-assistant">
              <div className="linkage-card-title">
                <h3><Sparkles size={15} /> 小懿问答 / 指令 <small>XIAOYI Q&amp;A / COMMANDS</small></h3>
                <span className="module-chip">输入区 / INPUT · {busy ? 'typing' : 'ready'}</span>
              </div>
              <textarea
                value={command}
                onChange={(event) => {
                  setCommand(event.target.value);
                  setSelectedAction('');
                }}
                placeholder="例如：小懿，启动模拟器 / 小懿，开始训练碳排最低目标"
              />
              <select value={selectedAction} onChange={(event) => setSelectedAction(event.target.value)}>
                <option value="">自动识别动作 / Auto-detect action</option>
                {commandCatalog.map((item) => (
                  <option value={item.id} key={item.id}>{item.group} · {item.label}</option>
                ))}
              </select>
              <div className="linkage-actions">
                <button id="btnXiaoyiStart" type="button" onClick={launchXiaoyi}><Bot size={14} />启动小懿 / Start</button>
                <button type="button" onClick={() => askXiaoyi()}><Send size={14} />识别并执行 / Run</button>
                <button type="button" disabled={!pendingPacket} onClick={confirmAction}><Play size={14} />确认执行 / Confirm</button>
                <button type="button" onClick={clearAssistant}>清空 / Clear</button>
              </div>
              <div className="xiaoyi-command-targets" aria-label="小懿可视化按钮联动区 / Xiaoyi visual action targets">
                <span><small>可视化按钮联动</small><b>VISUAL AUTO-CLICK TARGETS</b></span>
                <button id="btnXiaoyiOpenSimulationPanel" type="button" onClick={() => void runCatalogAction('open_simulation_panel', '小懿，打开仿真在线面板')}>仿真 / Simulation</button>
                <button id="btnXiaoyiOpenMarlPanel" type="button" onClick={() => void runCatalogAction('open_marl_panel', '小懿，打开 RL 策略面板')}>RL / Policy</button>
                <button id="btnXiaoyiOpenCarbonPanel" type="button" onClick={() => void runCatalogAction('open_carbon_panel', '小懿，打开低碳优先面板')}>低碳 / Carbon</button>
                <button id="btnXiaoyiOpenShorePanel" type="button" onClick={() => void runCatalogAction('open_shore_panel', '小懿，打开岸电联动面板')}>岸电 / Shore</button>
                <button id="btnXiaoyiOpenApiPanel" type="button" onClick={() => void runCatalogAction('open_api_panel', '小懿，打开 API 同步面板')}>API / Health</button>
                <button id="btnXiaoyiRefreshDashboard" type="button" onClick={() => void runCatalogAction('refresh_dashboard_snapshot', '小懿，刷新仿真并重新同步仪表盘')}>刷新 / Refresh</button>
                <button id="btnXiaoyiHealthCheck" type="button" onClick={() => void runCatalogAction('run_linkage_health_check', '小懿，做一次联动健康检查')}>检查 / Check</button>
                <button id="btnXiaoyiCheckSailingStatus" type="button" onClick={() => void runCatalogAction('check_sailing_status', '小懿，检查航行模拟器状态')}>模拟器 / Simulator</button>
                <button id="btnXiaoyiPreferenceEfficiency" type="button" onClick={() => void runCatalogAction('set_efficiency_priority', '小懿，切到效率优先')}>效率 / Efficiency</button>
                <button id="btnXiaoyiPreferenceBalanced" type="button" onClick={() => void runCatalogAction('set_balanced_dispatch', '小懿，切到均衡调度')}>均衡 / Balanced</button>
                <button id="btnXiaoyiPreferenceLowCarbon" type="button" onClick={() => void runCatalogAction('set_low_carbon_priority', '小懿，切到低碳优先')}>低碳优先 / Low-carbon</button>
                <button id="btnXiaoyiPreferenceShorePower" type="button" onClick={() => void runCatalogAction('set_shore_power_preference', '小懿，切到岸电优先')}>岸电优先 / Shore first</button>
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
              <div className="xiaoyi-algorithm-advisor" aria-label="小懿五算法训练顾问">
                <header>
                  <span><Bot size={13} />小懿训练顾问</span>
                  <b>五算法同一环境契约</b>
                </header>
                <div>
                  {rlAlgorithms.map((algorithm) => (
                    <button
                      className={trainingParams.algorithm === algorithm.id ? 'active' : ''}
                      type="button"
                      key={algorithm.id}
                      onClick={() => applyAlgorithm(algorithm.id)}
                    >
                      <b>{algorithm.label}</b>
                      <small>{algorithm.tag}</small>
                    </button>
                  ))}
                </div>
                <p>推荐使用逐日船舶活动增强集训练；旧 52,608 小时基准完整保留，用于能碳长周期证据对照。</p>
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
                <button id="btnOpenTrainingStudio" type="button" onClick={() => openTrainingStudio(false)}><SlidersHorizontal size={14} />配置参数 / Configure</button>
                <button id="btnStartTraining" type="button" onClick={() => startTraining()}><Play size={14} />启动训练 / Start</button>
                <button
                  id="btnPauseTraining"
                  type="button"
                  disabled={!trainingCanPause && !trainingCanResume}
                  onClick={() => controlTraining(trainingCanResume ? 'resume' : 'pause')}
                >
                  {trainingCanResume ? <Play size={14} /> : <Pause size={14} />}
                  {trainingCanResume ? '继续训练 / Resume' : '暂停训练 / Pause'}
                </button>
                <button
                  id="btnStopTraining"
                  className="training-stop-action"
                  type="button"
                  disabled={!trainingCanStop}
                  onClick={() => controlTraining('stop')}
                ><Square size={14} />停止 / Stop</button>
                <button id="btnTrainingStatus" type="button" onClick={showTrainingStatus}><Radio size={14} />状态 / Status</button>
                <button id="btnTrainingHistory" type="button" onClick={() => void openTrainingHistory()}><Gauge size={14} />历史收敛曲线 / Results</button>
                <button id="btnPolicyTest" type="button" onClick={runPolicyTest}><Gauge size={14} />策略测试 / Test</button>
                <button id="btnVerifyPolicy" type="button" onClick={verifyPolicy}><ShieldCheck size={14} />上线验证 / Dry-run</button>
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
                <button id="btnSailingLaunch" type="button" onClick={launchSailing}><ShipWheel size={14} />启动模拟器 / Launch</button>
                <button id="btnSailingDemo" type="button" onClick={() => runSailingAction('start_navigation_demo')}>航线演示 / Route demo</button>
                <button id="btnShipView" type="button" onClick={() => runSailingAction('switch_ship_view')}>船舶视角 / Ship view</button>
                <button id="btnSailingSmoke" type="button" onClick={() => runSailingAction('run_sailing_rl_smoke_test')}>Smoke test / 测试</button>
              </div>
              <div className="command-examples">
                <b>可说：</b>
                <span>启动模拟器</span>
                <span>开始训练岸电优先目标</span>
                <span>验证这个策略能不能上线</span>
              </div>
              <div className="linkage-log">
                {logs.length ? logs.map((item) => (
                  <p key={`${item.time}-${item.kind}-${item.message}`}>
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
                <ol className="xiaoyi-click-sequence" aria-label="小懿逐步点击过程 / Xiaoyi step-by-step click process">
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
                <h3><ListChecks size={15} /> 小懿指令中心</h3>
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
                    onClick={() => executeCommandShortcut({
                      id: `train_${profile.id}`,
                      label: `训练：${profile.label}`,
                      group: '优化目标训练',
                      command: profile.command,
                      actionId: 'start_rl_training',
                      objectiveId: profile.id,
                      badge: resolveAlgorithmProfile(profile.algorithm).label,
                      description: profile.reason,
                    })}
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
              <button className="icon-btn" type="button" onClick={() => setTrainingHistoryOpen(false)} aria-label="关闭历史训练结果"><X size={18} /></button>
            </div>
            {trainingHistoryLoading && <div className="training-history-loading">正在读取历史训练指标 / Loading training evidence…</div>}
            {trainingHistory && (
              <>
                <div className="training-evidence-banner">
                  <span><b>{trainingHistory.title}</b><small>{trainingHistory.title_en}</small></span>
                  <em>公开数据集 + 固定种子 / PUBLIC DATA + FIXED SEED</em>
                  <strong>非生产遥测 / NOT PRODUCTION TELEMETRY</strong>
                </div>
                <div className="training-evidence-meta">
                  <span><small>Run ID</small><b>{trainingHistory.run_id}</b></span>
                  <span><small>Environment</small><b>{trainingHistory.environment}</b></span>
                  <span><small>Algorithm / Seed</small><b>{trainingHistory.algorithm} · {trainingHistory.seed}</b></span>
                  <span><small>Scale / Duration</small><b>{Number(trainingHistory.total_steps).toLocaleString()} steps · {Math.round(Number(trainingHistory.duration_sec) / 60)} min</b></span>
                  <span><small>Checkpoint</small><b>{trainingHistory.checkpoint}</b></span>
                </div>
                <div className="training-result-metrics">
                  <span><small>Best callback reward</small><b>{trainingHistory.metrics?.best_callback_reward ?? '—'}</b></span>
                  <span><small>Last-20 callback mean</small><b>{trainingHistory.metrics?.mean_last_20_callback_reward ?? '—'}</b></span>
                  <span><small>Constraint success</small><b>{trainingHistory.metrics?.constraint_success_rate_pct ?? '—'}%</b></span>
                  <span><small>Carbon reduction</small><b>{trainingHistory.metrics?.carbon_reduction_pct}%</b></span>
                  <span><small>Shore-power gain</small><b>+{trainingHistory.metrics?.shore_power_gain_pct}pp</b></span>
                  <span><small>Cost saving</small><b>{trainingHistory.metrics?.cost_saving_pct}%</b></span>
                  <span className="safe"><small>Safety violations</small><b>{trainingHistory.metrics?.safety_violations}</b></span>
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
                    <footer><span className="entropy">Entropy</span><span className="success">Constraint success</span><em>未记录时显示为 0</em></footer>
                  </article>
                  <article className="checkpoint-evidence">
                    <header><span>Checkpoint 选择证据</span><small>evaluation checkpoints</small></header>
                    <div className="checkpoint-table">
                      {(trainingHistory.checkpoints ?? []).map((item: JsonMap) => (
                        <span key={item.step}>
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
              </>
            )}
          </div>
        </section>
      )}

      {trainingStudioOpen && (
        <section className="training-studio-backdrop" aria-label="强化学习训练配置工作台">
          <div className="training-studio-modal" role="dialog" aria-modal="true">
            <div className="training-studio-head">
              <div>
                <p>RL Training Studio · 小懿训练前确认</p>
                <h2>强化学习训练配置工作台</h2>
              </div>
              <div className="training-studio-head-actions">
                <span>{automationMode === 'xiaoyi' ? 'XIAOYI AUTO-CLICK' : trainingReviewOpen ? 'MANUAL CONFIRM' : 'PARAM EDIT'}</span>
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
                <span><Bot size={15} />小懿智能执行流程</span>
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
                    <select id="trainingObjectiveSelect" value={selectedObjective} onChange={(event) => selectTrainingObjective(event.target.value)}>
                      {trainingObjectives.map((item) => (
                        <option value={item.id} key={item.id}>{item.label}</option>
                      ))}
                    </select>
                    <em>{objective.reason}</em>
                  </label>
                  <label>
                    <small>4种RL算法 / 1种控制基线</small>
                    <select id="trainingAlgorithmSelect" value={trainingParams.algorithm} onChange={(event) => applyAlgorithm(event.target.value)}>
                      {rlAlgorithms.map((item) => (
                        <option value={item.id} key={item.id}>{item.label} · {item.tag}</option>
                      ))}
                    </select>
                    <em>{selectedAlgorithmProfile.description}</em>
                  </label>
                  <label>
                    <small>训练数据文件</small>
                      <input
                        id="trainingDataSelect"
                        list="trainingDataOptions"
                        value={trainingParams.data_file}
                        onChange={(event) => setTrainingParams((current) => ({ ...current, data_file: event.target.value }))}
                      />
                      <datalist id="trainingDataOptions">
                        {trainingDataFiles.map((item) => (
                          <option value={item.path} key={item.id}>{item.label} · {item.path}</option>
                        ))}
                      </datalist>
                    <em>{selectedDataFileProfile.description} 也可输入符合规范的 CSV 路径。</em>
                  </label>
                </div>

                <div className="training-string-grid studio-string-grid">
                  <label>
                    <small>仿真场景</small>
                    <input
                      value={trainingParams.scenario}
                      onChange={(event) => setTrainingParams((current) => ({ ...current, scenario: event.target.value }))}
                    />
                  </label>
                  <label>
                    <small>资产组</small>
                    <input
                      value={trainingParams.asset_group}
                      onChange={(event) => setTrainingParams((current) => ({ ...current, asset_group: event.target.value }))}
                    />
                  </label>
                  <label>
                    <small>安全护栏</small>
                      <input value="strict · environment constraints" readOnly />
                      <em>数据包声明的 v1/v2/v3 环境契约，固定 60 分钟 step。</em>
                  </label>
                </div>

                <div className="studio-subtitle">全部训练参数</div>
                <div className="training-param-grid studio-param-grid">
                  {trainingParamFields.map((field) => (
                    <label key={field.key}>
                      <small>{field.label}</small>
                      <input
                        type="number"
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
                  {Object.entries(rewardWeightLabels).map(([key, label]) => (
                    <label key={key}>
                      <small>{label}</small>
                      <input
                        type="number"
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
                  <button type="button" onClick={() => startTraining()}><ShieldCheck size={14} />生成确认面板</button>
                  <button id="btnConfirmTraining" type="button" disabled={!trainingReviewOpen} onClick={confirmStartTraining}><Play size={14} />确认开始训练</button>
                </div>
              </aside>
            </div>
          </div>
        </section>
      )}

      {commandCenterOpen && (
        <section className="command-center-backdrop" aria-label="小懿指令中心">
          <div className="command-center-modal" role="dialog" aria-modal="true">
            <div className="command-center-head">
              <div>
                <p>Xiaoyi Command Center</p>
                <h2>小懿指令中心</h2>
              </div>
              <button className="icon-btn" type="button" onClick={() => setCommandCenterOpen(false)} aria-label="关闭小懿指令中心">
                <X size={18} />
              </button>
            </div>
            <div className="command-center-toolbar">
              <input
                value={commandSearch}
                onChange={(event) => setCommandSearch(event.target.value)}
                placeholder="搜索：岸电 / 碳排 / 训练 / 模拟器 / API"
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
                        <button type="button" title={`判断：${profile.command}`} onClick={() => judgeCommandShortcut(shortcut)}><Bot size={13} />判断</button>
                        <button type="button" title={`执行：${profile.command}`} onClick={() => executeCommandShortcut(shortcut)}><Play size={13} />执行</button>
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
                        <button type="button" title={`判断：${shortcut.command}`} onClick={() => judgeCommandShortcut(shortcut)}><Bot size={13} />判断</button>
                        <button type="button" title={`执行：${shortcut.command}`} onClick={() => executeCommandShortcut(shortcut)}><Play size={13} />执行</button>
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
        <section className={`stage-modal-layer ${stageModal.kind}`} aria-label="小懿阶段确认弹窗">
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
                  <button id="btnStageConfirmTraining" type="button" onClick={confirmStartTraining}><Play size={14} />确认无误，开始训练</button>
                </>
              ) : stageModal.kind === 'done' ? (
                <button type="button" onClick={() => setStageModal(null)}><CheckCircle2 size={14} />知道了</button>
              ) : (
                <span><CheckCircle2 size={14} />本阶段确认无误，小懿继续执行</span>
              )}
            </div>
          </div>
        </section>
      )}
    </>
  );
}
