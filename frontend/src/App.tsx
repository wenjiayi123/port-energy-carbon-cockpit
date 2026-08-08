import { useEffect, useRef, useState } from 'react';
import {
  Activity,
  BatteryCharging,
  Bot,
  CheckCircle2,
  CircleAlert,
  Gauge,
  Leaf,
  Network,
  Pause,
  Play,
  Radio,
  RefreshCw,
  ServerCog,
  ShipWheel,
  Square,
  X,
  Zap,
} from 'lucide-react';
import { PortCommandCenter, type OperationalRuntimeState } from './components/PortCommandCenter';
import {
  DecisionImpactOverlay,
  type DecisionImpactReport,
  type DecisionImpactState,
} from './components/DecisionImpactOverlay';
import { XiaoyiLinkageHub } from './components/XiaoyiLinkageHub';
import { recomputeDashboard } from './lib/api';
import type { DashboardSnapshot, RlRewardTracePoint } from './types/dashboard';

type TopPanelId = 'simulation' | 'marl' | 'carbon' | 'shore' | 'api';

interface TopPanelMeta {
  id: TopPanelId;
  label: string;
  en: string;
  icon: JSX.Element;
}

type OperationalMode = 'refresh' | 'vessel' | 'berth' | 'crane' | 'yard' | 'agv' | 'shore' | 'peak' | 'renewable' | 'traffic' | 'twin' | 'schedule' | 'carbon' | 'comparison' | 'health';

interface OperationalDefinition {
  zh: string;
  en: string;
  scopeZh: string;
  scopeEn: string;
  descriptionZh: string;
  descriptionEn: string;
  primaryZh: string;
  primaryEn: string;
  mode: OperationalMode;
}

const vesselOperationContexts = [
  { id: 'vessel-0', name: 'TEST-STEP-01', eta: '00:00', berth: 'B1', status: '离线测试轨迹', statusEn: 'Held-out rollout' },
  { id: 'vessel-1', name: 'TEST-STEP-02', eta: '01:00', berth: 'B2', status: '离线测试轨迹', statusEn: 'Held-out rollout' },
  { id: 'vessel-2', name: 'TEST-STEP-03', eta: '02:00', berth: 'B3', status: '离线测试轨迹', statusEn: 'Held-out rollout' },
  { id: 'vessel-3', name: 'TEST-STEP-04', eta: '03:00', berth: 'B4', status: '离线测试轨迹', statusEn: 'Held-out rollout' },
  { id: 'vessel-4', name: 'TEST-STEP-05', eta: '04:00', berth: 'B1', status: '离线测试轨迹', statusEn: 'Held-out rollout' },
  { id: 'vessel-5', name: 'TEST-STEP-06', eta: '05:00', berth: 'B2', status: '离线测试轨迹', statusEn: 'Held-out rollout' },
  { id: 'vessel-6', name: 'TEST-STEP-07', eta: '06:00', berth: 'B3', status: '离线测试轨迹', statusEn: 'Held-out rollout' },
  { id: 'vessel-7', name: 'TEST-STEP-08', eta: '07:00', berth: 'B4', status: '离线测试轨迹', statusEn: 'Held-out rollout' },
] as const;

const vesselOperationalDefinitions = Object.fromEntries(vesselOperationContexts.map((vessel) => [
  vessel.id,
  {
    zh: `${vessel.name} 作业详情`,
    en: `${vessel.name} operation detail`,
    scopeZh: `${vessel.berth} · 测试时刻 ${vessel.eta}`,
    scopeEn: `${vessel.berth} · test time ${vessel.eta}`,
    descriptionZh: `查看 ${vessel.name} 的测试时刻、抽象泊位与环境动作。`,
    descriptionEn: `Review ${vessel.name} test time, abstract berth, and environment action.`,
    primaryZh: `定位 ${vessel.name} 作业`,
    primaryEn: `Focus ${vessel.name}`,
    mode: 'vessel',
  } satisfies OperationalDefinition,
])) as Record<string, OperationalDefinition>;

const operationalDefinitions: Record<string, OperationalDefinition> = {
  throughput: { zh: '测试分区吞吐量详情', en: 'Test-split throughput detail', scopeZh: '公开月度数据映射的测试轨迹', scopeEn: 'Held-out rollout mapped from public monthly data', descriptionZh: '查看测试分区处理量与轨迹变化；刷新会重新计算离线快照。', descriptionEn: 'Review held-out throughput and recompute the offline snapshot.', primaryZh: '刷新测试数据', primaryEn: 'Refresh test data', mode: 'refresh' },
  'vessel-ops': { zh: '测试步作业详情', en: 'Test-step operation detail', scopeZh: '环境生成的抽象作业步', scopeEn: 'Abstract environment operation steps', descriptionZh: '定位当前测试步，并重放留出集轨迹。', descriptionEn: 'Focus a held-out step and replay the test trajectory.', primaryZh: '定位测试步', primaryEn: 'Focus test step', mode: 'vessel' },
  ...vesselOperationalDefinitions,
  'vessel-queue': { zh: '测试轨迹队列', en: 'Held-out trajectory queue', scopeZh: '公开数据集测试分区', scopeEn: 'Public dataset test split', descriptionZh: '展示环境输出的时间步、泊位、资源动作和约束结果，不冒充实时船期。', descriptionEn: 'Inspect test-step actions and constraints; no live vessel schedule is claimed.', primaryZh: '刷新测试轨迹', primaryEn: 'Refresh test trajectory', mode: 'vessel' },
  'berth-plan': { zh: '泊位分配计划', en: 'Berth allocation plan', scopeZh: 'B01–B04 作业窗口', scopeEn: 'B01–B04 operating windows', descriptionZh: '核对靠泊窗口、泊位可用性和岸电接入约束，再应用计划变更。', descriptionEn: 'Verify berth windows, availability, and shore-power constraints before applying the plan.', primaryZh: '应用泊位计划', primaryEn: 'Apply berth plan', mode: 'berth' },
  'berth-b01': { zh: 'B1 测试步详情', en: 'B1 test-step detail', scopeZh: '离线轨迹中的 B1 动作', scopeEn: 'B1 action in held-out rollout', descriptionZh: '查看 B1 时间步的资源分配和计量结果。', descriptionEn: 'Inspect resource allocation and measured results for a B1 test step.', primaryZh: '定位 B1 测试步', primaryEn: 'Focus B1 test step', mode: 'vessel' },
  'berth-b02': { zh: 'B2 测试步详情', en: 'B2 test-step detail', scopeZh: '离线轨迹中的 B2 动作', scopeEn: 'B2 action in held-out rollout', descriptionZh: '查看 B2 时间步的资源分配和约束结果。', descriptionEn: 'Inspect resource allocation and constraints for a B2 test step.', primaryZh: '定位 B2 测试步', primaryEn: 'Focus B2 test step', mode: 'vessel' },
  'berth-b03': { zh: 'B3 测试步详情', en: 'B3 test-step detail', scopeZh: '离线轨迹中的 B3 动作', scopeEn: 'B3 action in held-out rollout', descriptionZh: '查看 B3 测试步的资源动作；公开数据不含生产岸桥计划。', descriptionEn: 'Inspect a B3 action; no production crane plan is claimed.', primaryZh: '定位 B3 测试步', primaryEn: 'Focus B3 test step', mode: 'crane' },
  'berth-b04': { zh: 'B4 测试步详情', en: 'B4 test-step detail', scopeZh: '离线轨迹中的 B4 动作', scopeEn: 'B4 action in held-out rollout', descriptionZh: '查看 B4 测试步的岸电动作；公开数据不含真实泊位可用性。', descriptionEn: 'Inspect a B4 shore-power action; live berth availability is not available.', primaryZh: '定位 B4 测试步', primaryEn: 'Focus B4 test step', mode: 'shore' },
  'crane-plan': { zh: '岸桥资源动作', en: 'Crane resource action', scopeZh: '环境动作中的岸桥比例', scopeEn: 'Crane ratio from environment action', descriptionZh: '只展示当前测试轨迹的岸桥投入；设备可用性尚未接入。', descriptionEn: 'Shows the test action only; equipment availability is not connected.', primaryZh: '查看岸桥动作', primaryEn: 'Inspect crane action', mode: 'crane' },
  'yard-occupancy': { zh: '堆场数据边界', en: 'Yard data boundary', scopeZh: '当前数据集无堆场占用率', scopeEn: 'No yard occupancy in current dataset', descriptionZh: '仅有环境输出的场内车辆资源比例，不构造堆场占用数值。', descriptionEn: 'No synthetic yard occupancy is generated.', primaryZh: '查看数据边界', primaryEn: 'Inspect data boundary', mode: 'yard' },
  'agv-dispatch': { zh: 'AGV 数据边界', en: 'AGV data boundary', scopeZh: '当前数据集无 AGV 遥测', scopeEn: 'No AGV telemetry in current dataset', descriptionZh: '环境只提供抽象的场内车辆资源动作，不冒充 AGV 生产调度。', descriptionEn: 'The environment action is not presented as production AGV telemetry.', primaryZh: '查看数据边界', primaryEn: 'Inspect data boundary', mode: 'agv' },
  alerts: { zh: '运行与约束状态', en: 'Runtime and constraint status', scopeZh: 'API 健康、训练异常与环境约束', scopeEn: 'API health, training errors, and environment constraints', descriptionZh: '刷新已接入系统的健康状态；天气、吃水和设备告警尚未接入。', descriptionEn: 'Refresh connected runtime health; weather, draft, and equipment alerts are not connected.', primaryZh: '刷新运行状态', primaryEn: 'Refresh runtime status', mode: 'health' },
  'twin-map': { zh: '测试轨迹可视化', en: 'Held-out trajectory replay', scopeZh: '测试分区的环境事件回放', scopeEn: 'Environment events from the test split', descriptionZh: '刷新离线测试轨迹并回到第一个时间步。', descriptionEn: 'Refresh the held-out rollout and return to its first step.', primaryZh: '刷新测试轨迹', primaryEn: 'Refresh test replay', mode: 'twin' },
  timeline: { zh: '测试轨迹时间线', en: 'Test trajectory timeline', scopeZh: 'B01–B04 抽象环境时间步', scopeEn: 'Abstract B01–B04 environment steps', descriptionZh: '重新计算留出集轨迹并定位到起始时间步；不是生产船期。', descriptionEn: 'Recompute the held-out rollout and return to its first step; this is not a live schedule.', primaryZh: '刷新测试时间线', primaryEn: 'Refresh test timeline', mode: 'schedule' },
  'energy-load': { zh: '测试轨迹能耗与负荷', en: 'Test trajectory energy and load', scopeZh: '环境计算的用电、辅机能耗和峰值约束', scopeEn: 'Environment energy and peak constraints', descriptionZh: '在当前奖励权重下重算测试轨迹。', descriptionEn: 'Recompute the held-out trajectory using the active reward weights.', primaryZh: '重算能耗轨迹', primaryEn: 'Recompute energy trajectory', mode: 'refresh' },
  'renewable-mix': { zh: '能源来源数据边界', en: 'Energy-source data boundary', scopeZh: '当前只有 eGRID 综合排放因子', scopeEn: 'Only an aggregate eGRID factor is available', descriptionZh: '当前数据不含光伏、风电或分时电源结构，因此不生成伪比例。', descriptionEn: 'No synthetic solar or wind shares are generated.', primaryZh: '查看数据边界', primaryEn: 'Inspect data boundary', mode: 'renewable' },
  'carbon-market': { zh: '碳排趋势与配额', en: 'Carbon trend and quota', scopeZh: '碳强度、碳排趋势与碳成本', scopeEn: 'Carbon intensity, trend, and cost', descriptionZh: '按当前碳价与低碳偏好重新计算碳排、配额和成本影响。', descriptionEn: 'Recompute emissions, quota, and cost impact using the active carbon price and low-carbon preference.', primaryZh: '重算碳排与配额', primaryEn: 'Recompute carbon and quota', mode: 'carbon' },
  'cost-analysis': { zh: '综合成本分析', en: 'Operating cost analysis', scopeZh: '能耗、时延与碳成本', scopeEn: 'Energy, delay, and carbon cost', descriptionZh: '刷新综合成本模型，保留当前策略权重和安全约束。', descriptionEn: 'Refresh the operating-cost model while retaining current policy weights and safety constraints.', primaryZh: '刷新成本分析', primaryEn: 'Refresh cost analysis', mode: 'refresh' },
  'strategy-comparison': { zh: '控制基线与 RL 策略对比', en: 'Control baseline versus RL comparison', scopeZh: '能耗、碳排与成本基线', scopeEn: 'Energy, carbon, and cost baselines', descriptionZh: '在独立测试集上对比 MPC 控制基线与已训练 RL 策略。', descriptionEn: 'Compare the MPC control baseline and trained RL policy on the held-out split.', primaryZh: '运行策略对比', primaryEn: 'Run policy comparison', mode: 'comparison' },
  'recommendation-0': { zh: '检查泊位资源动作', en: 'Inspect berth resource action', scopeZh: '当前测试时间步', scopeEn: 'Current held-out test step', descriptionZh: '检查环境输出的泊位、岸桥和车辆资源比例。', descriptionEn: 'Inspect environment berth, crane, and vehicle ratios.', primaryZh: '查看当前动作', primaryEn: 'Inspect current action', mode: 'berth' },
  'recommendation-1': { zh: '检查岸电动作', en: 'Inspect shore-power action', scopeZh: '当前测试时间步', scopeEn: 'Current held-out test step', descriptionZh: '查看岸电比例、负荷和排放结果。', descriptionEn: 'Inspect shore-power ratio, load, and emissions.', primaryZh: '查看岸电动作', primaryEn: 'Inspect shore action', mode: 'shore' },
  'recommendation-2': { zh: '检查测试步资源动作', en: 'Inspect test-step resource action', scopeZh: '环境输出的岸桥资源比例', scopeEn: 'Crane resource ratio from the environment', descriptionZh: '定位对应测试步并读取策略输出，不改写生产岸桥计划。', descriptionEn: 'Inspect the matching test step without changing a production crane plan.', primaryZh: '查看资源动作', primaryEn: 'Inspect resource action', mode: 'crane' },
  'recommendation-3': { zh: 'AGV 数据未接入', en: 'AGV data not connected', scopeZh: '数据边界', scopeEn: 'Data boundary', descriptionZh: '接入 AGV 遥测列后才可训练和评估具体充电动作。', descriptionEn: 'AGV telemetry is required before training concrete charging actions.', primaryZh: '查看数据边界', primaryEn: 'Inspect data boundary', mode: 'agv' },
  'recommendation-4': { zh: '检查环境峰值约束', en: 'Inspect environment peak constraint', scopeZh: '当前留出集轨迹', scopeEn: 'Current held-out rollout', descriptionZh: '按削峰奖励权重重算环境轨迹并读取实际峰值越界量。', descriptionEn: 'Recompute with peak reward weights and inspect measured constraint violations.', primaryZh: '重算峰值约束', primaryEn: 'Recompute peak constraint', mode: 'peak' },
  'recommendation-5': { zh: '分时能源数据未接入', en: 'Time-varying energy mix not connected', scopeZh: '数据边界', scopeEn: 'Data boundary', descriptionZh: '当前只使用 eGRID 综合排放因子。', descriptionEn: 'The benchmark only uses an aggregate eGRID factor.', primaryZh: '查看数据边界', primaryEn: 'Inspect data boundary', mode: 'renewable' },
  'recommendation-6': { zh: '外集卡数据未接入', en: 'External truck arrivals not connected', scopeZh: '数据边界', scopeEn: 'Data boundary', descriptionZh: '当前只有环境的场内车辆资源动作。', descriptionEn: 'Only the abstract yard-vehicle control is available.', primaryZh: '查看数据边界', primaryEn: 'Inspect data boundary', mode: 'traffic' },
};

