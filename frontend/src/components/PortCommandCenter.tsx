import { useEffect, useMemo, useState } from 'react';
import {
  Activity,
  Anchor,
  BatteryCharging,
  Bot,
  ChevronDown,
  DollarSign,
  Gauge,
  Leaf,
  Maximize2,
  Minimize2,
  Pause,
  Play,
  RefreshCw,
  ServerCog,
  Ship,
  Square,
  TriangleAlert,
  Waves,
  Wind,
  Zap,
} from 'lucide-react';
import type { DashboardSnapshot, DispatchTrajectoryPoint } from '../types/dashboard';
import type { RuntimeSnapshot } from './RuntimeClosedLoopPanel';

type CommandPanelId = 'runtime' | 'simulation' | 'marl' | 'carbon' | 'shore' | 'api';
type TrainingAction = 'pause' | 'resume' | 'stop';
type ScenarioMode = 'baseline' | 'optimized' | 'low-carbon';
type MapLayer = 'vessel' | 'agv' | 'truck' | 'planned';

export interface OperationalRuntimeState {
  latestEvent?: string;
}

interface PortCommandCenterProps {
  snapshot: DashboardSnapshot | null;
  runtimeSnapshot: RuntimeSnapshot | null;
  rlStatus: Record<string, any> | null;
  integrationStatus: Record<string, any> | null;
  auditIntegrityOk: boolean | null;
  greenPreference: number;
  carbonPrice: number;
  replayPlaying: boolean;
  activePoint?: DispatchTrajectoryPoint;
  operationState?: OperationalRuntimeState;
  onlineSystemCount: number;
  totalSystemCount: number;
  onOpenPanel: (panel: CommandPanelId) => Promise<void> | void;
  onToggleReplay: () => void;
  onRefreshSimulation: () => Promise<void> | void;
  onStartTraining: () => Promise<void> | void;
  onControlTraining: (action: TrainingAction) => Promise<void> | void;
  onOpenXiaoyi: () => void;
  onCheckSimulator: () => Promise<void> | void;
  onLaunchSimulator: () => Promise<void> | void;
  onOpenAction: (actionId: string) => void;
  onChangeRecommendationTab: (tab: 'recommended' | 'all') => void;
  onSetScenarioMode: (mode: ScenarioMode) => Promise<void> | void;
}

interface BilingualCopy {
  zh: string;
  en: string;
}

interface Recommendation extends BilingualCopy {
  tag: BilingualCopy;
  impact: string;
}

const statusCopies: Record<string, BilingualCopy> = {
  'Shore power': { zh: '岸电动作', en: 'Shore action' },
  Dispatch: { zh: '资源动作', en: 'Dispatch action' },
  Measured: { zh: '测试步', en: 'Test step' },
  Unavailable: { zh: '无数据', en: 'No data' },
};

function fmt(value: number | undefined, digits = 1) {
  if (typeof value !== 'number' || Number.isNaN(value)) return '--';
  return new Intl.NumberFormat('en-US', {
    maximumFractionDigits: digits,
    minimumFractionDigits: digits,
  }).format(value);
}

function statusClass(status: string) {
  if (status === 'Shore power' || status === 'Measured') return 'good';
  if (status === 'Unavailable') return 'warn';
  return 'info';
}

function chartCoordinates(
  values: number[],
  width = 250,
  height = 105,
  paddingX = 20,
  paddingY = 10,
  domain?: { minimum: number; maximum: number },
) {
  const maximum = domain?.maximum ?? Math.max(...values);
  const minimum = domain?.minimum ?? Math.min(...values);
  const range = Math.max(1, maximum - minimum);
  const usableWidth = width - paddingX * 2;
  const usableHeight = height - paddingY * 2;
  return values.map((value, index) => ({
    x: paddingX + (index / Math.max(1, values.length - 1)) * usableWidth,
    y: height - paddingY - ((value - minimum) / range) * usableHeight,
  }));
}

function pointsFrom(coordinates: Array<{ x: number; y: number }>) {
  return coordinates.map((point) => `${point.x.toFixed(1)},${point.y.toFixed(1)}`).join(' ');
}

function Bi({ zh, en, className = '' }: BilingualCopy & { className?: string }) {
  return <span className={`bi-label ${className}`}><span className="bi-zh">{zh}</span><span className="bi-en">{en}</span></span>;
}