function formatNumber(value: number | undefined, digits = 1) {
  if (typeof value !== 'number' || Number.isNaN(value)) return '--';
  return new Intl.NumberFormat('zh-CN', {
    maximumFractionDigits: digits,
    minimumFractionDigits: digits,
  }).format(value);
}

function clampPercent(value: unknown) {
  const number = typeof value === 'number' ? value : Number(value);
  if (!Number.isFinite(number)) return 0;
  return Math.min(100, Math.max(0, number));
}

function eventLabel(event: string | undefined) {
  const labels: Record<string, string> = {
    shore_power_first_berth: '岸电优先靠泊',
    distributed_crane_allocation: '岸桥错峰分配',
    low_carbon_slot_swap: '低碳时段换窗',
    yard_flow_smoothing: '堆场流量平滑',
    quota_aware_operation: '碳配额感知作业',
    fast_departure_release: '快速离港释放',
  };
  return event ? labels[event] ?? event.replace(/_/g, ' ') : '--';
}

function preferenceLabel(value: number) {
  if (value >= 0.86) return '岸电优先';
  if (value >= 0.72) return '低碳优先';
  if (value <= 0.32) return '效率优先';
  return '均衡调度';
}

function cumulative(values: number[]) {
  let total = 0;
  return values.map((value) => {
    total += value;
    return total;
  });
}

function buildSvgSeries(values: number[], maxValue: number, width = 460, height = 112) {
  if (!values.length) return [];
  const horizontalStep = values.length > 1 ? width / (values.length - 1) : width;
  return values.map((value, index) => ({
    x: Math.round(index * horizontalStep),
    y: Math.round(height - (value / Math.max(1, maxValue)) * (height - 12) - 6),
    value,
  }));
}

async function fetchJson(path: string, options: RequestInit = {}) {
  const response = await fetch(path, {
    ...options,
    headers: options.body ? { 'Content-Type': 'application/json', ...options.headers } : options.headers,
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data.detail || response.statusText);
  }
  return data;
}