export function PortCommandCenter({
  snapshot,
  runtimeSnapshot,
  rlStatus,
  integrationStatus,
  auditIntegrityOk,
  greenPreference,
  carbonPrice,
  replayPlaying,
  activePoint,
  operationState,
  onlineSystemCount,
  totalSystemCount,
  onOpenPanel,
  onToggleReplay,
  onRefreshSimulation,
  onStartTraining,
  onControlTraining,
  onOpenXiaoyi,
  onOpenAction,
  onChangeRecommendationTab,
  onSetScenarioMode,
}: PortCommandCenterProps) {
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [clock, setClock] = useState(() => new Date());
  const [scenarioMode, setScenarioMode] = useState<ScenarioMode>('optimized');
  const [viewMode, setViewMode] = useState<'2d' | '3d'>('3d');
  const [mapZoom, setMapZoom] = useState(1);
  const [recommendationTab, setRecommendationTab] = useState<'recommended' | 'all'>('recommended');
  const [layerVisibility, setLayerVisibility] = useState<Record<MapLayer, boolean>>({ vessel: true, agv: true, truck: true, planned: true });

  useEffect(() => {
    const timer = window.setInterval(() => setClock(new Date()), 1000);
    return () => window.clearInterval(timer);
  }, []);

  const traditional = snapshot?.strategies[0];
  const marl = snapshot?.strategies[1];
  const trajectory = marl?.trajectory ?? [];
  const point = activePoint ?? trajectory[0];
  const vesselRows = trajectory.slice(0, 8).map((item) => [
    item.vessel_id,
    item.time,
    item.shore_power_connected ? 'Shore power' : 'Dispatch',
  ]);
  const recommendationRows: Recommendation[] = trajectory.slice(0, 7).map((item) => ({
    zh: `${item.time} · ${item.berth_id} 资源动作`,
    en: `${item.time} ${item.berth_id} policy action`,
    tag: { zh: item.shore_power_connected ? '岸电接入' : '资源调度', en: item.event },
    impact: `${item.carbon_kg.toFixed(0)} kgCO2e`,
  }));
  const alertRows: BilingualCopy[] = [
    ...(rlStatus?.error ? [{ zh: `训练异常：${String(rlStatus.error)}`, en: 'Training runtime error' }] : []),
    ...(snapshot?.alerts ?? []).map((alert) => ({
      zh: `${alert.title_zh}：${alert.detail_zh}`,
      en: `${alert.title_en}: ${alert.detail_en}`,
    })),
  ];
  const trainingState = String(rlStatus?.status ?? 'idle');
  const canPause = Boolean(rlStatus?.can_pause ?? trainingState === 'running');
  const canResume = Boolean(rlStatus?.can_resume ?? trainingState === 'paused');
  const canStop = Boolean(rlStatus?.can_stop ?? ['running', 'paused'].includes(trainingState));
  const handledTeu = snapshot?.carbon_model.handled_teu ?? 0;
  const energySaving = (traditional?.total_energy_kwh ?? 0) - (marl?.total_energy_kwh ?? 0);
  const carbonSaving = (traditional?.total_carbon_kg ?? 0) - (marl?.total_carbon_kg ?? 0);
  const costSaving = (traditional?.total_cost_cny ?? 0) - (marl?.total_cost_cny ?? 0);
  const evidenceCoverage = Number(snapshot?.data_quality.score ?? 0);
  const energyLoad = (point?.energy_kwh ?? 0) / 1000;
  const clockText = clock.toLocaleTimeString('en-GB', { hour12: false });
  const dateText = clock.toLocaleDateString('zh-CN', { year: 'numeric', month: 'short', day: 'numeric' });
  const orderedRecommendations = recommendationTab === 'recommended'
    ? recommendationRows.map((item, index) => ({ item, index }))
    : [...recommendationRows.slice(2), ...recommendationRows.slice(0, 2)].map((item) => ({ item, index: recommendationRows.indexOf(item) }));
  const savingPct = (baseline: number | undefined, optimized: number | undefined) => {
    if (!baseline || optimized === undefined) return '0.0%';
    return `${(((optimized - baseline) / Math.abs(baseline)) * 100).toFixed(1)}%`;
  };
  const scenarioOutput = scenarioMode === 'baseline'
    ? ['0.0%', '0.0%', '0.0%']
    : [
      savingPct(traditional?.total_energy_kwh, marl?.total_energy_kwh),
      savingPct(traditional?.total_carbon_kg, marl?.total_carbon_kg),
      savingPct(traditional?.total_cost_cny, marl?.total_cost_cny),
    ];
  const activeLiveEvent = operationState?.latestEvent ?? point?.decision_reason ?? '等待测试集轨迹';
  const runtimeTemperature = runtimeSnapshot?.signals?.['weather.ambient_temperature_c'];
  const runtimeWind = runtimeSnapshot?.signals?.['weather.wind_speed_m_s'];
  const runtimeScenario = runtimeSnapshot?.active_scenario?.scenario_id ?? 'normal';
  const craneWorking = point?.crane_count ?? 0;
  const craneIdle = 0;
  const craneUtilization = craneWorking > 0 ? 100 : 0;
  const agvWorking = point?.yard_truck_count ?? 0;
  const yardSegments = [0, 0, 0];

  const energyCurve = useMemo(() => {
    const values = snapshot?.timeseries.map((item) => item.marl_energy_kwh / 1000) ?? [];
    return values.length ? values : [0];
  }, [snapshot?.timeseries]);
  const baselineEnergyCurve = useMemo(() => {
    const values = snapshot?.timeseries.map((item) => item.traditional_energy_kwh / 1000) ?? [];
    return values.length ? values : [0];
  }, [snapshot?.timeseries]);
  const carbonBase = (marl?.total_carbon_kg ?? 0) / 1000;
  const carbonCurve = useMemo(() => {
    const values = snapshot?.timeseries.map((item) => item.marl_carbon_kg / 1000) ?? [];
    return values.length ? values : [0];
  }, [snapshot?.timeseries]);
  const carbonTarget = useMemo(() => {
    const values = snapshot?.timeseries.map((item) => item.traditional_carbon_kg / 1000) ?? [];
    return values.length ? values : [0];
  }, [snapshot?.timeseries]);
  const energyDomain = useMemo(() => ({ minimum: Math.min(...energyCurve, ...baselineEnergyCurve), maximum: Math.max(...energyCurve, ...baselineEnergyCurve) }), [energyCurve, baselineEnergyCurve]);
  const energyActualCoordinates = useMemo(() => chartCoordinates(energyCurve, 250, 105, 20, 10, energyDomain), [energyCurve, energyDomain]);
  const baselineEnergyCoordinates = useMemo(() => chartCoordinates(baselineEnergyCurve, 250, 105, 20, 10, energyDomain), [baselineEnergyCurve, energyDomain]);
  const carbonDomain = useMemo(() => ({ minimum: Math.min(...carbonCurve, ...carbonTarget), maximum: Math.max(...carbonCurve, ...carbonTarget) }), [carbonCurve, carbonTarget]);
  const carbonActualCoordinates = useMemo(() => chartCoordinates(carbonCurve, 250, 100, 20, 10, carbonDomain), [carbonCurve, carbonDomain]);
  const carbonTargetCoordinates = useMemo(() => chartCoordinates(carbonTarget, 250, 100, 20, 10, carbonDomain), [carbonTarget, carbonDomain]);
  const energyPeak = Math.max(...energyCurve);
  const latestEnergyPoint = energyActualCoordinates[energyActualCoordinates.length - 1];
  const latestCarbonPoint = carbonActualCoordinates[carbonActualCoordinates.length - 1];
  const mixRows = [
    { zh: '电网', en: 'Grid', value: 100, className: 'mix-3' },
    { zh: '其他来源', en: 'Not provided', value: 0, className: 'mix-4' },
  ];

  const kpis = useMemo(() => [
    { zh: '处理量', en: 'Processed throughput', value: fmt(handledTeu, 0), unit: 'TEU', delta: { zh: '测试集轨迹计量', en: 'test split' }, icon: <Activity size={18} />, action: 'throughput' },
    { zh: '轨迹时长', en: 'Rollout horizon', value: String(trajectory.length), unit: 'h', delta: { zh: '完整环境 step', en: 'environment steps' }, icon: <Ship size={18} />, action: 'vessel-ops' },
    { zh: '泊位事件', en: 'Berth events', value: String(new Set(trajectory.map((item) => item.berth_id)).size), unit: '', delta: { zh: '轨迹真实输出', en: 'trajectory output' }, icon: <Anchor size={18} />, action: 'berth-plan' },
    { zh: '岸桥投入', en: 'Crane allocation', value: fmt(point?.crane_count ?? 0, 0), unit: '台', delta: { zh: '当前策略动作', en: 'current action' }, icon: <Gauge size={18} />, action: 'crane-plan' },
    { zh: '本步能耗', en: 'Step energy', value: fmt(energyLoad, 1), unit: 'MWh', delta: { zh: point?.time ?? '待轨迹', en: 'test step' }, icon: <Zap size={18} />, action: 'energy-load' },
    { zh: '累计能耗', en: 'Energy consumption', value: fmt((marl?.total_energy_kwh ?? 0) / 1000, 1), unit: 'MWh', delta: { zh: `差值 ${fmt(energySaving / 1000, 1)} MWh`, en: 'vs baseline' }, icon: <BatteryCharging size={18} />, action: 'energy-load' },
    { zh: '碳排放', en: 'Carbon emissions', value: fmt((marl?.total_carbon_kg ?? 0) / 1000, 1), unit: 'tCO2e', delta: { zh: `差值 ${fmt(carbonSaving / 1000, 1)} t`, en: 'vs baseline' }, icon: <Leaf size={18} />, action: 'carbon-market' },
    { zh: '碳强度', en: 'Carbon intensity', value: fmt(marl?.carbon_intensity_kg_per_teu ?? 0, 2), unit: 'kgCO2e/TEU', delta: { zh: '环境计量结果', en: 'environment metric' }, icon: <Leaf size={18} />, action: 'carbon-market' },
    { zh: '数据质量', en: 'Data quality', value: String(evidenceCoverage), unit: '%', delta: { zh: `离线 ${snapshot?.data_quality.grade ?? '--'} · 落地 ${snapshot?.data_quality.landing_readiness?.landing_grade ?? '--'}`, en: 'offline quality · landing grade' }, icon: <RefreshCw size={18} />, action: 'renewable-mix' },
    { zh: '综合成本', en: 'Operating cost', value: fmt((marl?.total_cost_cny ?? 0) / 10000, 1), unit: '¥10K', delta: { zh: `差值 ¥${fmt(costSaving / 1000, 1)}K`, en: 'vs baseline' }, icon: <DollarSign size={18} />, action: 'cost-analysis' },
  ], [carbonSaving, costSaving, energyLoad, energySaving, evidenceCoverage, handledTeu, marl, point?.crane_count, point?.time, snapshot?.data_quality.grade, snapshot?.data_quality.landing_readiness?.landing_grade, trajectory]);

  function toggleLayer(layer: MapLayer) {
    setLayerVisibility((layers) => ({ ...layers, [layer]: !layers[layer] }));
  }

  async function toggleFullscreen() {
    try {
      if (document.fullscreenElement) {
        await document.exitFullscreen();
      } else {
        await document.documentElement.requestFullscreen?.();
      }
    } catch {
      // Fullscreen can be denied by browser policy; the dashboard remains usable.
    }
  }

  useEffect(() => {
    const syncFullscreenState = () => setIsFullscreen(Boolean(document.fullscreenElement));
    syncFullscreenState();
    document.addEventListener('fullscreenchange', syncFullscreenState);
    return () => document.removeEventListener('fullscreenchange', syncFullscreenState);
  }, []);

  return (
    <div className="command-center-screen">
      <header className="command-header">
        <div className="command-live-block">
          <button className="command-live" type="button" title="打开实时数据、预测、审批与执行闭环 / Open realtime closed loop" onClick={() => void onOpenPanel('runtime')}><i /><Bi zh={runtimeSnapshot?.simulator_state === 'running' ? '公开数据校准实时模拟' : '实时模拟器失败关闭'} en={runtimeSnapshot?.simulator_state === 'running' ? 'CALIBRATED REALTIME SIMULATION' : 'RUNTIME FAIL-CLOSED'} /></button>
          <b>{clockText}</b>
          <small>{dateText}</small>
        </div>
        <div className="command-title-block">
          <h1><Bi zh="港口能碳与调度优化驾驶舱" en="PORT ENERGY, CARBON & SCHEDULING OPTIMIZATION DASHBOARD" className="command-title-copy" /></h1>
          <span className="command-developer-badge">
            <small>研发者</small><b>温家懿</b><em>Developer: Wen Jiayi</em>
          </span>
        </div>
        <div className="command-weather">
          <span><Bi zh="气象" en="Weather" /><b>{runtimeTemperature ? `${fmt(Number(runtimeTemperature.value), 1)} °C · 工程模拟` : '等待模拟器'}</b></span>
          <span><Bi zh="风速" en="Wind" /><b><Wind size={12} /> {runtimeWind ? `${fmt(Number(runtimeWind.value), 1)} m/s` : '--'}</b></span>
          <span><Bi zh="运行场景" en="Scenario" /><b><Waves size={13} /> {runtimeScenario}</b></span>
          <span><Bi zh="碳价情景" en="Carbon price scenario" /><b className="price">¥ {carbonPrice.toFixed(1)}/t</b></span>
          <button className="command-icon-button" type="button" title="打开 API 与模型治理面板 / Open API and model governance" aria-label="打开 API 与模型治理面板 / Open API and model governance" onClick={() => void onOpenPanel('api')}><ServerCog size={16} /></button>
          <button
            className="command-icon-button"
            type="button"
            title={isFullscreen ? '退出全屏驾驶舱 / Exit fullscreen cockpit' : '进入全屏驾驶舱 / Fullscreen cockpit'}
            aria-label={isFullscreen ? '退出全屏驾驶舱 / Exit fullscreen cockpit' : '进入全屏驾驶舱 / Fullscreen cockpit'}
            aria-pressed={isFullscreen}
            onClick={() => void toggleFullscreen()}
          >
            {isFullscreen ? <Minimize2 size={16} /> : <Maximize2 size={16} />}
          </button>
        </div>
      </header>

      <section className="command-kpi-row" aria-label="关键业务指标 / Key performance indicators">
        {kpis.map((item, index) => (
          <button className="command-kpi" key={item.en} type="button" title={`打开${item.zh}详情 / Open ${item.en}`} aria-label={`打开${item.zh}详情 / Open ${item.en}`} onClick={() => onOpenAction(item.action)}>
            <span className={`command-kpi-icon tone-${index % 4}`}>{item.icon}</span>
            <div>
              <Bi zh={item.zh} en={item.en} className="kpi-label" />
              <b>{item.value}<em>{item.unit}</em></b>
              <i><Bi zh={item.delta.zh} en={item.delta.en} /></i>
            </div>
            {(index === 0 || index > 6) && <ChevronDown size={12} />}
          </button>
        ))}
      </section>

      <section className="command-main-grid">
        <aside className="command-panel operations-overview">
          <div className="command-panel-title"><b><Bi zh="运营总览" en="OPERATIONS OVERVIEW" /></b><Activity size={13} /></div>
          <section className="ops-section vessel-queue">
            <div className="ops-title"><b><Bi zh={`测试轨迹（${vesselRows.length}）`} en={`TEST TRAJECTORY (${vesselRows.length})`} /></b><button type="button" onClick={() => onOpenAction('vessel-queue')}><Bi zh="查看全部" en="View all" /> →</button></div>
            <div className="ops-table-head"><Bi zh="数据记录" en="Data record" /><Bi zh="测试时刻" en="Test time" /><Bi zh="动作" en="Action" /></div>
            {vesselRows.map((vessel, index) => {
              const status = statusCopies[vessel[2]] ?? { zh: vessel[2], en: vessel[2] };
              return <button className="ops-table-row ops-row-button" key={`${vessel[0]}-${vessel[1]}-${index}`} type="button" title={`查看 ${vessel[0]} 测试步 / View ${vessel[0]} test step`} onClick={() => onOpenAction(`vessel-${index}`)}>
                <span><i>{index + 1}</i>{vessel[0]}</span><span>{vessel[1]}</span><b className={statusClass(vessel[2])}><Bi {...status} /></b>
              </button>;
            })}
          </section>

          <section className="ops-section berth-allocation">
            <div className="ops-title"><b><Bi zh="泊位分配" en="BERTH ALLOCATION" /></b><button type="button" onClick={() => onOpenAction('berth-plan')}><Bi zh="查看全部" en="View all" /> →</button></div>
            <div className="berth-table-head"><Bi zh="泊位" en="Berth" /><Bi zh="船舶" en="Vessel" /><Bi zh="作业窗口" en="Start – end" /><Bi zh="状态" en="Status" /></div>
            {[{ label: 'B01', id: 'B1' }, { label: 'B02', id: 'B2' }, { label: 'B03', id: 'B3' }, { label: 'B04', id: 'B4' }].map((berth) => {
              const trajectoryPoint = trajectory.find((item) => item.berth_id === berth.id);
              const statusName = trajectoryPoint ? 'Measured' : 'Unavailable';
              const status = statusCopies[statusName];
              const windowTime = trajectoryPoint ? `${trajectoryPoint.time} · test step ${trajectoryPoint.step}` : '—';
              return <button className="berth-table-row berth-row-button" key={berth.id} type="button" title={`查看 ${berth.label} 测试步 / Open ${berth.label} test step`} onClick={() => onOpenAction(`berth-${berth.label.toLowerCase()}`)}>
                <b>{berth.label}</b><span>{trajectoryPoint?.vessel_id ?? '—'}</span><span>{windowTime}</span><em className={statusClass(statusName)}><Bi {...status} /></em>
              </button>;
            })}
          </section>

          <section className="ops-section crane-assignment">
            <div className="ops-title"><b><Bi zh="岸桥分配" en="CRANE ASSIGNMENT" /></b><small>当前动作 {craneWorking} 台<br />from policy trajectory</small></div>
            <button className="crane-ring-wrap ops-graphic-button" type="button" title="查看岸桥分配策略 / View crane assignment plan" onClick={() => onOpenAction('crane-plan')}>
              <div className="crane-ring"><b>{craneUtilization}%</b><small><Bi zh="利用率" en="Utilization" /></small></div>
              <div className="crane-legend"><span><i className="blue" /><Bi zh="策略投入" en="Allocated" /><b>{craneWorking}</b></span><span><i className="teal" /><Bi zh="空闲" en="Not in dataset" /><b>{craneIdle}</b></span></div>
            </button>
          </section>

          <section className="ops-section occupancy-section">
            <div className="ops-title"><b><Bi zh="堆场占用率" en="YARD OCCUPANCY" /></b><small>当前公开数据集未提供<br />Not provided by source</small></div>
            <button className="segmented-meter meter-button" type="button" title="查看堆场占用与调度 / View yard occupancy and dispatch" onClick={() => onOpenAction('yard-occupancy')}><i style={{ width: `${yardSegments[0]}%` }} /><i style={{ width: `${yardSegments[1]}%` }} /><i style={{ width: `${yardSegments[2]}%` }} /></button>
            <div className="meter-legend"><Bi zh="换用实际堆场快照后启用" en="Requires yard snapshot columns" /></div>
          </section>

          <section className="ops-section occupancy-section">
            <div className="ops-title"><b><Bi zh="场内车辆投入" en="YARD VEHICLE ALLOCATION" /></b><small>当前策略 {agvWorking} 辆<br />from trajectory action</small></div>
            <button className="agv-meter meter-button" type="button" title="查看场内车辆调度 / View yard vehicle dispatch" onClick={() => onOpenAction('agv-dispatch')}><i style={{ width: `${agvWorking > 0 ? 100 : 0}%` }} /></button><b className="meter-value">{agvWorking}</b>
            <div className="meter-legend"><span><i className="green-dot" /><Bi zh="作业中" en="Working" /></span><span><i className="teal-dot" /><Bi zh="空闲" en="Idle" /></span><span><i className="blue-dot" /><Bi zh="充电中" en="Charging" /></span></div>
          </section>

          <section className="ops-section alerts-section">
            <div className="ops-title"><b><Bi zh={`治理与约束（${alertRows.length}）`} en={`GOVERNANCE & CONSTRAINTS (${alertRows.length})`} /></b><button type="button" onClick={() => onOpenAction('alerts')}><Bi zh="查看全部" en="View all" /> →</button></div>
            {alertRows.length === 0 && <div className="alert-row"><small>--:--</small><b><Bi zh="当前无治理或约束告警" en="No governance or constraint alerts" /></b></div>}
            {alertRows.map((alert, index) => {
              return <button className="alert-row" type="button" key={alert.en} title={`${alert.zh} / ${alert.en}`} onClick={() => onOpenAction('alerts')}><TriangleAlert size={11} /><small>{point?.time ?? '--:--'}</small><b><Bi {...alert} /></b></button>;
            })}
          </section>
        </aside>

        <section className="command-panel digital-twin-panel">
          <div className="command-panel-title twin-title">
            <b><Bi zh="测试轨迹回放" en="HELD-OUT TRAJECTORY REPLAY" /></b>
            <div className="twin-toolbar">
              <button className="twin-evidence-button" type="button" title="打开算法落地证据 / Open algorithm evidence" onClick={() => void onOpenPanel('marl')}><Gauge size={11} /><Bi zh="证据" en="Evidence" /></button>
              <button className={viewMode === '2d' ? 'active' : ''} type="button" title="切换二维泊位视图 / Switch to 2D berth view" aria-label="切换二维泊位视图 / Switch to 2D berth view" aria-pressed={viewMode === '2d'} onClick={() => setViewMode('2d')}>2D</button>
              <button className={viewMode === '3d' ? 'active' : ''} type="button" title="切换三维港区视图 / Switch to 3D port view" aria-label="切换三维港区视图 / Switch to 3D port view" aria-pressed={viewMode === '3d'} onClick={() => setViewMode('3d')}>◆ 3D</button>
              <button type="button" title={replayPlaying ? '暂停数字孪生回放 / Pause twin replay' : '继续数字孪生回放 / Resume twin replay'} aria-label={replayPlaying ? '暂停数字孪生回放 / Pause twin replay' : '继续数字孪生回放 / Resume twin replay'} onClick={onToggleReplay}>⌁</button>
              <button type="button" title="刷新仿真回放 / Refresh simulation replay" aria-label="刷新仿真回放 / Refresh simulation replay" onClick={onRefreshSimulation}>▦</button>
            </div>
          </div>
          <div className={`command-twin-stage view-${viewMode} ${replayPlaying ? 'playing' : 'paused'}`}>
            <div className="twin-map-world" style={{ transform: `scale(${mapZoom})` }}>
              <button className="reference-map-layer" type="button" title="查看离线测试轨迹 / View held-out trajectory" aria-label="查看离线测试轨迹 / View held-out trajectory" onClick={() => onOpenAction('twin-map')} />
              <span className="twin-tide-shimmer" />
              <svg className="twin-network-layer" viewBox="0 0 800 520" preserveAspectRatio="none" aria-hidden="true">
                <defs>
                  <linearGradient id="twin-channel-glow" x1="0" y1="0" x2="1" y2="0">
                    <stop offset="0" stopColor="#13c6ff" stopOpacity="0.12" />
                    <stop offset="0.55" stopColor="#13c6ff" stopOpacity="0.92" />
                    <stop offset="1" stopColor="#77eaff" stopOpacity="0.5" />
                  </linearGradient>
                </defs>
                {layerVisibility.vessel && <path className="twin-network-route vessel" d="M66 398 C176 376 275 326 370 286 C471 244 566 268 672 207" />}
              </svg>
              <div className="twin-terminal-zone" aria-hidden="true">
                <span><Bi zh="测试泊位区" en="TEST BERTH ZONE" /></span>
              </div>
              {[{ label: 'B01', id: 'B1' }, { label: 'B02', id: 'B2' }, { label: 'B03', id: 'B3' }, { label: 'B04', id: 'B4' }].map((berth, index) => {
                const berthPoint = trajectory.find((item) => item.berth_id === berth.id);
                const isActive = point?.berth_id === berth.id;
                return <button className={`twin-berth-node berth-node-${index + 1} ${isActive ? 'active' : ''}`} type="button" key={berth.id} title={`查看 ${berth.label} 测试步 / Open ${berth.label} test step`} onClick={() => onOpenAction(`berth-${berth.label.toLowerCase()}`)}>
                  <i />
                  <span>{isActive ? 'CURRENT' : 'TEST'}</span>
                  <b>{berth.label}</b>
                  <small>{berthPoint?.time ?? '--:--'} · {berthPoint?.vessel_id ?? '无测试记录'}</small>
                </button>;
              })}
              <button className="twin-moving-vessel" type="button" title={replayPlaying ? '暂停测试轨迹 / Pause test replay' : '继续测试轨迹 / Resume test replay'} aria-label={replayPlaying ? '暂停测试轨迹 / Pause test replay' : '继续测试轨迹 / Resume test replay'} onClick={onToggleReplay}><Ship size={15} /><small>{point?.berth_id ?? 'B--'}</small></button>
            </div>
            <span className="twin-scan-line" />
            <button className="twin-current-card" type="button" title="查看当前测试轨迹 / View current test trajectory" onClick={() => onOpenAction(`berth-${(point?.berth_id ?? 'B1').toLowerCase().replace('b', 'b0')}`)}>
              <span><i /><Bi zh="当前测试步" en="CURRENT TEST STEP" /></span>
              <b>{point?.vessel_id ?? '等待测试集'} <em>→</em> {point?.berth_id ?? 'B--'}</b>
              <small>{point?.time ?? '--:--'} · STEP {point?.step ?? 0}　岸桥 {point?.crane_count ?? 0}　集卡 {point?.yard_truck_count ?? 0}</small>
            </button>
            <button className="twin-data-boundary" type="button" title="查看数据边界 / View data boundary" onClick={() => onOpenAction('berth-b04')}><b>DATA</b><Bi zh="公开测试集 · 非实时港口" en="PUBLIC TEST SPLIT · NOT LIVE" /></button>
            <div className="twin-legend" aria-label="港区图层控制 / Port layer controls">
              <button className={layerVisibility.vessel ? 'active' : ''} type="button" aria-pressed={layerVisibility.vessel} title="显示或隐藏归一化测试航迹 / Toggle normalized test route" onClick={() => toggleLayer('vessel')}><i className="route vessel" /><Bi zh="测试航迹" en="TEST ROUTE" /></button>
              <span><Anchor size={12} /><Bi zh={`${point?.berth_id ?? 'B--'} 泊位`} en="CURRENT BERTH" /></span>
              <span><Gauge size={12} /><Bi zh={`岸桥 ${point?.crane_count ?? 0}`} en="CRANES" /></span>
              <span><ServerCog size={12} /><Bi zh={`集卡 ${point?.yard_truck_count ?? 0}`} en="TRUCKS" /></span>
              <span className={point?.shore_power_connected ? 'connected' : 'disconnected'}><Zap size={12} /><Bi zh={point?.shore_power_connected ? '岸电已接' : '岸电未接'} en="SHORE POWER" /></span>
            </div>
            <div className="twin-live-status"><i /><Bi zh="测试回放" en="TEST REPLAY" /><small>{activeLiveEvent}</small></div>
            <div className="twin-map-controls">
              <button type="button" title="重置地图视角 / Reset map" aria-label="重置地图视角 / Reset map" onClick={() => { setMapZoom(1); setViewMode('3d'); }}>⌖</button>
              <button type="button" title="查看岸电窗口联动 / View shore power" aria-label="查看岸电窗口联动 / View shore power" onClick={() => void onOpenPanel('shore')}>▱</button>
              <button type="button" title="缩小港区视图 / Zoom out" aria-label="缩小港区视图 / Zoom out" onClick={() => setMapZoom((zoom) => Math.max(1, Number((zoom - 0.05).toFixed(2))))}>−</button>
              <button type="button" title="放大港区视图 / Zoom in" aria-label="放大港区视图 / Zoom in" onClick={() => setMapZoom((zoom) => Math.min(1.2, Number((zoom + 0.05).toFixed(2))))}>＋</button>
            </div>
          </div>
        </section>

        <section className="command-panel schedule-panel">
          <div className="command-panel-title"><b><Bi zh="测试轨迹时间线" en="TEST TRAJECTORY TIMELINE" /></b><span><Bi zh="非生产船期" en="NOT A LIVE SCHEDULE" /></span></div>
          <div className="schedule-content">
            <button className="gantt-board gantt-action" type="button" title="查看船期时间线与窗口 / View timeline and windows" onClick={() => onOpenAction('timeline')}>
              <div className="gantt-times">{(trajectory.length ? trajectory.slice(0, 10).map((item) => item.time) : ['--:--']).map((time, index) => <span key={`${time}-${index}`}>{time}</span>)}</div>
              {trajectory.slice(0, 4).map((item, index) => <div className="gantt-row" key={`${item.berth_id}-${item.step}`}><b>{item.berth_id}</b><span>{item.vessel_id}</span><i style={{ left: `${12 + index * 18}%`, width: '16%' }}><Ship size={10} />{item.time}</i></div>)}
              <span className="gantt-now" />
            </button>
            <div className="schedule-table">
              <div><Bi zh="数据记录" en="Data record" /><Bi zh="测试时刻" en="Test time" /><Bi zh="下一步" en="Next step" /><Bi zh="泊位" en="Berth" /><Bi zh="动作" en="Action" /></div>
              {vesselRows.slice(0, 5).map((vessel, index) => { const status = statusCopies[vessel[2]] ?? { zh: vessel[2], en: vessel[2] }; return <button type="button" key={`${vessel[0]}-${index}`} title={`查看 ${vessel[0]} 测试轨迹 / View ${vessel[0]} test trajectory`} onClick={() => onOpenAction(`vessel-${index}`)}><span>{vessel[0]}</span><span>{vessel[1]}</span><span>—</span><span>{trajectory[index]?.berth_id ?? '—'}</span><em className={statusClass(vessel[2])}><Bi {...status} /></em></button>; })}
            </div>
          </div>
        </section>

        <aside className="command-right-column">
          <section className="command-panel ai-optimization-panel">
            <div className="command-panel-title">
              <b><Bi zh="AI 优化中心" en="AI OPTIMIZATION CENTER" /></b>
              <div className="ai-title-actions"><button className="xiaoyi-link-trigger" type="button" title="打开小懿联动中枢 / Open Xiaoyi hub" onClick={onOpenXiaoyi}><Bot size={14} /><Bi zh="小懿联动" en="AI COPILOT" /></button><span><Bi zh="数据可追溯" en="Data traceability" />　<strong>◉ {evidenceCoverage}%</strong></span></div>
            </div>
            <div className="optimization-tabs"><button className={recommendationTab === 'recommended' ? 'active' : ''} type="button" aria-pressed={recommendationTab === 'recommended'} onClick={() => { setRecommendationTab('recommended'); onChangeRecommendationTab('recommended'); }}><Bi zh="推荐动作" en="RECOMMENDED" /></button><button className={recommendationTab === 'all' ? 'active' : ''} type="button" aria-pressed={recommendationTab === 'all'} onClick={() => { setRecommendationTab('all'); onChangeRecommendationTab('all'); }}><Bi zh="全部方案" en="ALL OPTIONS" /></button></div>
            <div className="recommendation-list">
              {orderedRecommendations.map(({ item, index }) => {
                const actionId = `recommendation-${index}`;
                return <button type="button" key={item.en} title={`查看策略动作：${item.zh} / View ${item.en}`} onClick={() => onOpenAction(actionId)}><i>{index + 1}</i><Bi zh={item.zh} en={item.en} className="recommendation-copy" /><em><Bi {...item.tag} /></em><b>{item.impact}</b></button>;
              })}
            </div>
            <button className="view-recommendations" type="button" onClick={onOpenXiaoyi}><Bi zh="打开全部小懿建议" en="VIEW ALL RECOMMENDATIONS" /> →</button>
          </section>

          <section className="command-analytics-grid">
            <button className="mini-command-panel chart-action load-curve-panel" type="button" title="查看测试轨迹能耗与电网负荷 / View test energy and grid load" onClick={() => onOpenAction('energy-load')}>
              <div className="mini-command-title"><b><Bi zh="测试轨迹能耗" en="TEST ENERGY LOAD (MW)" /></b><span><Bi zh="轨迹峰值" en="Peak" /><strong>{fmt(energyPeak, 1)} MW</strong></span></div>
              <svg viewBox="0 0 250 105" role="img" aria-label="测试轨迹能耗曲线 / Test energy load curve">
                <path className="chart-grid" d="M20 18H240M20 45H240M20 72H240M20 99H240M20 15V99M75 15V99M130 15V99M185 15V99M240 15V99" />
                <polyline className="chart-line blue chart-line-live" points={pointsFrom(energyActualCoordinates)} />
                <polyline className="chart-line dashed chart-line-forecast" points={pointsFrom(baselineEnergyCoordinates)} />
                {latestEnergyPoint && <circle className="chart-point blue" cx={latestEnergyPoint.x} cy={latestEnergyPoint.y} r="3.2" />}
              </svg>
            </button>
            <button className="mini-command-panel chart-action energy-mix-panel" type="button" title="查看可再生与岸电结构 / View renewable and shore-power mix" onClick={() => onOpenAction('renewable-mix')}>
              <div className="mini-command-title"><b><Bi zh="能源结构" en="ENERGY SOURCE MIX" /></b></div>
              <div className="energy-mix-body"><div className="mix-donut"><b>N/A</b><small><Bi zh="来源结构" en="SOURCE MIX" /></small></div><div>{mixRows.map((row) => <span key={row.en}><i className={row.className} /><Bi zh={row.zh} en={row.en} /><b>{row.value}%</b></span>)}</div></div>
            </button>
            <button className="mini-command-panel chart-action emission-chart-panel" type="button" title="查看碳核算与配额 / View carbon accounting and quota" onClick={() => void onOpenPanel('carbon')}>
              <div className="mini-command-title"><b><Bi zh="碳排放趋势" en="CARBON EMISSIONS (tCO2e)" /></b></div>
              <svg viewBox="0 0 250 100" role="img" aria-label="测试轨迹碳排放对比 / Test carbon comparison"><path className="chart-grid" d="M20 15H240M20 42H240M20 69H240M20 96H240M20 15V96M64 15V96M108 15V96M152 15V96M196 15V96M240 15V96" /><polyline className="chart-line green chart-line-live" points={pointsFrom(carbonActualCoordinates)} /><polyline className="chart-line blue dashed chart-line-forecast" points={pointsFrom(carbonTargetCoordinates)} />{latestCarbonPoint && <circle className="chart-point green" cx={latestCarbonPoint.x} cy={latestCarbonPoint.y} r="3.2" />}</svg>
            </button>
            <button className="mini-command-panel chart-action baseline-panel" type="button" title="查看控制基线与优化策略对比 / View strategy comparison" onClick={() => onOpenAction('strategy-comparison')}>
              <div className="mini-command-title"><b><Bi zh="基线与优化对比" en="BASELINE VS OPTIMIZED" /></b><small><Bi zh="测试集" en="Held-out" /></small></div>
              <div className="bar-comparison">{[
                ['能耗', 'Energy', 90, 90 * (marl?.total_energy_kwh ?? 0) / Math.max(1, traditional?.total_energy_kwh ?? 0), fmt(traditional?.total_energy_kwh ?? 0, 0), fmt(marl?.total_energy_kwh ?? 0, 0)],
                ['碳排', 'Carbon', 90, 90 * (marl?.total_carbon_kg ?? 0) / Math.max(1, traditional?.total_carbon_kg ?? 0), fmt((traditional?.total_carbon_kg ?? 0) / 100, 0), fmt((marl?.total_carbon_kg ?? 0) / 100, 0)],
                ['成本', 'Cost', 90, 90 * (marl?.total_cost_cny ?? 0) / Math.max(1, traditional?.total_cost_cny ?? 0), fmt((traditional?.total_cost_cny ?? 0) / 1000, 0), fmt((marl?.total_cost_cny ?? 0) / 1000, 0)],
              ].map((row) => <span key={String(row[1])}><i style={{ height: `${row[2]}%` }}><small>{row[4]}</small></i><i className="optimized" style={{ height: `${row[3]}%` }}><small>{row[5]}</small></i><b><Bi zh={String(row[0])} en={String(row[1])} /></b></span>)}</div>
            </button>
          </section>

          <section className="command-panel forecast-panel">
            <div className="command-panel-title"><b><Bi zh="24 小时测试轨迹摘要" en="24-HOUR TEST ROLLOUT" /></b></div>
            <div>{[
              ['处理量', 'Throughput', fmt(handledTeu, 0), '测试集'], ['本步能耗', 'Energy load', fmt(energyLoad, 1), point?.time ?? '--'], ['累计碳排', 'Carbon emissions', fmt(carbonBase, 1), '测试轨迹'], ['数据来源', 'Data source', 'POLA+eGRID', snapshot?.carbon_model.dataset_sha256.slice(0, 8) ?? '--'], ['碳价情景', 'Carbon price', `¥${carbonPrice.toFixed(1)}`, '用户输入'],
            ].map((row) => <button type="button" key={String(row[1])} title={`查看${row[0]} / View ${row[1]}`} onClick={() => onOpenAction(row[1] === 'Carbon price' || row[1] === 'Carbon emissions' ? 'carbon-market' : row[1] === 'Energy load' ? 'energy-load' : row[1] === 'Renewable share' ? 'renewable-mix' : 'throughput')}><Bi zh={String(row[0])} en={String(row[1])} /><b>{row[2]}</b><em>{row[3]}</em></button>)}</div>
          </section>

          <section className="command-panel scenario-panel">
            <div className="command-panel-title"><b><Bi zh="场景推演" en="SCENARIO SIMULATION" /></b></div>
            <div className="scenario-controls"><div>{(['baseline', 'optimized', 'low-carbon'] as const).map((mode) => {
              const copy = mode === 'baseline' ? { zh: '基线方案', en: 'Baseline' } : mode === 'optimized' ? { zh: '综合优化', en: 'Optimized' } : { zh: '低碳优先', en: 'Low-carbon' };
              return <button className={scenarioMode === mode ? 'active' : ''} type="button" key={mode} aria-pressed={scenarioMode === mode} onClick={() => { setScenarioMode(mode); void onSetScenarioMode(mode); }}><Bi {...copy} /></button>;
            })}</div><button type="button" onClick={onRefreshSimulation}><Bi zh="运行推演" en="Run simulation" /> →</button></div>
            <div className="scenario-deltas"><span><Bi zh="能耗" en="Energy" /> <b>{scenarioOutput[0]}</b></span><span><Bi zh="碳排" en="Carbon" /> <b>{scenarioOutput[1]}</b></span><span><Bi zh="成本" en="Cost" /> <b>{scenarioOutput[2]}</b></span><span><Bi zh="数据分区" en="Split" /> <b>TEST</b></span><span><Bi zh="对照基线" en="Baseline" /> <b>{traditional?.strategy ?? '--'}</b></span><span><Bi zh="当前策略" en="Policy" /> <b>{marl?.strategy ?? '--'}</b></span></div>
            <div className="training-inline-controls"><span>RL {trainingState.toUpperCase()}</span><button type="button" title="查看 RL 因果评测证据 / View RL causal evidence" aria-label="查看 RL 因果评测证据 / View RL causal evidence" onClick={() => void onOpenPanel('marl')}><Gauge size={11} /><Bi zh="证据" en="Evidence" /></button><button type="button" title="启动 RL 训练 / Start RL training" aria-label="启动 RL 训练 / Start RL training" onClick={onStartTraining}><Play size={11} /><Bi zh="训练" en="Train" /></button><button type="button" title={canResume ? '继续 RL 训练 / Resume RL training' : '暂停 RL 训练 / Pause RL training'} aria-label={canResume ? '继续 RL 训练 / Resume RL training' : '暂停 RL 训练 / Pause RL training'} disabled={!canPause && !canResume} onClick={() => onControlTraining(canResume ? 'resume' : 'pause')}>{canResume ? <Play size={11} /> : <Pause size={11} />}</button><button type="button" title="停止 RL 训练 / Stop RL training" aria-label="停止 RL 训练 / Stop RL training" disabled={!canStop} onClick={() => onControlTraining('stop')}><Square size={10} /></button><button type="button" title={replayPlaying ? '暂停数字孪生回放 / Pause twin replay' : '继续数字孪生回放 / Resume twin replay'} aria-label={replayPlaying ? '暂停数字孪生回放 / Pause twin replay' : '继续数字孪生回放 / Resume twin replay'} onClick={onToggleReplay}>{replayPlaying ? <Pause size={11} /> : <Play size={11} />}<Bi zh="孪生" en="Twin" /></button></div>
          </section>
        </aside>
      </section>

      <footer className="command-status-footer"><span><i />{onlineSystemCount}/{totalSystemCount} <Bi zh="系统在线" en="SYSTEMS ONLINE" /></span><span><Bi zh="实时模拟" en="RUNTIME" />: {runtimeSnapshot?.simulator_state ?? 'checking'}</span><span><Bi zh="实港快照" en="PORT FEEDS" />: {integrationStatus?.ready_adapter_count ?? 0}/{integrationStatus?.required_adapter_count ?? 6}</span><span><Bi zh="审计链" en="AUDIT CHAIN" />: {auditIntegrityOk === true ? 'INTACT' : 'FAIL-CLOSED'}</span><span><Bi zh="模式" en="MODE" />: {runtimeSnapshot?.data_mode ?? snapshot?.governance.deployment_mode ?? '等待数据'}</span><span><Bi zh="策略" en="POLICY" />: {rlStatus?.policy_version ?? marl?.strategy ?? '等待策略'}</span><span><Bi zh="生产调度" en="PRODUCTION DISPATCH" />: DISABLED</span><span><Bi zh="更新时间" en="UPDATED" /> {clockText}</span></footer>
    </div>
  );
}