export function App() {
  const [greenPreference, setGreenPreference] = useState(0.5);
  const [carbonPrice, setCarbonPrice] = useState(85);
  const [snapshot, setSnapshot] = useState<DashboardSnapshot | null>(null);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [activePanel, setActivePanel] = useState<TopPanelId | null>(null);
  const [panelBusy, setPanelBusy] = useState(false);
  const [panelNotice, setPanelNotice] = useState('等待操作。');
  const [apiHealth, setApiHealth] = useState<Record<string, any> | null>(null);
  const [rlStatus, setRlStatus] = useState<Record<string, any> | null>(null);
  const [rlCapabilities, setRlCapabilities] = useState<Record<string, any> | null>(null);
  const [modelRegistry, setModelRegistry] = useState<Record<string, any> | null>(null);
  const [integrationStatus, setIntegrationStatus] = useState<Record<string, any> | null>(null);
  const [auditStatus, setAuditStatus] = useState<Record<string, any> | null>(null);
  const [landingEvidence, setLandingEvidence] = useState<Record<string, any> | null>(null);
  const [policyTest, setPolicyTest] = useState<Record<string, any> | null>(null);
  const [sailingStatus, setSailingStatus] = useState<Record<string, any> | null>(null);
  const [replayStep, setReplayStep] = useState(0);
  const [replayPlaying, setReplayPlaying] = useState(true);
  const [xiaoyiOpenToken, setXiaoyiOpenToken] = useState(0);
  const [activeOperation, setActiveOperation] = useState<string | null>(null);
  const [operationBusy, setOperationBusy] = useState(false);
  const [operationHistory, setOperationHistory] = useState<Record<string, string>>({});
  const [operationResults, setOperationResults] = useState<Record<string, string>>({});
  const [operationalState, setOperationalState] = useState<OperationalRuntimeState>({});
  const [decisionImpact, setDecisionImpact] = useState<DecisionImpactState | null>(null);
  const impactRunToken = useRef(0);

  const panelMeta: Record<TopPanelId, TopPanelMeta> = {
    simulation: { id: 'simulation', label: '离线仿真', en: 'Offline simulation', icon: <Activity size={16} /> },
    marl: { id: 'marl', label: 'RL 策略', en: 'RL policy', icon: <ShipWheel size={16} /> },
    carbon: { id: 'carbon', label: '低碳优先', en: 'Low-carbon priority', icon: <Leaf size={16} /> },
    shore: { id: 'shore', label: '岸电联动', en: 'Shore-power linkage', icon: <BatteryCharging size={16} /> },
    api: { id: 'api', label: isRefreshing ? '重算中' : 'API 已同步', en: isRefreshing ? 'Recomputing' : 'API synchronized', icon: <ServerCog size={16} /> },
  };
  const panelHeading: Record<TopPanelId, { zh: string; en: string }> = {
    simulation: { zh: '仿真状态与模拟器启动', en: 'Simulation status and simulator launch' },
    marl: { zh: 'RL 策略测试与真实训练状态', en: 'RL policy testing and measured training status' },
    carbon: { zh: '低碳偏好调度参数', en: 'Low-carbon preference dispatch parameters' },
    shore: { zh: '岸电窗口与优先训练', en: 'Shore-power windows and priority training' },
    api: { zh: 'API 同步与联动健康检查', en: 'API synchronization and linkage health check' },
  };

  const traditional = snapshot?.strategies[0];
  const marl = snapshot?.strategies[1];
  const marlTrajectory = marl?.trajectory ?? [];
  const traditionalTrajectory = traditional?.trajectory ?? [];
  const replaySteps = marlTrajectory.map((point, index) => ({
    marl: point,
    traditional: traditionalTrajectory[index] ?? null,
  }));
  const activeReplayIndex = replaySteps.length ? Math.min(replayStep, replaySteps.length - 1) : 0;
  const activeReplay = replaySteps[activeReplayIndex];
  const activeMarlPoint = activeReplay?.marl;
  const activeTraditionalPoint = activeReplay?.traditional;
  const replayProgress = replaySteps.length > 1 ? (activeReplayIndex / (replaySteps.length - 1)) * 100 : 0;
  const marlCumulativeCarbon = cumulative(marlTrajectory.map((point) => point.carbon_kg));
  const traditionalCumulativeCarbon = cumulative(traditionalTrajectory.map((point) => point.carbon_kg));
  const maxReplayCarbon = Math.max(1, ...marlCumulativeCarbon, ...traditionalCumulativeCarbon);
  const marlCarbonSeries = buildSvgSeries(marlCumulativeCarbon, maxReplayCarbon);
  const traditionalCarbonSeries = buildSvgSeries(traditionalCumulativeCarbon, maxReplayCarbon);
  const activeMarlCarbonPoint = marlCarbonSeries[activeReplayIndex];
  const activeTraditionalCarbonPoint = traditionalCarbonSeries[activeReplayIndex];
  const activeMarlCumulativeCarbon = marlCumulativeCarbon[activeReplayIndex] ?? 0;
  const activeTraditionalCumulativeCarbon = traditionalCumulativeCarbon[activeReplayIndex] ?? 0;
  const activeCumulativeSaving = activeTraditionalCumulativeCarbon - activeMarlCumulativeCarbon;
  const rewardTrace = snapshot?.rl_environment.reward_trace ?? [];
  const activeReward = rewardTrace[activeReplayIndex] ?? rewardTrace[rewardTrace.length - 1];
  const rewardBars: RlRewardTracePoint[] = rewardTrace.length ? rewardTrace : [
    { step: 0, reward: 0, carbon_penalty: 0, delay_penalty: 0, energy_penalty: 0, shore_power_bonus: 0 },
  ];
  const rewardMin = Math.min(...rewardBars.map((point) => point.reward));
  const rewardMax = Math.max(...rewardBars.map((point) => point.reward));
  const rewardRange = Math.max(1, rewardMax - rewardMin);
  const trainingProgress = clampPercent(rlStatus?.progress);
  const trainingState = String(rlStatus?.status ?? 'idle');
  const trainingCanPause = Boolean(rlStatus?.can_pause ?? trainingState === 'running');
  const trainingCanResume = Boolean(rlStatus?.can_resume ?? trainingState === 'paused');
  const trainingCanStop = Boolean(rlStatus?.can_stop ?? ['running', 'paused'].includes(trainingState));
  const rlLogs = Array.isArray(rlStatus?.logs) ? (rlStatus.logs as string[]) : [];
  const policyMetrics = policyTest?.metrics as Record<string, number> | undefined;
  const carbonStepSaving = (activeTraditionalPoint?.carbon_kg ?? 0) - (activeMarlPoint?.carbon_kg ?? 0);
  const delayStepSaving = (activeTraditionalPoint?.delay_minutes ?? 0) - (activeMarlPoint?.delay_minutes ?? 0);
  const rewardWeights = (rlStatus?.config?.reward_weights ?? {}) as Record<string, number>;
  const algorithmMatrix = Array.isArray(rlCapabilities?.algorithms)
    ? rlCapabilities.algorithms as Array<Record<string, any>>
    : [
      { id: 'ppo', name: 'PPO', family: 'reinforcement_learning', action_space: 'continuous' },
      { id: 'sac', name: 'SAC', family: 'reinforcement_learning', action_space: 'continuous' },
      { id: 'td3', name: 'TD3', family: 'reinforcement_learning', action_space: 'continuous' },
      { id: 'dqn', name: 'DQN', family: 'reinforcement_learning', action_space: '81 discrete' },
      { id: 'mpc', name: 'MPC', family: 'control_theory', action_space: '27-action beam search' },
    ];
  const shorePowerGain = (marl?.shore_power_usage_rate ?? 0) - (traditional?.shore_power_usage_rate ?? 0);
  const carbonReductionTon = ((traditional?.total_carbon_kg ?? 0) - (marl?.total_carbon_kg ?? 0)) / 1000;
  const shoreWindowCards = marlTrajectory.map((point, index) => {
    const traditionalPoint = traditionalTrajectory[index];
    const reductionKg = Math.max(0, (traditionalPoint?.carbon_kg ?? point.carbon_kg) - point.carbon_kg);
    const peakLoadKw = point.load_kw;
    const safetyOk = point.peak_violation_kw <= 0 && point.delay_minutes <= 120;
    const reason = point.shore_power_connected
      ? point.decision_reason
      : '峰值负荷与泊位周转优先，当前窗口保留燃油待机并等待下一轮岸电匹配。';
    return {
      ...point,
      reductionKg,
      peakLoadKw,
      safetyOk,
      reason,
    };
  });
  const activeShoreWindow = shoreWindowCards[activeReplayIndex] ?? shoreWindowCards[0];
  const maxPeakLoadKw = Math.max(1, ...shoreWindowCards.map((point) => point.peakLoadKw));
  const shoreConnectedCount = shoreWindowCards.filter((point) => point.shore_power_connected).length;
  const shoreTrainingActive = rlStatus?.config?.objective_id === 'shore_power_priority' && ['running', 'paused'].includes(String(rlStatus?.status));
  const projectedShoreRate = marl?.shore_power_usage_rate ?? 0;
  const projectedShoreLift = projectedShoreRate - (traditional?.shore_power_usage_rate ?? 0);
  const shoreSafetyConstraints = [
    { label: '电网容量超限', value: `${formatNumber(activeShoreWindow?.peak_violation_kw, 0)} kW`, ok: (activeShoreWindow?.peak_violation_kw ?? 0) <= 0 },
    { label: '延误护栏', value: `${formatNumber(activeMarlPoint?.delay_minutes, 1)} / 120 min`, ok: (activeMarlPoint?.delay_minutes ?? 0) <= 120 },
    { label: '岸电窗口互斥', value: `${activeShoreWindow?.berth_id ?? '--'} 单泊位`, ok: true },
    { label: '人工确认边界', value: rlStatus?.status === 'running' ? '训练中' : 'dry-run', ok: true },
  ];
  const carbonMarket = snapshot?.carbon_market;
  const carbonSourceEntries = Object.entries(snapshot?.carbon_model.source_breakdown_kg ?? {})
    .sort(([, left], [, right]) => right - left)
    .slice(0, 4);
  const maxCarbonSource = Math.max(1, ...carbonSourceEntries.map(([, value]) => value));
  const linkageSystems = (apiHealth?.linkage?.systems ?? {}) as Record<string, any>;
  const xiaoyiSystem = linkageSystems.xiaoyi_ai ?? {};
  const rlSystem = linkageSystems.rl_interface ?? {};
  const sailingSystem = linkageSystems.sailing_simulator ?? sailingStatus ?? {};
  const dashboardOnline = apiHealth?.health?.status === 'ok' || linkageSystems.energy_carbon_cockpit?.online === true;
  const topologyNodes = [
    {
      id: 'dashboard',
      label: '能碳驾驶舱',
      value: dashboardOnline ? 'online' : 'checking',
      detail: linkageSystems.energy_carbon_cockpit?.label ?? apiHealth?.health?.service ?? '等待健康检查',
      online: dashboardOnline,
      icon: <ServerCog size={18} />,
    },
    {
      id: 'xiaoyi',
      label: '小懿 AI',
      value: xiaoyiSystem.online ? 'online' : 'offline',
      detail: xiaoyiSystem.label ?? '待检查',
      online: xiaoyiSystem.online === true,
      icon: <Bot size={18} />,
    },
    {
      id: 'rl',
      label: 'RL 训练接口',
      value: rlSystem.online ? 'ready' : 'checking',
      detail: rlSystem.label ?? '待检查',
      online: rlSystem.online === true,
      icon: <Gauge size={18} />,
    },
    {
      id: 'sailing',
      label: '航行模拟器',
      value: sailingSystem.process?.running ? `pid ${sailingSystem.process.pid}` : (sailingSystem.launchable ? 'launchable' : 'offline'),
      detail: sailingSystem.label ?? '待检查',
      online: sailingSystem.launchable === true || sailingSystem.process?.running === true,
      icon: <ShipWheel size={18} />,
    },
    {
      id: 'godot',
      label: 'Godot Runtime',
      value: sailingSystem.godot_executable?.exists ? 'available' : 'missing',
      detail: sailingSystem.godot_executable?.path ?? '等待模拟器状态',
      online: sailingSystem.godot_executable?.exists === true,
      icon: <Activity size={18} />,
    },
  ];
  const routeEntries: [string, boolean][] = Object.entries((rlSystem.routes ?? {}) as Record<string, boolean>);
  const displayedRouteEntries: [string, boolean][] = routeEntries.length ? routeEntries : [
    ['/api/rl/train/status', false],
    ['/api/rl/simulate', false],
  ];
  const onlineRouteCount = routeEntries.filter(([, online]) => online).length;
  const systemHealthyCount = topologyNodes.filter((node) => node.online).length;
  const activePreference = preferenceLabel(greenPreference);
  const currentRlAlgorithm = String(rlStatus?.config?.algorithm ?? 'SAC').toUpperCase();
  const latestRegisteredPolicy = Array.isArray(modelRegistry?.policies) ? modelRegistry.policies[0] : null;
  const landingBusiness = landingEvidence?.business_metrics_vs_fixed_full_resources as Record<string, any> | undefined;
  const algorithmIncrement = landingEvidence?.algorithm_increment_vs_causal_legacy_mpc as Record<string, any> | undefined;
  const landingProtocol = landingEvidence?.protocol as Record<string, any> | undefined;
  const landingDataset = landingEvidence?.dataset?.landing_readiness as Record<string, any> | undefined;
  const landingStress = landingEvidence?.stress_tests as Record<string, any> | undefined;
  const stressEntries = Object.entries(landingStress ?? {}) as Array<[string, Record<string, any>]>;

  async function runDecisionImpact(report: DecisionImpactReport, task?: () => Promise<void> | void, showResultReport = true) {
    const runToken = impactRunToken.current + 1;
    impactRunToken.current = runToken;
    setDecisionImpact({ report, phase: 'running', progress: 10, stageIndex: 0 });
    const [taskResult] = await Promise.allSettled([Promise.resolve().then(() => task?.())]);
    if (impactRunToken.current !== runToken) return;
    const error = taskResult.status === 'rejected' ? String(taskResult.reason) : undefined;
    if (!showResultReport && !error) {
      setDecisionImpact(null);
    } else {
      setDecisionImpact({
        report,
        phase: 'done',
        progress: 100,
        stageIndex: Math.max(0, report.phases.length - 1),
        error,
      });
      if (!error && report.autoCloseMs) {
        window.setTimeout(() => {
          setDecisionImpact((current) => current?.report.id === report.id ? null : current);
        }, report.autoCloseMs);
      }
    }
  }

  function recommendationTabImpact(tab: 'recommended' | 'all'): DecisionImpactReport {
    const allOptions = tab === 'all';
    return {
      id: `recommendation-tab-${tab}-${Date.now()}`,
      eyebrow: allOptions ? 'CANDIDATE POLICY SPACE' : 'PRIORITY POLICY RANKING',
      title: allOptions ? '7 条可选调度路径已展开' : '推荐动作优先级已重新计算',
      subtitle: allOptions
        ? '系统保留泊位、岸桥、AGV、削峰、能源结构和集卡等替代路径，供值班人员比较。'
        : 'SAC 策略输出经过安全、船期、电网容量与经营成本约束评分后，形成当前推荐顺序。',
      algorithm: `${currentRlAlgorithm} + 多目标约束评分`,
      algorithmDetail: 'RL 负责连续调度偏好，规则层负责安全、船期、泊位兼容和变电站容量硬约束；这里展示排序结果，不会自动生产下发。',
      objective: allOptions ? '保留可选路径与人工判断空间' : '碳排、延误、能耗与成本综合最优',
      scope: allOptions ? '7 条候选方案 · 船/机/车/电/场' : 'Top 3 推荐动作 · 当前班次',
      phases: [
        { label: '读取状态', detail: '正在读取船期、泊位、岸桥、AGV、堆场与用电峰值。' },
        { label: '生成候选', detail: '正在展开可行动作并剔除违反安全边界的组合。' },
        { label: '多目标评分', detail: '正在计算碳排、延误、能耗、成本和岸电收益。' },
        { label: '人工可读', detail: '正在把策略输出翻译成对象、时间窗口和预期影响。' },
      ],
      actions: allOptions
        ? ['展开泊位/岸桥/AGV/削峰/能源/集卡 7 条路径', '保留每条路径的作用对象、窗口和预期影响', '不改变任何生产状态']
        : ['按硬约束过滤不可执行路径', '按综合收益和置信度重排优先级', '把岸电窗口与业务对象绑定'],
      risks: [
        { level: 'guard', label: '安全硬约束', detail: '风速、吃水、设备与电网边界不可突破' },
        { level: 'watch', label: '推荐不等于执行', detail: '值班人员仍需打开详情并人工确认' },
      ],
      recommendations: ['先比较全部路径，再回到推荐动作核对优先级', '执行前重点复核变电站峰值与岸电兼容性'],
      results: [
        { label: '候选方案', value: allOptions ? '7' : 'TOP 3', detail: allOptions ? '完整保留' : '综合排序', tone: 'blue' },
        { label: '硬约束', value: '4 类', detail: '安全/船期/泊位/电网', tone: 'amber' },
        { label: '策略引擎', value: currentRlAlgorithm, detail: 'Continuous RL', tone: 'green' },
        { label: '生产下发', value: '0', detail: '等待人工确认', tone: 'blue' },
      ],
    };
  }

  function operationalImpact(actionId: string, executing: boolean): DecisionImpactReport {
    const definition = operationalDefinitions[actionId] ?? operationalDefinitions['twin-map'];
    const isShore = definition.mode === 'shore';
    const algorithm = ['shore', 'carbon', 'renewable', 'peak'].includes(definition.mode)
      ? `${currentRlAlgorithm} · Continuous RL`
      : ['berth', 'crane', 'yard', 'agv', 'traffic'].includes(definition.mode)
        ? 'RL Policy · PortEnergyDispatchEnv'
        : '约束规则引擎 · 离线快照';
    const verb = executing ? '离线计算与回放' : '建议作用域解析';
    const shoreReduction = (snapshot?.carbon_model.shore_power_reduction_kg ?? 0) / 1000;
    return {
      id: `operation-${actionId}-${executing ? 'execute' : 'inspect'}-${Date.now()}`,
      eyebrow: executing ? 'HUMAN CONFIRMED OFFLINE ANALYSIS' : 'ACTION SCOPE INSPECTION',
      title: `${definition.zh} · ${verb}`,
      subtitle: executing
        ? '人工确认已记录，系统正在离线测试集上重算或定位轨迹，不会写入生产业务状态。'
        : '系统已解析作用对象、时间窗口、模型依据与执行边界；当前仍是待确认状态。',
      algorithm,
      algorithmDetail: isShore
        ? 'SAC 适合连续权重调度：提高岸电奖励，同时保留峰值负荷、延误、泊位互斥和人工确认护栏。'
        : 'Gymnasium adapter 将策略动作转换为统一的泊位、岸桥、车辆、能源与堆场事件，再由约束层校验。',
      objective: isShore ? '岸电接入收益最大化 + 峰值与延误受控' : definition.descriptionZh,
      scope: definition.scopeZh,
      phases: executing
        ? [
          { label: '锁定对象', detail: `正在锁定 ${definition.scopeZh}，避免作用域漂移。` },
          { label: '安全校验', detail: '正在校验风速、吃水、泊位互斥、设备与变电站容量。' },
          { label: '离线计算', detail: `正在分析：${definition.primaryZh}。` },
          { label: 'KPI 快照', detail: '正在从环境轨迹重算能耗、碳强度、延误与成本。' },
        ]
        : [
          { label: '定位对象', detail: `正在解析 ${definition.scopeZh}。` },
          { label: '读取模型', detail: `正在读取 ${algorithm} 的当前策略输出。` },
          { label: '校验边界', detail: '正在识别安全、船期、电网和岗位责任边界。' },
          { label: '生成详情', detail: '正在生成待确认业务动作报告。' },
        ],
      actions: isShore
        ? ['将绿色偏好切换到岸电优先 0.88', '在统一测试集上重新滚动求解', '刷新离线轨迹与驾驶舱 KPI']
        : [definition.descriptionZh, '定位或重算离线测试轨迹', '保留生产系统隔离边界'],
      risks: [
        { level: 'guard', label: '人工确认边界', detail: executing ? '已确认运行离线分析，未改变生产计划' : '当前仍为待确认，未改变生产计划' },
        { level: 'watch', label: isShore ? '变电站峰值' : '资源冲突', detail: isShore ? '岸电、岸桥、冷藏箱与 AGV 充电可能叠加' : '需持续监控船期、设备和场内交通变化' },
        { level: 'guard', label: '安全越界', detail: `${policyTest?.metrics?.safety_violations ?? 0} · 超限时拒绝下发` },
      ],
      recommendations: isShore
        ? ['保留燃油待机作为兼容性或峰值异常时的回退路径', '执行后同时检查总碳排、峰值容量和综合成本']
        : ['执行后检查测试轨迹 KPI 与回放因果链', '接入生产告警后需重新运行约束校验'],
      results: [
        { label: executing ? '分析状态' : '当前状态', value: executing ? '已计算' : '待确认', detail: executing ? '离线快照' : '未生产下发', tone: executing ? 'green' : 'amber' },
        { label: '轨迹指标', value: operationalMetric(actionId), detail: definition.scopeZh, tone: 'blue' },
        { label: isShore ? '岸电替代减排' : '策略引擎', value: isShore ? `${formatNumber(shoreReduction, 2)} t` : algorithm.split(' · ')[0], detail: isShore ? '当前仿真快照' : '当前策略', tone: 'green' },
        { label: '安全越界', value: String(policyTest?.metrics?.safety_violations ?? 0), detail: '硬约束保持', tone: 'amber' },
      ],
    };
  }

  function scenarioImpact(mode: 'baseline' | 'optimized' | 'low-carbon'): DecisionImpactReport {
    const isLowCarbon = mode === 'low-carbon';
    const targetPreference = mode === 'baseline' ? 0.25 : mode === 'optimized' ? 0.5 : 0.82;
    const scenarioLabel = mode === 'baseline' ? '基线方案' : mode === 'optimized' ? '综合优化' : '低碳优先';
    return {
      id: `scenario-${mode}-${Date.now()}`,
      eyebrow: 'MULTI-OBJECTIVE SCENARIO SWITCH',
      title: `${scenarioLabel}权重已装载`,
      subtitle: `调度偏好切换到 ${targetPreference.toFixed(2)}，安全、船期、设备和电网约束继续作为不可突破的硬边界。`,
      algorithm: isLowCarbon ? 'SAC · Carbon-Min Continuous RL' : `${currentRlAlgorithm} · Multi-objective Policy`,
      algorithmDetail: isLowCarbon
        ? 'SAC 提高碳排、岸电与可再生时段的奖励权重，在连续动作空间中调节资源偏好。'
        : '同一策略环境下调整奖励权重，用于比较传统效率优先与多目标平衡路径。',
      objective: isLowCarbon ? '碳排最小化，兼顾延误、成本与安全' : '能耗、碳排、成本与时延综合权衡',
      scope: `全港调度 · 权重 ${targetPreference.toFixed(2)}`,
      phases: [
        { label: '冻结基线', detail: '正在保存当前班次、设备与能源状态作为对照。' },
        { label: '注入偏好', detail: `正在把 ${scenarioLabel} 权重 ${targetPreference.toFixed(2)} 注入策略环境。` },
        { label: '约束校验', detail: '正在校验船期、安全、泊位和电网容量硬约束。' },
        { label: '重算快照', detail: '正在更新碳排、能耗、成本与岸电利用结果。' },
      ],
      actions: ['更新绿色调度偏好', '保留船期、安全、设备与电网硬约束', '为下一次场景推演准备统一初始状态'],
      risks: [
        { level: 'guard', label: '安全与船期', detail: '权重变化不能绕过硬约束' },
        { level: 'watch', label: '电力负荷转移', detail: '岸电增加可能抬高港区瞬时用电' },
      ],
      recommendations: ['下一步点击“运行推演”比较完整轨迹', '重点观察测试轨迹的峰值约束与岸电动作'],
      results: [
        { label: '低碳权重', value: targetPreference.toFixed(2), detail: scenarioLabel, tone: 'green' },
        { label: '预计碳排', value: `${formatNumber((marl?.total_carbon_kg ?? 0) / 1000, 1)} t`, detail: '当前优化快照', tone: 'blue' },
        { label: '岸电使用', value: `${formatNumber(marl?.shore_power_usage_rate, 1)}%`, detail: '策略轨迹', tone: 'green' },
        { label: '硬约束', value: 'ACTIVE', detail: '不可突破', tone: 'amber' },
      ],
    };
  }

  function simulationImpact(): DecisionImpactReport {
    return {
      id: `simulation-run-${Date.now()}`,
      autoCloseMs: 4800,
      eyebrow: 'DIGITAL TWIN POLICY ROLLOUT',
      title: '低碳场景推演已完成',
      subtitle: '同一测试集下完成控制基线与优化策略双轨迹回放。',
      algorithm: `${currentRlAlgorithm} Policy + Gymnasium Adapter`,
      algorithmDetail: '策略通过 Gymnasium reset/step 事件流输出调度动作；驾驶舱将每一步映射为船舶、泊位、岸桥、车辆、岸电、能耗、碳排与延误。',
      objective: '验证低碳策略相对传统基线的累计收益',
      scope: `${snapshot?.scenario_id ?? 'port_la_2025_public_benchmark'} · ${replaySteps.length} 个时序节点`,
      phases: [
        { label: '环境 Reset', detail: '正在恢复统一船期、泊位、设备与能源初始状态。' },
        { label: '策略 Rollout', detail: '正在逐步生成岸电、岸桥、换窗与堆场动作。' },
        { label: '基线对照', detail: '正在与先到先服务和固定资源顺序进行同场景比较。' },
        { label: '孪生回写', detail: '正在生成累计曲线、节点原因和业务 KPI。' },
      ],
      actions: ['重放每个环境 step 及资源动作', '同步控制基线/RL 累计碳排曲线', '将奖励项、单步减排和延误写入节点详情'],
      risks: [
        { level: 'guard', label: '仿真隔离', detail: '本次推演不直接改变生产计划' },
        { level: 'watch', label: '模型偏差', detail: '实际 TOS、天气与设备状态变化时需重算' },
      ],
      recommendations: ['点击第 2 与第 5 个节点核对调度因果链', '关注累计减排是否来自多次真实动作而非终值修饰'],
      results: [
        { label: '累计减排', value: `${formatNumber(((traditional?.total_carbon_kg ?? 0) - (marl?.total_carbon_kg ?? 0)) / 1000, 2)} t`, detail: '优化策略 vs 控制基线', tone: 'green' },
        { label: '能耗差异', value: `${formatNumber(((traditional?.total_energy_kwh ?? 0) - (marl?.total_energy_kwh ?? 0)) / 1000, 2)} MWh`, detail: '同场景对照', tone: 'blue' },
        { label: '岸电提升', value: `${formatNumber(shorePowerGain, 1)} pp`, detail: '百分点', tone: 'green' },
        { label: '时序节点', value: String(replaySteps.length), detail: '可逐步解释', tone: 'amber' },
      ],
    };
  }

  function replayNodeImpact(index: number): DecisionImpactReport {
    const marlPoint = replaySteps[index]?.marl;
    const baselinePoint = replaySteps[index]?.traditional;
    const savingKg = (baselinePoint?.carbon_kg ?? 0) - (marlPoint?.carbon_kg ?? 0);
    const savedDelay = (baselinePoint?.delay_minutes ?? 0) - (marlPoint?.delay_minutes ?? 0);
    return {
      id: `replay-node-${index}-${Date.now()}`,
      autoCloseMs: 3800,
      eyebrow: `HELD-OUT TRACE · STEP ${marlPoint?.step ?? index + 1}`,
      title: `${marlPoint?.time ?? '--'} · ${eventLabel(marlPoint?.event)}`,
      subtitle: marlPoint?.decision_reason ?? '正在读取当前调度节点的决策原因。',
      algorithm: `${currentRlAlgorithm} Policy · Gymnasium step(action)`,
      algorithmDetail: '当前节点展示策略动作如何改变泊位、岸电、岸桥和车辆状态，并与同一步传统调度结果对照。',
      objective: '解释单步动作如何累积为最终减排与延误改善',
      scope: `${marlPoint?.vessel_id ?? '待定船舶'} · ${marlPoint?.berth_id ?? '待定泊位'}`,
      phases: [
        { label: '锁定节点', detail: `正在定位 STEP ${marlPoint?.step ?? index + 1} 的船舶与泊位。` },
        { label: '读取动作', detail: `正在解析 ${eventLabel(marlPoint?.event)} 的策略行为。` },
        { label: '对照基线', detail: '正在计算与 Traditional 同一步的能耗、碳排和延误差异。' },
        { label: '生成解释', detail: '正在把 reward 与动作因果翻译为港口业务语言。' },
      ],
      actions: [
        `${marlPoint?.vessel_id ?? '船舶'} 在 ${marlPoint?.berth_id ?? '泊位'} 执行“${eventLabel(marlPoint?.event)}”`,
        `配置 ${marlPoint?.crane_count ?? '--'} 台岸桥、${marlPoint?.yard_truck_count ?? '--'} 台集卡`,
        marlPoint?.shore_power_connected ? '接入岸电并替代船上燃油负荷' : '保留燃油待机并等待更优岸电窗口',
      ],
      risks: [
        { level: 'guard', label: '延误护栏', detail: `${formatNumber(marlPoint?.delay_minutes, 1)} / 120 min` },
        { level: marlPoint?.shore_power_connected ? 'watch' : 'guard', label: '岸电状态', detail: marlPoint?.shore_power_connected ? '需持续监控峰值负荷与兼容性' : '未强行接电，保留安全回退' },
      ],
      recommendations: ['结合前后节点观察累计曲线，而非孤立评价单步', '若峰值或延误接近边界，保留下一窗口重新匹配'],
      results: [
        { label: '单步减排', value: `${formatNumber(savingKg, 0)} kg`, detail: '相对 Traditional', tone: 'green' },
        { label: '延误压缩', value: `${formatNumber(savedDelay, 1)} min`, detail: '同一节点', tone: 'blue' },
        { label: '本步能耗', value: `${formatNumber(marlPoint?.energy_kwh, 0)} kWh`, detail: `${marlPoint?.crane_count ?? '--'} 台岸桥`, tone: 'amber' },
        { label: '岸电状态', value: marlPoint?.shore_power_connected ? 'CONNECTED' : 'STANDBY', detail: marlPoint?.berth_id ?? '--', tone: marlPoint?.shore_power_connected ? 'green' : 'amber' },
      ],
    };
  }

  useEffect(() => {
    let active = true;
    setIsRefreshing(true);
    const timer = window.setTimeout(() => {
      recomputeDashboard({
        green_preference: greenPreference,
        carbon_price_cny_per_ton: carbonPrice,
      })
        .then((nextSnapshot) => {
          if (active) {
            setSnapshot(nextSnapshot);
          }
        })
        .finally(() => {
          if (active) {
            setIsRefreshing(false);
          }
        });
    }, 180);

    return () => {
      active = false;
      window.clearTimeout(timer);
    };
  }, [greenPreference, carbonPrice]);

  useEffect(() => {
    let active = true;

    async function refreshEngineeringSignals() {
      const [health, linkage, rl, sailing, registry, integration, audit, evidence] = await Promise.all([
        fetchJson('/api/health').catch(() => null),
        fetchJson('/api/linkage/health').catch(() => null),
        fetchJson('/api/rl/train/status').catch(() => null),
        fetchJson('/api/sailing/status').catch(() => null),
        fetchJson('/api/rl/registry').catch(() => null),
        fetchJson('/api/integration/status').catch(() => null),
        fetchJson('/api/audit/integrity').catch(() => null),
        fetchJson('/api/evidence/landing-benchmark').catch(() => null),
      ]);
      if (!active) return;
      setApiHealth({ health, linkage, rl, sailing, registry });
      if (rl) setRlStatus(rl);
      if (sailing) setSailingStatus(sailing);
      if (registry) setModelRegistry(registry);
      if (integration) setIntegrationStatus(integration);
      if (audit) setAuditStatus(audit);
      if (evidence) setLandingEvidence(evidence);
    }

    void refreshEngineeringSignals();
    const timer = window.setInterval(refreshEngineeringSignals, 7000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, []);

  useEffect(() => {
    if (!replayPlaying || (activePanel !== 'simulation' && activePanel !== 'shore') || replaySteps.length <= 1) {
      return undefined;
    }
    const timer = window.setInterval(() => {
      setReplayStep((current) => (current + 1) % replaySteps.length);
    }, 1700);
    return () => window.clearInterval(timer);
  }, [activePanel, replayPlaying, replaySteps.length]);

  useEffect(() => {
    if ((activePanel !== 'marl' && activePanel !== 'shore') || rlStatus?.status !== 'running') {
      return undefined;
    }
    const timer = window.setInterval(() => {
      void refreshRlStatus(true);
    }, 3000);
    return () => window.clearInterval(timer);
  }, [activePanel, rlStatus?.status]);

  async function syncDashboard(reason = '仪表盘已重新同步。') {
    setIsRefreshing(true);
    setPanelBusy(true);
    try {
      const nextSnapshot = await recomputeDashboard({
        green_preference: greenPreference,
        carbon_price_cny_per_ton: carbonPrice,
      });
      setSnapshot(nextSnapshot);
      setPanelNotice(reason);
    } catch (error) {
      setPanelNotice(`同步失败：${String(error)}`);
    } finally {
      setPanelBusy(false);
      setIsRefreshing(false);
    }
  }

  function openOperationalAction(actionId: string) {
    const definition = operationalDefinitions[actionId] ?? operationalDefinitions['twin-map'];
    setActivePanel(null);
    setActiveOperation(actionId in operationalDefinitions ? actionId : 'twin-map');
    setPanelNotice(`${definition.zh}已打开，等待确认运行离线分析。`);
    if (actionId.startsWith('recommendation-')) {
      void runDecisionImpact(operationalImpact(actionId, false), undefined, false);
    }
  }

  async function recomputeOperationalSnapshot(preference: number, reason: string) {
    setIsRefreshing(true);
    try {
      const nextSnapshot = await recomputeDashboard({
        green_preference: preference,
        carbon_price_cny_per_ton: carbonPrice,
      });
      setSnapshot(nextSnapshot);
      setPanelNotice(reason);
    } finally {
      setIsRefreshing(false);
    }
  }

  function commitOperationalState(actionId: string, definition: OperationalDefinition, notice: string) {
    setOperationalState((state) => {
      void actionId;
      void definition;
      return { ...state, latestEvent: notice };
    });
  }

  async function executeOperationalAction(actionId: string) {
    const definition = operationalDefinitions[actionId] ?? operationalDefinitions['twin-map'];
    const activeActionId = actionId in operationalDefinitions ? actionId : 'twin-map';
    const firstConnectedIndex = shoreWindowCards.findIndex((point) => point.shore_power_connected);
    let nextPreference = greenPreference;
    let notice = `${definition.zh}离线分析已完成。`;

    setOperationBusy(true);
    setActivePanel(null);
    try {
      switch (definition.mode) {
        case 'vessel':
          setReplayStep(activeActionId === 'berth-b03' ? 2 : 0);
          setReplayPlaying(true);
          notice = `${definition.zh}已定位，留出集轨迹回放已启用。`;
          await recomputeOperationalSnapshot(nextPreference, notice);
          break;
        case 'berth':
          setReplayStep(activeActionId === 'berth-b02' || activeActionId === 'recommendation-0' ? 1 : 0);
          setReplayPlaying(true);
          notice = `${definition.zh}已定位到现有测试轨迹；公开数据不含生产泊位计划，未改写业务状态。`;
          break;
        case 'crane':
          setReplayStep(2);
          setReplayPlaying(true);
          notice = `${definition.zh}已定位当前策略的岸桥投入；未伪造生产节拍。`;
          break;
        case 'yard':
          setReplayStep(3);
          notice = '当前公开数据集不含堆场占用快照，该模块已明确标记为未接入。';
          break;
        case 'agv':
          setReplayStep(4);
          setReplayPlaying(true);
          notice = '当前轨迹只包含场内车辆投入数，不包含车辆电量，因此未生成虚假充电指令。';
          break;
        case 'shore':
          nextPreference = 0.88;
          setGreenPreference(nextPreference);
          setReplayStep(firstConnectedIndex >= 0 ? firstConnectedIndex : 0);
          setReplayPlaying(true);
          notice = `${definition.zh}已作为奖励权重情景重算，结果仅写入离线快照。`;
          await recomputeOperationalSnapshot(nextPreference, notice);
          break;
        case 'peak':
          nextPreference = 0.64;
          setGreenPreference(nextPreference);
          setReplayPlaying(true);
          notice = `${definition.zh}已作为奖励权重情景重算，峰值约束由环境实际计算。`;
          await recomputeOperationalSnapshot(nextPreference, notice);
          break;
        case 'renewable':
          nextPreference = 0.82;
          setGreenPreference(nextPreference);
          setReplayPlaying(true);
          notice = '当前数据只有 eGRID 综合排放因子，没有分时能源结构，未生成虚假光伏/风电比例。';
          break;
        case 'traffic':
          setReplayPlaying(true);
          notice = '公开基准不包含外集卡到港明细，当前只展示环境输出的场内车辆动作。';
          break;
        case 'twin':
          setReplayStep(0);
          setReplayPlaying(true);
          notice = `${definition.zh}已刷新，离线测试轨迹从当前快照重载。`;
          await recomputeOperationalSnapshot(nextPreference, notice);
          break;
        case 'schedule':
          setReplayStep(0);
          setReplayPlaying(true);
          notice = `${definition.zh}已刷新，测试时间线已重新计算；未使用生产船期。`;
          await recomputeOperationalSnapshot(nextPreference, notice);
          break;
        case 'carbon':
          nextPreference = Math.max(nextPreference, 0.82);
          setGreenPreference(nextPreference);
          notice = `${definition.zh}已重算，碳排、配额与成本影响已同步。`;
          await recomputeOperationalSnapshot(nextPreference, notice);
          break;
        case 'comparison': {
          const data = await fetchJson('/api/rl/simulate', {
            method: 'POST',
            body: JSON.stringify({ strategy_id: 'auto:latest', source: 'operation_detail_comparison' }),
          });
          setPolicyTest(data);
          notice = `策略对比完成：减排 ${formatNumber(data.metrics?.carbon_reduction_pct, 1)}%，安全越界 ${data.metrics?.safety_violations ?? 0}。`;
          setPanelNotice(notice);
          break;
        }
        case 'health': {
          const [health, linkage, rl, sailing, registry, integration, audit] = await Promise.all([
            fetchJson('/api/health'),
            fetchJson('/api/linkage/health'),
            fetchJson('/api/rl/train/status'),
            fetchJson('/api/sailing/status'),
            fetchJson('/api/rl/registry'),
            fetchJson('/api/integration/status'),
            fetchJson('/api/audit/integrity'),
          ]);
          setApiHealth({ health, linkage, rl, sailing, registry });
          setRlStatus(rl);
          setSailingStatus(sailing);
          setModelRegistry(registry);
          setIntegrationStatus(integration);
          setAuditStatus(audit);
          notice = `告警与健康状态已刷新：${linkage.summary?.xiaoyi ?? '小懿待检查'} / ${linkage.summary?.rl ?? 'RL待检查'}。`;
          setPanelNotice(notice);
          break;
        }
        case 'refresh':
        default:
          notice = `${definition.zh}已刷新，当前驾驶舱快照已重新计算。`;
          await recomputeOperationalSnapshot(nextPreference, notice);
      }
      setOperationHistory((history) => ({
        ...history,
        [activeActionId]: new Date().toLocaleTimeString('zh-CN', { hour12: false }),
      }));
      setOperationResults((results) => ({ ...results, [activeActionId]: notice }));
      commitOperationalState(activeActionId, definition, notice);
    } catch (error) {
      setPanelNotice(`${definition.zh}执行失败：${String(error)}`);
      throw error;
    } finally {
      setOperationBusy(false);
    }
  }

  async function executeOperationalActionWithImpact(actionId: string) {
    await runDecisionImpact(operationalImpact(actionId, true), async () => {
      await executeOperationalAction(actionId);
      setActiveOperation(null);
    });
  }

  function operationalMetric(actionId: string) {
    if (['throughput'].includes(actionId)) return `${formatNumber(snapshot?.carbon_model.handled_teu, 0)} TEU`;
    const vesselContext = vesselOperationContexts.find((vessel) => vessel.id === actionId);
    if (vesselContext) return `${vesselContext.name} · ${vesselContext.berth} · ${vesselContext.status}`;
    if (['vessel-ops', 'vessel-queue', 'berth-b01'].includes(actionId)) return `${activeMarlPoint?.vessel_id ?? '待测试轨迹'} · ${activeMarlPoint?.berth_id ?? '--'}`;
    if (['berth-plan', 'berth-b02', 'recommendation-0'].includes(actionId)) return `${shoreConnectedCount}/${shoreWindowCards.length || 0} 个岸电窗口`;
    if (['crane-plan', 'berth-b03', 'recommendation-2'].includes(actionId)) return `${formatNumber(activeMarlPoint?.crane_count, 0)} 台活跃岸桥`;
    if (['yard-occupancy'].includes(actionId)) return `场内车辆动作 ${formatNumber(activeMarlPoint?.yard_truck_count, 0)}`;
    if (['agv-dispatch', 'recommendation-3'].includes(actionId)) return 'AGV 遥测未接入';
    if (['energy-load'].includes(actionId)) return `${formatNumber((activeMarlPoint?.load_kw ?? 0) / 1000, 2)} MW`;
    if (['renewable-mix', 'recommendation-5'].includes(actionId)) return '分时能源结构未接入';
    if (['carbon-market'].includes(actionId)) return `${formatNumber((marl?.total_carbon_kg ?? 0) / 1000, 1)} tCO2e`;
    if (['cost-analysis'].includes(actionId)) return `¥${formatNumber(marl?.total_cost_cny, 0)}`;
    if (['strategy-comparison'].includes(actionId)) return `减排 ${formatNumber(policyTest?.metrics?.carbon_reduction_pct, 1)}%`;
    if (['alerts'].includes(actionId)) return `${systemHealthyCount}/${topologyNodes.length} 个系统在线`;
    if (['recommendation-1', 'berth-b04'].includes(actionId)) return `${shoreConnectedCount} 个岸电窗口已接入`;
    if (['recommendation-4'].includes(actionId)) return `峰值 ${formatNumber(maxPeakLoadKw / 1000, 2)} MW`;
    if (['recommendation-6', 'timeline'].includes(actionId)) return `回放 STEP ${activeReplayIndex + 1}`;
    return `快照更新 ${new Date().toLocaleTimeString('zh-CN', { hour12: false })}`;
  }

  async function refreshSimulationReplay() {
    await runDecisionImpact(simulationImpact(), async () => {
      setActivePanel('simulation');
      setReplayStep(0);
      setReplayPlaying(true);
      await syncDashboard('仿真数据已刷新，回放时间轴已从 STEP 1 重新播放。');
    });
  }

  function inspectReplayStep(index: number) {
    const report = replayNodeImpact(index);
    void runDecisionImpact(report, () => {
      setReplayStep(index);
      setReplayPlaying(false);
    });
    const nodeRunToken = impactRunToken.current;
    window.setTimeout(() => {
      if (impactRunToken.current === nodeRunToken) {
        setReplayPlaying(true);
      }
    }, 2500 + (report.autoCloseMs ?? 0) + 120);
  }

  function toggleReplayWithImpact() {
    if (!replayPlaying) {
      setReplayPlaying(true);
      setPanelNotice('数字孪生回放已继续。');
      return;
    }
    const report = replayNodeImpact(activeReplayIndex);
    void runDecisionImpact({
      ...report,
      id: `replay-pause-${Date.now()}`,
      eyebrow: 'DIGITAL TWIN PAUSE AUDIT',
      title: `回放已冻结在 STEP ${activeMarlPoint?.step ?? activeReplayIndex + 1}`,
      subtitle: '当前窗口、策略动作与累计结果已锁定，便于值班人员复核；暂停回放不会触发新的生产动作。',
      objective: '冻结当前因果证据并保留人工复核窗口',
      actions: ['暂停数字孪生时间轴', '锁定当前船舶、泊位与策略原因', '保留累计曲线和 KPI 供人工复核'],
      recommendations: ['复核完成后关闭面板，再决定是否继续播放', '生产执行仍需单独的人工确认动作'],
      results: [
        { label: '回放状态', value: 'PAUSED', detail: `STEP ${activeMarlPoint?.step ?? activeReplayIndex + 1}`, tone: 'amber' },
        ...report.results.slice(0, 3),
      ],
    }, () => setReplayPlaying(false));
  }

  function inspectRecommendationTab(tab: 'recommended' | 'all') {
    void runDecisionImpact(recommendationTabImpact(tab));
  }

  async function openPanel(panel: TopPanelId) {
    setActivePanel(panel);
    setPanelNotice(`${panelMeta[panel].label} 面板已打开。`);
    if (panel === 'api') {
      await runApiCheck();
    }
    if (panel === 'marl') {
      await Promise.all([refreshRlStatus(), refreshLandingEvidence()]);
    }
    if (panel === 'simulation') {
      await refreshSailingStatus();
    }
  }

  async function refreshLandingEvidence() {
    try {
      const evidence = await fetchJson('/api/evidence/landing-benchmark');
      setLandingEvidence(evidence);
    } catch {
      setLandingEvidence(null);
    }
  }

  async function refreshRlStatus(silent = false) {
    if (!silent) {
      setPanelBusy(true);
    }
    try {
      const capabilitiesPromise = fetchJson('/api/rl/capabilities')
        .then((payload) => setRlCapabilities(payload))
        .catch(() => undefined);
      const data = await fetchJson('/api/rl/train/status');
      setRlStatus(data);
      await capabilitiesPromise;
      if (!silent) {
        setPanelNotice(`训练状态：${data.summary ?? data.status ?? '已刷新'}`);
      }
    } catch (error) {
      if (!silent) {
        setPanelNotice(`训练状态读取失败：${String(error)}`);
      }
    } finally {
      if (!silent) {
        setPanelBusy(false);
      }
    }
  }

  async function startMarlTraining() {
    setActivePanel('marl');
    setReplayPlaying(true);
    setPanelBusy(true);
    try {
      const objectiveId = greenPreference >= 0.7 ? 'carbon_min' : 'cost_carbon_balance';
      const algorithm = objectiveId === 'carbon_min' ? 'sac' : 'td3';
      const data = await fetchJson('/api/rl/train/start', {
        method: 'POST',
        body: JSON.stringify({
          confirm: true,
          source: 'topbar_rl_panel',
          config: {
            objective_id: objectiveId,
            objective_label: objectiveId === 'carbon_min' ? '碳排最低目标' : '成本与碳排均衡',
            algorithm,
            scenario: 'port_la_vessel_activity_benchmark',
            dataset_id: 'port_la_2020_2024_vessel_activity_hourly',
            total_steps: 100000,
            seed: 20260720,
          },
        }),
      });
      setRlStatus(data.result ?? data);
      setPanelNotice(`RL 训练已启动：${data.result?.config?.objective_label ?? data.result?.policy_version ?? 'policy pending'}`);
    } catch (error) {
      setPanelNotice(`RL 训练启动失败：${String(error)}`);
    } finally {
      setPanelBusy(false);
    }
  }

  async function controlMarlTraining(action: 'pause' | 'resume' | 'stop') {
    setActivePanel('marl');
    setPanelBusy(true);
    try {
      const data = await fetchJson(`/api/rl/train/${action}`, { method: 'POST' });
      setRlStatus(data.result ?? data);
      const actionLabel = action === 'pause' ? '已暂停' : action === 'resume' ? '已继续' : '已停止';
      setPanelNotice(`RL 训练${actionLabel}：${data.summary ?? data.status ?? '状态已更新'}`);
    } catch (error) {
      setPanelNotice(`训练控制失败：${String(error)}`);
    } finally {
      setPanelBusy(false);
    }
  }

  async function runPolicyTest() {
    setActivePanel('marl');
    setReplayPlaying(true);
    setPanelBusy(true);
    try {
      const data = await fetchJson('/api/rl/simulate', {
        method: 'POST',
        body: JSON.stringify({
          strategy_id: rlStatus?.job_id ?? 'auto:latest',
          source: 'topbar_marl_panel',
        }),
      });
      setPolicyTest(data);
      setPanelNotice(`策略测试完成：减排 ${formatNumber(data.metrics?.carbon_reduction_pct, 1)}%，安全越界 ${data.metrics?.safety_violations ?? 0}。`);
    } catch (error) {
      setPanelNotice(`策略测试失败：${String(error)}`);
    } finally {
      setPanelBusy(false);
    }
  }

  async function startShorePowerTraining() {
    setActivePanel('shore');
    setReplayPlaying(true);
    setPanelBusy(true);
    try {
      const data = await fetchJson('/api/rl/train/start', {
        method: 'POST',
        body: JSON.stringify({
          confirm: true,
          source: 'topbar_shore_panel',
          config: {
            objective_id: 'shore_power_priority',
            objective_label: '岸电优先目标',
            algorithm: 'sac',
            scenario: 'port_la_vessel_activity_benchmark',
            dataset_id: 'port_la_2020_2024_vessel_activity_hourly',
            total_steps: 100000,
            seed: 20260720,
            reward_weights: { shore_power: 0.44, carbon: 0.24, delay: 0.12, safety: 0.20, storage: 0.08 },
          },
        }),
      });
      setRlStatus(data.result ?? data);
      setPanelNotice(`岸电优先训练已启动：${data.result?.policy_version ?? 'policy pending'}`);
    } catch (error) {
      setPanelNotice(`岸电训练启动失败：${String(error)}`);
    } finally {
      setPanelBusy(false);
    }
  }

  function applyShorePowerPreference() {
    const firstConnectedIndex = shoreWindowCards.findIndex((point) => point.shore_power_connected);
    setGreenPreference(0.88);
    setActivePanel('shore');
    setReplayPlaying(true);
    setReplayStep(firstConnectedIndex >= 0 ? firstConnectedIndex : 0);
    setPanelNotice('岸电优先已应用，窗口调度面板正在跟随接入窗口播放。');
  }

  function applyDashboardPreference(value: number, label: string, panel: TopPanelId) {
    setGreenPreference(value);
    setActivePanel(panel);
    setReplayPlaying(true);
    setPanelNotice(`${label}已应用，驾驶舱正在按新调度偏好重算。`);
  }

  async function applyScenarioMode(mode: 'baseline' | 'optimized' | 'low-carbon') {
    const scenario = {
      baseline: { value: 0.25, label: '效率优先', panel: 'simulation' as const },
      optimized: { value: 0.5, label: '均衡调度', panel: 'marl' as const },
      'low-carbon': { value: 0.82, label: '低碳优先', panel: 'carbon' as const },
    }[mode];
    await runDecisionImpact(scenarioImpact(mode), async () => {
      applyDashboardPreference(scenario.value, scenario.label, scenario.panel);
      await recomputeOperationalSnapshot(scenario.value, `${scenario.label}已应用，驾驶舱快照已按新权重重算。`);
    });
  }

  async function refreshSailingStatus(reason?: string) {
    setPanelBusy(true);
    try {
      const data = await fetchJson('/api/sailing/status');
      setSailingStatus(data);
      setPanelNotice(data.process?.running ? `航行模拟器运行中：pid=${data.process.pid}` : reason ?? data.label ?? '航行模拟器状态已刷新。');
    } catch (error) {
      setPanelNotice(`航行模拟器状态读取失败：${String(error)}`);
    } finally {
      setPanelBusy(false);
    }
  }

  async function checkSimulatorForReplay() {
    setActivePanel('simulation');
    setReplayPlaying(true);
    await refreshSailingStatus('模拟器状态已刷新，仿真回放控制台保持在线。');
  }

  async function launchSailingSimulator() {
    setActivePanel('simulation');
    setReplayStep(0);
    setReplayPlaying(true);
    setPanelBusy(true);
    try {
      const data = await fetchJson('/api/sailing/launch', {
        method: 'POST',
        body: JSON.stringify({ confirm: true, preset: 'main_scene', source: 'topbar_simulation_panel' }),
      });
      setSailingStatus(data.status);
      setPanelNotice(`航行模拟器启动结果：${data.result?.status ?? 'done'}${data.result?.pid ? ` · pid=${data.result.pid}` : ''}`);
    } catch (error) {
      setPanelNotice(`航行模拟器启动失败：${String(error)}`);
    } finally {
      setPanelBusy(false);
    }
  }

  async function runApiCheck() {
    setPanelBusy(true);
    try {
      const [health, linkage, rl, sailing, registry, integration, audit] = await Promise.all([
        fetchJson('/api/health'),
        fetchJson('/api/linkage/health'),
        fetchJson('/api/rl/train/status'),
        fetchJson('/api/sailing/status'),
        fetchJson('/api/rl/registry'),
        fetchJson('/api/integration/status'),
        fetchJson('/api/audit/integrity'),
      ]);
      setApiHealth({ health, linkage, rl, sailing, registry });
      setRlStatus(rl);
      setSailingStatus(sailing);
      setModelRegistry(registry);
      setIntegrationStatus(integration);
      setAuditStatus(audit);
      setPanelNotice(`API健康检查完成：${linkage.summary?.xiaoyi ?? '小懿待检查'} / ${linkage.summary?.rl ?? 'RL待检查'} / ${linkage.summary?.sailing ?? '航行模拟器待检查'}`);
    } catch (error) {
      setPanelNotice(`API健康检查失败：${String(error)}`);
    } finally {
      setPanelBusy(false);
    }
  }

  const selectedOperationalDefinition = activeOperation
    ? operationalDefinitions[activeOperation] ?? operationalDefinitions['twin-map']
    : null;
  const selectedOperationalModel = selectedOperationalDefinition
    ? ['shore', 'carbon', 'renewable', 'peak'].includes(selectedOperationalDefinition.mode)
      ? `${currentRlAlgorithm} · Continuous RL`
      : ['berth', 'crane', 'yard', 'agv', 'traffic'].includes(selectedOperationalDefinition.mode)
        ? 'RL Policy · PortEnergyDispatchEnv'
        : '约束规则引擎 · Offline Snapshot'
    : '';
  const selectedOperationalBehavior = selectedOperationalDefinition
    ? selectedOperationalDefinition.mode === 'shore'
      ? '切换岸电优先奖励权重，在留出集上重新计算轨迹并回写能碳 KPI。'
      : selectedOperationalDefinition.descriptionZh
    : '';
  const selectedOperationalRisk = selectedOperationalDefinition?.mode === 'shore'
    ? '变电站峰值、船舶接口兼容与泊位互斥；任一硬约束失败则拒绝下发。'
    : '生产船期、设备可用性与告警尚未接入，不能据此直接下发。';
  const selectedOperationalAdvice = selectedOperationalDefinition?.mode === 'shore'
    ? '执行后同时复核总碳排、峰值容量、岸电兼容和综合成本。'
    : '执行后通过数字孪生节点与 KPI 回写复核真实影响。';

  return (
    <main className="port-command-shell">
      <PortCommandCenter
        snapshot={snapshot}
        rlStatus={rlStatus}
        integrationStatus={integrationStatus}
        auditIntegrityOk={auditStatus?.ok ?? null}
        greenPreference={greenPreference}
        carbonPrice={carbonPrice}
        replayPlaying={replayPlaying}
        activePoint={activeMarlPoint}
        operationState={operationalState}
        onlineSystemCount={systemHealthyCount}
        totalSystemCount={topologyNodes.length}
        onOpenPanel={openPanel}
        onToggleReplay={toggleReplayWithImpact}
        onRefreshSimulation={refreshSimulationReplay}
        onStartTraining={startMarlTraining}
        onControlTraining={controlMarlTraining}
        onOpenXiaoyi={() => setXiaoyiOpenToken((token) => token + 1)}
        onCheckSimulator={checkSimulatorForReplay}
        onLaunchSimulator={launchSailingSimulator}
        onOpenAction={openOperationalAction}
        onChangeRecommendationTab={inspectRecommendationTab}
        onSetScenarioMode={applyScenarioMode}
      />
      {activeOperation && selectedOperationalDefinition && (
        <section className="operation-detail-panel" aria-label={`${selectedOperationalDefinition.zh}操作详情`}>
          <div className="operation-detail-head">
            <div>
              <p><span>业务动作</span><small>OPERATION ACTION</small></p>
              <h2><span>{selectedOperationalDefinition.zh}</span><small>{selectedOperationalDefinition.en}</small></h2>
            </div>
            <button className="icon-btn" type="button" onClick={() => { setActiveOperation(null); setDecisionImpact(null); }} aria-label="关闭业务动作详情">
              <X size={18} />
            </button>
          </div>
          <p className="operation-detail-copy"><span>{selectedOperationalDefinition.descriptionZh}</span><small>{selectedOperationalDefinition.descriptionEn}</small></p>
          <div className="operation-detail-grid">
            <span><small>作用范围 / Scope</small><b>{selectedOperationalDefinition.scopeZh}<em>{selectedOperationalDefinition.scopeEn}</em></b></span>
            <span><small>轨迹指标 / Trajectory metric</small><b>{operationalMetric(activeOperation)}</b></span>
            <span><small>执行状态 / Execution</small><b className={operationHistory[activeOperation] ? 'applied' : ''}>{operationHistory[activeOperation] ? '已应用' : '待确认'}<em>{operationHistory[activeOperation] ? `Applied · ${operationHistory[activeOperation]}` : 'Ready for confirmation'}</em></b></span>
            <span><small>数据来源 / Data source</small><b>公开基准测试分区<em>Offline test snapshot</em></b></span>
          </div>
          <div className="operation-decision-grid">
            <span><small>模型 / Decision engine</small><b>{selectedOperationalModel}</b></span>
            <span><small>执行行为 / Action</small><b>{selectedOperationalBehavior}</b></span>
            <span className="risk"><small>风险护栏 / Risk guard</small><b>{selectedOperationalRisk}</b></span>
            <span className="advice"><small>值班建议 / Advice</small><b>{selectedOperationalAdvice}</b></span>
          </div>
          <div className="operation-detail-actions">
            <button className="operation-primary" type="button" disabled={operationBusy} onClick={() => void executeOperationalActionWithImpact(activeOperation)}>
              {operationBusy ? <RefreshCw size={15} /> : <Zap size={15} />}{operationBusy ? '执行中 / Running' : <><span>{selectedOperationalDefinition.primaryZh}</span><small>{selectedOperationalDefinition.primaryEn}</small></>}
            </button>
            <button className="operation-secondary" type="button" onClick={() => setActiveOperation(null)}>暂不执行 / Close</button>
          </div>
          {operationResults[activeOperation] && <div className="operation-detail-result"><CheckCircle2 size={14} /><span>{operationResults[activeOperation]}</span><small>Action result has been synchronized with the offline test snapshot.</small></div>}
          <div className="operation-detail-note"><CheckCircle2 size={14} />执行会更新对应的驾驶舱状态与后端重算快照，不会跳转到无关模块。<small>The action updates the matching cockpit state and backend snapshot only.</small></div>
        </section>
      )}
      {activePanel && (
        <section className="top-action-panel" aria-label={`${panelMeta[activePanel].label}功能面板`}>
          <div className="top-action-head">
            <div>
              <p><span>{panelMeta[activePanel].label}</span><small>{panelMeta[activePanel].en}</small></p>
              <h2><span>{panelHeading[activePanel].zh}</span><small>{panelHeading[activePanel].en}</small></h2>
            </div>
            <button className="icon-btn" type="button" onClick={() => { setActivePanel(null); setDecisionImpact(null); }} aria-label="关闭顶部功能面板">
              <X size={18} />
            </button>
          </div>

          <div className="top-action-content">
            {activePanel === 'simulation' && (
              <>
                <div className="action-stat-grid">
                  <span>场景 <b>{snapshot?.scenario_id ?? 'port_la_2025_public_benchmark'}</b></span>
                  <span>时序点 <b>{snapshot?.timeseries.length ?? 0}</b></span>
                  <span>Gymnasium <b>{snapshot?.rl_environment.status ?? '--'}</b></span>
                  <span>模拟器 <b>{sailingStatus?.process?.running ? `运行中 pid=${sailingStatus.process.pid}` : sailingStatus?.label ?? '待检查'}</b></span>
                </div>
                <div className="action-command-row">
                  <button type="button" onClick={toggleReplayWithImpact}>
                    {replayPlaying ? <Pause size={14} /> : <Play size={14} />}{replayPlaying ? '暂停窗口' : '播放窗口'}
                  </button>
                  <button type="button" onClick={refreshSimulationReplay}><RefreshCw size={14} />刷新仿真</button>
                  <button type="button" onClick={checkSimulatorForReplay}><Radio size={14} />检查模拟器</button>
                  <button type="button" onClick={launchSailingSimulator}><Play size={14} />启动模拟器</button>
                </div>
                <div className="simulation-console">
                  <div className="route-replay-map">
                    <span className="route-replay-line" />
                    <span className="route-replay-progress" style={{ width: `${replayProgress}%` }} />
                    {replaySteps.map((step, index) => (
                      <button
                        className={`route-replay-node ${index === activeReplayIndex ? 'active' : ''} ${index < activeReplayIndex ? 'past' : ''}`}
                        key={`${step.marl.step}-${step.marl.berth_id}`}
                        type="button"
                        style={{ left: `${replaySteps.length > 1 ? (index / (replaySteps.length - 1)) * 100 : 0}%` }}
                        onClick={() => inspectReplayStep(index)}
                        title={`${step.marl.time} ${step.marl.vessel_id}`}
                      >
                        {step.marl.berth_id}
                      </button>
                    ))}
                    <span className="route-vessel-marker" style={{ left: `${replayProgress}%` }}><ShipWheel size={13} /></span>
                  </div>
                  <div className="event-inspector">
                    <div>
                      <small>当前回放 STEP {activeMarlPoint?.step ?? '--'}</small>
                      <h3>{activeMarlPoint ? `${activeMarlPoint.time} · ${eventLabel(activeMarlPoint.event)}` : '等待仿真数据'}</h3>
                      <p>{activeMarlPoint?.decision_reason ?? '刷新仿真后展示测试集策略轨迹和奖励依据。'}</p>
                    </div>
                    <div className="event-metric-grid">
                      <span>船舶 <b>{activeMarlPoint?.vessel_id ?? '--'}</b></span>
                      <span>泊位 <b>{activeMarlPoint?.berth_id ?? '--'}</b></span>
                      <span>单步减排 <b>{formatNumber(carbonStepSaving, 0)} kg</b></span>
                      <span>延误压缩 <b>{formatNumber(delayStepSaving, 1)} min</b></span>
                    </div>
                  </div>
                  <div className="simulation-live-grid">
                    <div className="carbon-follow-card">
                      <div className="training-console-head">
                        <span>碳排曲线跟随播放</span>
                        <b>STEP {activeMarlPoint?.step ?? '--'} / {replaySteps.length || '--'}</b>
                      </div>
                      <svg className="carbon-follow-chart" viewBox="0 0 460 112" role="img" aria-label="累计碳排放跟随回放曲线">
                        <line x1="0" y1="106" x2="460" y2="106" />
                        <polyline className="traditional-carbon-line" points={traditionalCarbonSeries.map((point) => `${point.x},${point.y}`).join(' ')} />
                        <polyline className="marl-carbon-line" points={marlCarbonSeries.map((point) => `${point.x},${point.y}`).join(' ')} />
                        {activeTraditionalCarbonPoint && <circle className="traditional-carbon-dot" cx={activeTraditionalCarbonPoint.x} cy={activeTraditionalCarbonPoint.y} r="4" />}
                        {activeMarlCarbonPoint && <circle className="marl-carbon-dot" cx={activeMarlCarbonPoint.x} cy={activeMarlCarbonPoint.y} r="5" />}
                      </svg>
                      <div className="carbon-follow-legend">
                        <span><i className="traditional" />Traditional {formatNumber(activeTraditionalCumulativeCarbon / 1000, 2)} t</span>
                        <span><i className="marl" />优化策略 {formatNumber(activeMarlCumulativeCarbon / 1000, 2)} t</span>
                        <span>累计少排 <b>{formatNumber(activeCumulativeSaving / 1000, 2)} t</b></span>
                      </div>
                    </div>
                    <div className="sim-process-card">
                      <div className="training-console-head">
                        <span>模拟器进程状态</span>
                        <b>{sailingStatus?.process?.running ? 'RUNNING' : sailingStatus?.launchable ? 'READY' : 'WAITING'}</b>
                      </div>
                      <div className="sim-process-grid">
                        <span>进程 <b>{sailingStatus?.process?.running ? `pid=${sailingStatus.process.pid}` : '未运行'}</b></span>
                        <span>Godot <b>{sailingStatus?.godot_executable?.exists ? '可用' : '待检查'}</b></span>
                        <span>项目 <b>{sailingStatus?.project_root?.exists ? '已找到' : '待检查'}</b></span>
                        <span>预设 <b>{sailingStatus?.last_launch?.preset ?? 'main_scene'}</b></span>
                      </div>
                      <p>{sailingStatus?.process?.running ? '航行模拟器已由驾驶舱拉起，回放控制台继续展示调度过程。' : '点击“启动模拟器”后，这里会同步显示进程与预设状态。'}</p>
                    </div>
                  </div>
                  <div className="step-compare-board">
                    <article>
                      <span>Traditional 当前步</span>
                      <b>{activeTraditionalPoint ? `${activeTraditionalPoint.time} · ${activeTraditionalPoint.berth_id}` : '--'}</b>
                      <small>{activeTraditionalPoint?.decision_reason ?? '等待传统调度事件。'}</small>
                    </article>
                    <article className="marl">
                      <span>优化策略当前步</span>
                      <b>{activeMarlPoint ? `${activeMarlPoint.time} · ${activeMarlPoint.berth_id}` : '--'}</b>
                      <small>{activeMarlPoint?.decision_reason ?? '等待优化策略轨迹。'}</small>
                    </article>
                  </div>
                </div>
              </>
            )}

            {activePanel === 'marl' && (
              <>
                <div className="action-stat-grid">
                  <span>当前策略 <b>{rlStatus?.policy_version ?? policyTest?.policy?.policy_version ?? 'auto:latest'}</b></span>
                  <span>训练状态 <b>{rlStatus?.status ?? snapshot?.rl_environment.status ?? '--'}</b></span>
                  <span>注册阶段 <b>{latestRegisteredPolicy?.stage ?? '未注册'}</b></span>
                  <span>生产资格 <b>{latestRegisteredPolicy?.production_eligible ? '允许' : '禁止'}</b></span>
                </div>
                <section className="landing-evidence-board" aria-label="v4 因果落地评测证据">
                  <header>
                    <div>
                      <span>V4 因果落地评测 · 新增业务证据</span>
                      <small>CAUSAL OFFLINE ROBUSTNESS · NOT A FIELD KPI</small>
                    </div>
                    <b>{landingEvidence?.status ? 'REPRODUCIBLE' : 'LOADING'}</b>
                  </header>
                  <div className="landing-evidence-protocol">
                    <span>测试协议 <b>{landingProtocol?.windows ?? '--'} 窗口 × {landingProtocol?.episode_hours ?? '--'}h</b></span>
                    <span>因果步数 <b>{landingProtocol?.steps?.toLocaleString?.() ?? '--'}</b></span>
                    <span>MPC 深度 <b>H{landingProtocol?.policy?.horizon ?? '--'} · Beam {landingProtocol?.policy?.beam_width ?? '--'} · {landingProtocol?.policy?.candidate_actions ?? '--'} 动作</b></span>
                    <span>数据密度 <b>{landingDataset?.row_volume?.toLocaleString?.() ?? '--'} 行 / {landingDataset?.independent_operational_anchors?.toLocaleString?.() ?? '--'} 官方锚点</b></span>
                  </div>
                  <div className="landing-business-grid">
                    <article>
                      <small>能耗下降 · 对固定全资源</small>
                      <b>{formatNumber(landingBusiness?.energy_reduction_pct, 2)}%</b>
                      <span>公开数据留出集</span>
                    </article>
                    <article>
                      <small>碳排下降 · 95% CI</small>
                      <b>{formatNumber(landingBusiness?.carbon_reduction_pct, 2)}%</b>
                      <span>{formatNumber(landingBusiness?.carbon_reduction_ci95?.ci95_low_pct, 2)}–{formatNumber(landingBusiness?.carbon_reduction_ci95?.ci95_high_pct, 2)}%</span>
                    </article>
                    <article>
                      <small>成本下降 · 95% CI</small>
                      <b>{formatNumber(landingBusiness?.cost_reduction_pct, 2)}%</b>
                      <span>{formatNumber(landingBusiness?.cost_reduction_ci95?.ci95_low_pct, 2)}–{formatNumber(landingBusiness?.cost_reduction_ci95?.ci95_high_pct, 2)}%</span>
                    </article>
                    <article>
                      <small>峰值下降 / 吞吐保留</small>
                      <b>{formatNumber(landingBusiness?.peak_reduction_pct, 2)}%</b>
                      <span>{formatNumber(100 + Number(landingBusiness?.throughput_change_pct ?? 0), 4)}% throughput</span>
                    </article>
                  </div>
                  <div className="landing-increment-grid">
                    <div className="landing-increment-positive">
                      <strong>相对因果旧 MPC 的算法增量</strong>
                      <span>延误下降 <b>{formatNumber(algorithmIncrement?.delay_reduction_pct, 2)}%</b></span>
                      <span>P95 队列下降 <b>{formatNumber(algorithmIncrement?.p95_queue_reduction_pct, 2)}%</b></span>
                      <span>动作抖动下降 <b>{formatNumber(algorithmIncrement?.action_variation_reduction_pct, 2)}%</b></span>
                      <span>硬约束成功 <b>{formatNumber(algorithmIncrement?.constraint_success_rate_pct, 1)}%</b></span>
                    </div>
                    <div className="landing-increment-tradeoff">
                      <strong>公开代价 · 不隐藏负结果</strong>
                      <span>碳排增加 <b>{formatNumber(Math.abs(Number(algorithmIncrement?.carbon_reduction_pct ?? 0)), 4)}%</b></span>
                      <span>成本增加 <b>{formatNumber(Math.abs(Number(algorithmIncrement?.cost_reduction_pct ?? 0)), 4)}%</b></span>
                      <span>峰值增加 <b>{formatNumber(Math.abs(Number(algorithmIncrement?.peak_reduction_pct ?? 0)), 4)}%</b></span>
                      <span>实港等级 <b>{landingDataset?.landing_grade ?? '--'} · 生产禁用</b></span>
                    </div>
                  </div>
                  <div className="landing-stress-strip">
                    {stressEntries.map(([stressId, stress]) => (
                      <span key={stressId}>
                        <small>{stressId.replace(/_/g, ' ')}</small>
                        <b>{formatNumber(stress.risk_aware_zero_violation_rate_pct, 0)}% 零硬越界</b>
                        <em>{stressId === 'grid_derating_10pct' ? '软储备缺口 +7.692%' : '代价已公开'}</em>
                      </span>
                    ))}
                  </div>
                  <footer>
                    <span>证据哈希 <b>{landingEvidence?.evidence_sha256?.slice(0, 16) ?? '--'}…</b></span>
                    <span>数据展开比 <b>{formatNumber(landingDataset?.modeled_rows_per_operational_anchor, 3)} 行/锚点</b></span>
                    <span>边界 <b>公开数据离线回放，不是港口现场 KPI</b></span>
                  </footer>
                </section>
                <section className="algorithm-matrix-board" aria-label="五算法训练矩阵">
                  <header>
                    <div>
                      <span>训练中心 · 五算法矩阵</span>
                      <small>4 RL ALGORITHMS + 1 CONTROL BASELINE</small>
                    </div>
                    <b>{rlCapabilities?.runtime?.available ? `SB3 ${rlCapabilities.runtime.stable_baselines3 ?? 'ready'}` : '运行时核验中'}</b>
                  </header>
                  <div>
                    {algorithmMatrix.map((algorithm) => (
                      <article className={algorithm.family === 'control_theory' ? 'control' : ''} key={algorithm.id}>
                        <span>{algorithm.family === 'control_theory' ? '控制基线' : '强化学习'}</span>
                        <b>{algorithm.name}</b>
                        <small>{algorithm.action_space}</small>
                        <em>{algorithm.defaults?.total_steps ? `${Number(algorithm.defaults.total_steps).toLocaleString()} default steps` : 'rolling optimization'}</em>
                      </article>
                    ))}
                  </div>
                  <footer>
                    <span>训练数据 <b>{rlStatus?.config?.dataset_id ?? 'port_la_2020_2024_vessel_activity_hourly'}</b></span>
                    <span>观测 <b>{rlStatus?.config?.observation_count ?? 25} 维</b></span>
                    <span>动作 <b>连续 4 / DQN 81</b></span>
                    <span>训练渲染 <b>OFF</b></span>
                    <span>测试回放 <b>HELD-OUT ONLY</b></span>
                  </footer>
                </section>
                <div className="training-monitor-grid">
                  <div className="training-console">
                    <div className="training-console-head">
                      <span>训练监控</span>
                      <b>{formatNumber(trainingProgress, 1)}%</b>
                    </div>
                    <div className="training-meter"><div style={{ width: `${trainingProgress}%` }} /></div>
                    <div className="event-metric-grid">
                      <span>目标 <b>{rlStatus?.config?.objective_label ?? '能碳均衡目标'}</b></span>
                      <span>算法 <b>{String(rlStatus?.config?.algorithm ?? 'SAC').toUpperCase()}</b></span>
                      <span>Step <b>{rlStatus?.step ?? snapshot?.rl_environment.episode_steps ?? 0}</b></span>
                      <span>Entropy <b>{rlStatus?.entropy ?? '--'}</b></span>
                    </div>
                    <div className="reward-bar-board">
                      {rewardBars.map((point, index) => {
                        const height = 28 + ((point.reward - rewardMin) / rewardRange) * 52;
                        return (
                          <span
                            className={index === activeReplayIndex ? 'active' : ''}
                            key={`${point.step}-${index}`}
                            style={{ height: `${height}px` }}
                            title={`step ${point.step}: reward ${formatNumber(point.reward, 2)}`}
                          >
                            <i>{formatNumber(point.reward, 1)}</i>
                          </span>
                        );
                      })}
                    </div>
                    <div className="reward-term-strip">
                      <span>碳惩罚 <b>{formatNumber(activeReward?.carbon_penalty, 2)}</b></span>
                      <span>延误惩罚 <b>{formatNumber(activeReward?.delay_penalty, 2)}</b></span>
                      <span>能耗惩罚 <b>{formatNumber(activeReward?.energy_penalty, 2)}</b></span>
                      <span>岸电奖励 <b>{formatNumber(activeReward?.shore_power_bonus, 2)}</b></span>
                    </div>
                  </div>
                  <div className="policy-test-console">
                    <div className="training-console-head">
                      <span>训练后策略测试</span>
                      <b>{policyTest?.status ?? '待测试'}</b>
                    </div>
                    <div className="policy-score-grid">
                      <span>减排 <b>{policyMetrics ? `${formatNumber(policyMetrics.carbon_reduction_pct, 1)}%` : '--'}</b></span>
                      <span>岸电提升 <b>{policyMetrics ? `${formatNumber(policyMetrics.shore_power_gain_pct, 1)}%` : '--'}</b></span>
                      <span>成本节省 <b>{policyMetrics ? `${formatNumber(policyMetrics.cost_saving_pct, 1)}%` : '--'}</b></span>
                      <span>安全越界 <b>{policyMetrics?.safety_violations ?? 0}</b></span>
                      <span>制品完整性 <b>{latestRegisteredPolicy?.artifact_integrity ?? '--'}</b></span>
                      <span>数据一致性 <b>{latestRegisteredPolicy?.dataset_status ?? '--'}</b></span>
                      <span>数据偏移 <b>{latestRegisteredPolicy?.drift?.status ?? '--'}</b></span>
                      <span>制品哈希 <b>{latestRegisteredPolicy?.artifact_sha256?.slice(0, 12) ?? '--'}</b></span>
                    </div>
                    <p className="policy-summary">{policyTest?.summary ?? '运行策略测试后，这里会显示减排、岸电、成本和安全护栏的综合结果。'}</p>
                    <div className="training-log-feed">
                      {(rlLogs.length ? rlLogs : ['等待训练任务。', '点击启动训练后自动轮询进度。']).map((line) => (
                        <span key={line}>{line}</span>
                      ))}
                    </div>
                  </div>
                </div>
                <div className="action-command-row">
                  <button type="button" onClick={startMarlTraining}><Play size={14} />启动训练</button>
                  <button
                    type="button"
                    disabled={panelBusy || (!trainingCanPause && !trainingCanResume)}
                    onClick={() => controlMarlTraining(trainingCanResume ? 'resume' : 'pause')}
                  >
                    {trainingCanResume ? <Play size={14} /> : <Pause size={14} />}
                    {trainingCanResume ? '继续训练' : '暂停训练'}
                  </button>
                  <button
                    className="danger-action"
                    type="button"
                    disabled={panelBusy || !trainingCanStop}
                    onClick={() => controlMarlTraining('stop')}
                  ><Square size={14} />停止训练</button>
                  <button type="button" onClick={() => refreshRlStatus()}><Radio size={14} />查看训练状态</button>
                  <button type="button" onClick={runPolicyTest}><Gauge size={14} />运行策略测试</button>
                </div>
              </>
            )}

            {activePanel === 'carbon' && (
              <>
                <div className="action-stat-grid">
                  <span>范围一·辅机燃油 <b>{formatNumber((snapshot?.carbon_model.scope1_auxiliary_fuel_kg ?? 0) / 1000, 2)} t</b></span>
                  <span>范围二·所在地法 <b>{formatNumber((snapshot?.carbon_model.scope2_location_based_kg ?? 0) / 1000, 2)} t</b></span>
                  <span>范围二·市场法 <b>{snapshot?.carbon_model.scope2_market_based_kg == null ? '未接入' : `${formatNumber(snapshot.carbon_model.scope2_market_based_kg / 1000, 2)} t`}</b></span>
                  <span>核算保证 <b>{snapshot?.carbon_model.assurance_status ?? '待检查'}</b></span>
                </div>
                <input
                  className="top-panel-slider"
                  type="range"
                  min="0"
                  max="1"
                  step="0.01"
                  value={greenPreference}
                  onChange={(event) => setGreenPreference(Number(event.target.value))}
                />
                <div className="carbon-impact-console">
                  <div className="carbon-mode-card">
                    <span>当前调度模式</span>
                    <h3>{activePreference}</h3>
                    <p>{carbonMarket?.optimization_advice ?? '等待优化结果同步后展示配额、成本和调度建议。'}</p>
                    <div className="carbon-mode-meter">
                      <i style={{ width: `${clampPercent(greenPreference * 100)}%` }} />
                    </div>
                  </div>
                  <div className="carbon-impact-grid">
                    <span>基线等额配额情景 <b>{formatNumber(carbonMarket?.quota_utilization_rate, 1)}%</b></span>
                    <span>配额缺口 <b>{formatNumber(carbonMarket?.quota_gap_ton, 2)} t</b></span>
                    <span>减排价值 <b>{formatNumber((carbonMarket?.abatement_value_cny ?? 0) / 10000, 2)} 万</b></span>
                    <span>碳成本节省 <b>{formatNumber((carbonMarket?.carbon_cost_saving_cny ?? 0) / 10000, 2)} 万</b></span>
                    <span>数据质量 <b>{snapshot?.data_quality.score ?? 0}/100 · {snapshot?.data_quality.grade ?? '--'}</b></span>
                    <span>落地数据等级 <b>{snapshot?.data_quality.landing_readiness?.landing_grade ?? '--'} · {snapshot?.data_quality.landing_readiness?.production_training_ready ? '可训练' : '未就绪'}</b></span>
                    <span>分布偏移 <b>{snapshot?.data_drift.status ?? '待检查'}</b></span>
                    <span>核算方法 <b>{snapshot?.carbon_model.scope2_method ?? '--'}</b></span>
                    <span>生产执行 <b>{snapshot?.governance.production_dispatch_enabled ? '已启用' : '已禁用'}</b></span>
                  </div>
                  <div className="carbon-source-board">
                    {carbonSourceEntries.map(([source, value]) => (
                      <span key={source}>
                        <small>{source}</small>
                        <b>{formatNumber(value / 1000, 2)} t</b>
                        <i style={{ width: `${clampPercent((value / maxCarbonSource) * 100)}%` }} />
                      </span>
                    ))}
                  </div>
                </div>
                <div className="action-command-row">
                  <button type="button" onClick={() => setGreenPreference(0.25)}>效率优先</button>
                  <button type="button" onClick={() => setGreenPreference(0.5)}>均衡调度</button>
                  <button type="button" onClick={() => setGreenPreference(0.82)}>低碳优先</button>
                </div>
              </>
            )}

            {activePanel === 'shore' && (
              <>
                <div className="action-stat-grid">
                  <span>岸电使用率 <b>{formatNumber(marl?.shore_power_usage_rate, 1)}%</b></span>
                  <span>提升 <b>{formatNumber(shorePowerGain, 1)} 个百分点</b></span>
                  <span>替代减排 <b>{formatNumber((snapshot?.carbon_model.shore_power_reduction_kg ?? 0) / 1000, 2)} t</b></span>
                  <span>联动窗口 <b>{shoreConnectedCount} / {shoreWindowCards.length || 0} 个</b></span>
                </div>
                <div className="shore-dispatch-board">
                  {shoreWindowCards.map((point, index) => (
                    <button
                      className={`shore-window-card ${point.shore_power_connected ? 'connected' : 'standby'} ${index === activeReplayIndex ? 'active' : ''}`}
                      key={`${point.step}-${point.time}-${point.berth_id}`}
                      type="button"
                      onClick={() => inspectReplayStep(index)}
                    >
                      <span>{point.time} · {point.berth_id}</span>
                      <b>{point.vessel_id}</b>
                      <em>{point.shore_power_connected ? '岸电接入' : '燃油待机'}</em>
                      <small>{point.reason}</small>
                      <i style={{ width: `${clampPercent((point.peakLoadKw / maxPeakLoadKw) * 100)}%` }} />
                    </button>
                  ))}
                </div>
                <div className="shore-window-console">
                  <div className="shore-window-main">
                    <span className={activeMarlPoint?.shore_power_connected ? 'plug-state connected' : 'plug-state'}>
                      {activeMarlPoint?.shore_power_connected ? 'CONNECTED' : 'STANDBY'}
                    </span>
                    <h3>{activeMarlPoint ? `${activeMarlPoint.time} · ${activeMarlPoint.vessel_id}` : '等待岸电窗口'}</h3>
                    <p>{activeMarlPoint?.decision_reason ?? '岸电联动窗口会跟随仿真回放高亮当前泊位和接入理由。'}</p>
                    <div className="event-metric-grid">
                      <span>岸桥 <b>{activeMarlPoint?.crane_count ?? '--'}</b></span>
                      <span>集卡 <b>{activeMarlPoint?.yard_truck_count ?? '--'}</b></span>
                      <span>本步能耗 <b>{formatNumber(activeMarlPoint?.energy_kwh, 0)} kWh</b></span>
                      <span>本步碳排 <b>{formatNumber(activeMarlPoint?.carbon_kg, 0)} kg</b></span>
                      <span>替代减排 <b>{formatNumber(activeShoreWindow?.reductionKg, 0)} kg</b></span>
                      <span>峰值负荷 <b>{formatNumber(activeShoreWindow?.peakLoadKw, 0)} kW</b></span>
                    </div>
                  </div>
                  <div className="shore-weight-board">
                    {Object.entries(rewardWeights).length ? Object.entries(rewardWeights).map(([key, value]) => (
                      <span key={key}>
                        <small>{key}</small>
                        <b>{formatNumber(value * 100, 0)}%</b>
                        <i style={{ width: `${clampPercent(value * 100)}%` }} />
                      </span>
                    )) : (
                      <>
                        <span><small>shore_power</small><b>44%</b><i style={{ width: '44%' }} /></span>
                        <span><small>carbon</small><b>24%</b><i style={{ width: '24%' }} /></span>
                        <span><small>delay</small><b>12%</b><i style={{ width: '12%' }} /></span>
                        <span><small>safety</small><b>20%</b><i style={{ width: '20%' }} /></span>
                      </>
                    )}
                  </div>
                </div>
                <div className="shore-ops-grid">
                  <div className="shore-safety-panel">
                    <div className="training-console-head">
                      <span>安全约束</span>
                      <b>{shoreSafetyConstraints.every((item) => item.ok) ? 'PASS' : 'REVIEW'}</b>
                    </div>
                    {shoreSafetyConstraints.map((item) => (
                      <span className={item.ok ? 'ok' : 'warn'} key={item.label}>
                        {item.ok ? <CheckCircle2 size={13} /> : <CircleAlert size={13} />}
                        <small>{item.label}</small>
                        <b>{item.value}</b>
                      </span>
                    ))}
                  </div>
                  <div className="shore-training-delta">
                    <div className="training-console-head">
                      <span>训练后接入率变化</span>
                      <b>{shoreTrainingActive ? `${formatNumber(trainingProgress, 1)}%` : '待训练'}</b>
                    </div>
                    <div className="shore-rate-ladder">
                      <span>
                        <small>传统调度</small>
                        <b>{formatNumber(traditional?.shore_power_usage_rate, 1)}%</b>
                        <i style={{ width: `${clampPercent(traditional?.shore_power_usage_rate ?? 0)}%` }} />
                      </span>
                      <span>
                        <small>当前优化策略</small>
                        <b>{formatNumber(marl?.shore_power_usage_rate, 1)}%</b>
                        <i style={{ width: `${clampPercent(marl?.shore_power_usage_rate ?? 0)}%` }} />
                      </span>
                      <span>
                        <small>岸电训练后</small>
                        <b>{formatNumber(projectedShoreRate, 1)}%</b>
                        <i style={{ width: `${clampPercent(projectedShoreRate)}%` }} />
                      </span>
                    </div>
                    <p>相对传统调度提升 {formatNumber(projectedShoreLift, 1)} 个百分点，训练目标将更多奖励岸电窗口匹配、峰值负荷平滑和安全护栏。</p>
                  </div>
                </div>
                <div className="action-command-row">
                  <button type="button" onClick={toggleReplayWithImpact}>
                    {replayPlaying ? <Pause size={14} /> : <Play size={14} />}{replayPlaying ? '暂停窗口' : '播放窗口'}
                  </button>
                  <button type="button" onClick={applyShorePowerPreference}><Zap size={14} />切到岸电优先</button>
                  <button type="button" onClick={startShorePowerTraining}><Play size={14} />训练岸电策略</button>
                </div>
              </>
            )}

            {activePanel === 'api' && (
              <>
                <div className="action-stat-grid">
                  <span>Dashboard <b>{apiHealth?.health?.status ?? '待检查'}</b></span>
                  <span>小懿 <b>{apiHealth?.linkage?.summary?.xiaoyi ?? '待检查'}</b></span>
                  <span>RL <b>{apiHealth?.linkage?.summary?.rl ?? '待检查'}</b></span>
                  <span>模拟器 <b>{apiHealth?.linkage?.summary?.sailing ?? '待检查'}</b></span>
                </div>
                <div className="api-topology-console">
                  <div className="api-topology-head">
                    <span><Network size={14} />联动拓扑</span>
                    <b>{systemHealthyCount}/{topologyNodes.length} 节点可用</b>
                    <small>{apiHealth?.linkage?.updated_at ?? '等待健康检查'}</small>
                  </div>
                  <div className="api-node-grid">
                    {topologyNodes.map((node) => (
                      <article className={`api-node ${node.online ? 'online' : 'offline'}`} key={node.id}>
                        <div>
                          {node.icon}
                          <span>{node.label}</span>
                        </div>
                        <b>{node.value}</b>
                        <small>{node.detail}</small>
                        {node.online ? <CheckCircle2 size={15} /> : <CircleAlert size={15} />}
                      </article>
                    ))}
                  </div>
                  <div className="api-flow-strip">
                    <span>Dashboard</span>
                    <i />
                    <span>小懿意图识别</span>
                    <i />
                    <span>RL 训练/验证</span>
                    <i />
                    <span>航行模拟器</span>
                    <i />
                    <span>Godot 执行环境</span>
                  </div>
                  <div className="api-detail-grid">
                    <div className="api-route-list">
                      <strong>RL 路由可用性</strong>
                      {displayedRouteEntries.map(([route, ok]) => (
                        <span key={route}>
                          {ok ? <CheckCircle2 size={13} /> : <CircleAlert size={13} />}
                          <b>{route}</b>
                          <em>{ok ? 'ready' : 'waiting'}</em>
                        </span>
                      ))}
                    </div>
                    <div className="api-status-card">
                      <strong>联动心跳</strong>
                      <span>小懿地址 <b>{xiaoyiSystem.base_url ?? '未连接'}</b></span>
                      <span>模拟器项目 <b>{sailingSystem.project_root?.exists ? '已找到' : '待检查'}</b></span>
                      <span>Godot 可执行 <b>{sailingSystem.godot_executable?.exists ? '可用' : '待检查'}</b></span>
                      <span>训练状态 <b>{rlStatus?.summary ?? rlStatus?.status ?? '待读取'}</b></span>
                      <span>模型注册表 <b>{modelRegistry?.count ?? 0} 个制品</b></span>
                      <span>最新阶段 <b>{latestRegisteredPolicy?.stage ?? '未注册'}</b></span>
                      <span>只读实港快照 <b>{integrationStatus?.read_only_shadow_ready ? '全部就绪' : `${integrationStatus?.ready_adapter_count ?? 0}/${integrationStatus?.required_adapter_count ?? 6}`}</b></span>
                      <span>快照完整性 <b>{integrationStatus?.missing_adapters?.length ? '失败关闭' : '签名有效'}</b></span>
                      <span>审计链 <b>{auditStatus?.ok ? '完整' : '失败关闭'}</b></span>
                      <span>生产调度 <b>{modelRegistry?.production_dispatch_enabled ? '已启用' : '已禁用'}</b></span>
                    </div>
                  </div>
                </div>
                <div className="action-command-row">
                  <button type="button" onClick={runApiCheck}><ServerCog size={14} />健康检查</button>
                  <button type="button" onClick={() => syncDashboard('API 已重新同步当前仪表盘快照。')}><RefreshCw size={14} />重新同步</button>
                </div>
              </>
            )}
          </div>

          <div className={`top-action-notice ${panelBusy ? 'working' : ''}`}>
            {panelBusy ? '执行中...' : panelNotice}
          </div>
        </section>
      )}
      {decisionImpact && <DecisionImpactOverlay state={decisionImpact} onClose={() => setDecisionImpact(null)} />}
      <XiaoyiLinkageHub
        currentGreenPreference={greenPreference}
        currentCarbonPrice={carbonPrice}
        externalOpenToken={xiaoyiOpenToken}
        onSetGreenPreference={(value, label) => {
          applyDashboardPreference(value, label, value >= 0.86 ? 'shore' : 'carbon');
        }}
        onSyncDashboard={syncDashboard}
        onOpenTopPanel={openPanel}
        onRunApiCheck={runApiCheck}
      />
    </main>
  );
}
