import {
  Activity,
  BatteryCharging,
  CheckCircle2,
  CircleAlert,
  Database,
  History,
  Play,
  RefreshCw,
  RotateCcw,
  ShieldCheck,
  Square,
  ThermometerSun,
  Zap,
} from 'lucide-react';

export interface RuntimeSignal {
  field_id: string;
  value: number | string | boolean | null;
  unit: string;
  event_time: string;
  ingest_time: string;
  source_type: string;
  source_id: string;
  quality_status: string;
  confidence: number;
  is_measured: boolean;
  is_simulated: boolean;
  is_derived: boolean;
  site_id: string;
  asset_id: string;
  schema_version: string;
  trace_id: string;
  source_record_time?: string | null;
  assumption_id?: string | null;
}

export interface RuntimeSnapshot {
  schema_version: string;
  snapshot_id: string;
  trace_id: string;
  simulator_state: string;
  data_mode: string;
  live_data_verified: boolean;
  dispatch_allowed: boolean;
  production_authority: boolean;
  virtual_event_time: string;
  generated_at: string;
  step: number;
  active_scenario: { scenario_id: string; remaining_steps: number };
  signals: Record<string, RuntimeSignal>;
  quality: Record<string, any>;
  kpis: Record<string, any>;
  decision_allowed: boolean;
  snapshot_sha256: string;
  dataset: Record<string, any>;
}

interface RuntimeClosedLoopPanelProps {
  snapshot: RuntimeSnapshot | null;
  forecast: Record<string, any> | null;
  decision: Record<string, any> | null;
  history: Record<string, any> | null;
  integrationStatus: Record<string, any> | null;
  busy: boolean;
  onRefresh: () => Promise<void> | void;
  onCreateDecision: () => Promise<void> | void;
  onApprove: (approverId: string) => Promise<void> | void;
  onExecute: () => Promise<void> | void;
  onRollback: () => Promise<void> | void;
  onInject: (scenarioId: string) => Promise<void> | void;
  onControl: (action: 'start' | 'stop' | 'reset') => Promise<void> | void;
}

function fmt(value: unknown, digits = 1) {
  const number = Number(value);
  if (!Number.isFinite(number)) return '--';
  return new Intl.NumberFormat('zh-CN', {
    maximumFractionDigits: digits,
    minimumFractionDigits: digits,
  }).format(number);
}

function shortHash(value: unknown) {
  const text = String(value ?? '');
  return text ? `${text.slice(0, 12)}…${text.slice(-6)}` : '--';
}

function signal(snapshot: RuntimeSnapshot | null, id: string) {
  return snapshot?.signals?.[id];
}

const liveCards = [
  ['grid.import_power_kw', '电网进口', 'Grid import'],
  ['transformer.loading_pct', '变压器负载率', 'Transformer loading'],
  ['solar.available_power_kw', '光伏可用功率', 'Solar available'],
  ['battery.power_kw', '储能功率', 'Battery power'],
  ['battery.soc_pct', 'SOC', 'Battery SOC'],
  ['battery.soh_pct', 'SOH', 'Battery SOH'],
  ['battery.temperature_c', '电池温度', 'Battery temperature'],
  ['shore_power.load_kw', '岸电负荷', 'Shore-power load'],
  ['charging.agv_load_kw', 'AGV 充电', 'AGV charging'],
  ['reefer.load_kw', '冷藏箱负荷', 'Reefer load'],
  ['hvac.load_kw', '暖通负荷', 'HVAC load'],
  ['lighting.load_kw', '照明负荷', 'Lighting load'],
  ['operations.processed_teu', '本步处理量', 'Processed throughput'],
  ['operations.queue_teu', '作业队列', 'Operation queue'],
  ['kpi.step_carbon_kg', '本步碳排', 'Step carbon'],
  ['kpi.step_cost_cny', '本步成本', 'Step cost'],
] as const;

const scenarioButtons = [
  ['communications_loss', '注入失联'],
  ['sensor_drift', '注入漂移'],
  ['transformer_derating', '变压器降额'],
  ['battery_overtemperature', '电池过温'],
  ['extreme_heat', '极端高温'],
  ['equipment_fault', '设备故障'],
  ['demand_response_event', '需求响应事件'],
] as const;

export function RuntimeClosedLoopPanel({
  snapshot,
  forecast,
  decision,
  history,
  integrationStatus,
  busy,
  onRefresh,
  onCreateDecision,
  onApprove,
  onExecute,
  onRollback,
  onInject,
  onControl,
}: RuntimeClosedLoopPanelProps) {
  const classifications = snapshot?.quality?.classification_pct ?? {};
  const decisionStatus = String(decision?.status ?? 'not_created');
  const approvals = Array.isArray(decision?.approvals) ? decision.approvals : [];
  const requiredApprovals = Number(decision?.required_approvals ?? 0);
  const receipt = decision?.execution_receipt as Record<string, any> | null | undefined;
  const kpiDelta = (receipt?.kpi_delta ?? {}) as Record<string, number>;
  const forecastPoints = Array.isArray(forecast?.points) ? forecast.points : [];
  const historyItems = Array.isArray(history?.items) ? history.items.slice(-12) : [];
  const lineage = Object.values(snapshot?.signals ?? {});
  const recommendedAction = (decision?.recommended_action ?? {}) as Record<string, number>;
  const projectedAction = (decision?.projected_action ?? {}) as Record<string, number>;
  const integrationAdapters = Array.isArray(integrationStatus?.adapters) ? integrationStatus.adapters : [];
  const shadowReady = Boolean(integrationStatus?.read_only_shadow_ready);
  const alignment = integrationStatus?.dynamic_time_alignment ?? {};
  const firstIntegrationBlocker = String(integrationStatus?.blocker_codes?.[0] ?? '');
  const integrationBlockerZh: Record<string, string> = {
    shadow_mode_not_configured: '尚未启用具名港口影子模式。',
    signed_feed_evidence_incomplete: '六路数据尚未全部通过签名、结构和时效校验。',
    resident_payload_missing: '服务启动后六个数据源必须重新发送，摘要不能恢复业务值。',
    dynamic_sources_not_time_aligned: '五个动态数据源的观测时间差超过 300 秒。',
    identity_or_audit_not_ready: '身份鉴权或防篡改审计链尚未就绪。',
  };

  return (
    <div className="runtime-closed-loop">
      <div className="runtime-trust-strip">
        <span className={snapshot?.simulator_state === 'running' ? 'ok' : 'blocked'}>
          <i />公开数据校准实时模拟<small>PUBLIC-DATA-CALIBRATED SIMULATION</small>
        </span>
        <span className={forecast?.true_model_inference ? 'ok' : 'blocked'}>
          <i />模型真实推理输出<small>MODEL INFERENCE</small>
        </span>
        <span className={shadowReady ? 'ok' : 'blocked'}>
          <i />六源统一影子快照
          <small>{shadowReady ? 'ATOMIC SHADOW STATE READY' : `${integrationStatus?.resident_payload_count ?? 0}/${integrationStatus?.required_adapter_count ?? 6} RESIDENT`}</small>
        </span>
        <span className="blocked"><i />生产控制禁用<small>PRODUCTION AUTHORITY = FALSE</small></span>
      </div>

      <section className="runtime-control-board">
        <div>
          <strong><Activity size={15} />实时模拟器</strong>
          <span>状态 <b>{snapshot?.simulator_state ?? 'loading'}</b></span>
          <span>场景 <b>{snapshot?.active_scenario?.scenario_id ?? '--'}</b></span>
          <span>步数 <b>{snapshot?.step ?? '--'}</b></span>
          <span>虚拟时间 <b>{snapshot?.virtual_event_time ?? '--'}</b></span>
          <span>质量门禁 <b className={snapshot?.decision_allowed ? 'good' : 'bad'}>{snapshot?.decision_allowed ? 'PASS' : 'FAIL-CLOSED'}</b></span>
        </div>
        <div className="runtime-actions">
          <button id="btnRuntimeRefresh" type="button" disabled={busy} onClick={() => void onRefresh()}><RefreshCw size={13} />刷新</button>
          <button id="btnRuntimeStart" type="button" disabled={busy} onClick={() => void onControl('start')}><Play size={13} />启动</button>
          <button id="btnRuntimeStop" type="button" disabled={busy} onClick={() => void onControl('stop')}><Square size={12} />停止</button>
          <button id="btnRuntimeReset" type="button" disabled={busy} onClick={() => void onControl('reset')}><RotateCcw size={13} />复位</button>
        </div>
      </section>

      <section className={`runtime-shadow-section ${shadowReady ? 'ready' : 'blocked'}`}>
        <div className="runtime-section-title">
          <strong><Database size={15} />六源实港只读影子状态</strong>
          <span>{shadowReady ? 'READY · 原子快照可读' : 'FAIL-CLOSED · 不释放混合输入'}</span>
        </div>
        <div className="runtime-shadow-summary">
          <span>签名与时效<b>{integrationStatus?.ready_adapter_count ?? 0}/{integrationStatus?.required_adapter_count ?? 6}</b></span>
          <span>进程内有效载荷<b>{integrationStatus?.resident_payload_count ?? 0}/{integrationStatus?.required_adapter_count ?? 6}</b></span>
          <span>模型字段合同<b>{integrationStatus?.required_field_count ?? 21} fields</b></span>
          <span>动态源时间差<b>{alignment?.observed_skew_seconds == null ? '--' : `${fmt(alignment.observed_skew_seconds, 0)}s / ${alignment.max_allowed_seconds}s`}</b></span>
        </div>
        <div className="runtime-shadow-adapters">
          {(integrationAdapters.length ? integrationAdapters : [
            { adapter_id: 'terminal_operating_system' },
            { adapter_id: 'energy_management_system' },
            { adapter_id: 'berth_and_vessel_feed' },
            { adapter_id: 'equipment_availability_feed' },
            { adapter_id: 'weather_and_navigation_feed' },
            { adapter_id: 'shore_power_compatibility_registry' },
          ]).map((item: Record<string, any>) => (
            <span key={item.adapter_id} className={item.resident_payload_ready ? 'ok' : 'blocked'}>
              <i />
              <b>{item.adapter_id}</b>
              <small>{item.resident_payload_ready ? `seq ${item.sequence} · ${shortHash(item.payload_sha256)}` : item.ready ? '摘要有效，等待源重发载荷' : '未接入或已过期'}</small>
            </span>
          ))}
        </div>
        {!shadowReady && (
          <p className="runtime-shadow-blocker"><CircleAlert size={13} />
            {integrationBlockerZh[firstIntegrationBlocker] ?? '必须启用影子模式、身份鉴权与审计，并接收六路新鲜签名报文。'}
          </p>
        )}
        <footer>
          原始业务值仅驻留当前进程；服务重启后六源必须重发。签名只证明来源与完整性，不代表计量校准、现场验收或生产授权。
        </footer>
      </section>

      <section className="runtime-live-section">
        <div className="runtime-section-title">
          <strong><Zap size={15} />连续能碳与设备状态</strong>
          <span>{snapshot?.snapshot_sha256 ? `snapshot ${shortHash(snapshot.snapshot_sha256)}` : '等待快照'}</span>
        </div>
        <div className="runtime-live-grid">
          {liveCards.map(([id, zh, en]) => {
            const item = signal(snapshot, id);
            return (
              <article key={id} className={item?.quality_status === '正常' || item?.quality_status === '插值' ? '' : 'warn'}>
                <span>{zh}<small>{en}</small></span>
                <b>{fmt(item?.value, id.includes('pct') || id.includes('temperature') ? 1 : 0)} <em>{item?.unit ?? '--'}</em></b>
                <i>{item?.source_type ?? '等待数据'} · {item?.quality_status ?? '--'}</i>
              </article>
            );
          })}
        </div>
      </section>

      <section className="runtime-model-section">
        <div className="runtime-section-title">
          <strong><ThermometerSun size={15} />当前输入因果预测</strong>
          <span>{forecast?.model?.model_id ?? '等待模型推理'}</span>
        </div>
        <div className="runtime-forecast-grid">
          {forecastPoints.length ? forecastPoints.map((point: Record<string, any>) => (
            <article key={point.horizon_hours}>
              <span>未来 {point.horizon_hours}h<small>{point.event_time}</small></span>
              <b>{fmt(point.predictions?.terminal_load_kw, 0)} kW</b>
              <em>区域负荷 {fmt(point.predictions?.regional_grid_demand_mw, 0)} MW</em>
              <em>电价 ¥{fmt(point.predictions?.electricity_price_cny_per_kwh, 3)}/kWh</em>
              <em>碳因子 {fmt(point.predictions?.grid_carbon_kg_per_kwh, 3)}</em>
            </article>
          )) : (
            <article className="runtime-empty"><CircleAlert size={15} /><b>预测失败关闭</b><em>先恢复模拟器与数据质量门禁</em></article>
          )}
          <article className="runtime-model-evidence">
            <span>模型证据<small>MODEL EVIDENCE</small></span>
            <em>模型 SHA-256 <b>{shortHash(forecast?.model?.model_sha256)}</b></em>
            <em>数据 SHA-256 <b>{shortHash(forecast?.model?.dataset_sha256)}</b></em>
            <em>分区 <b>Train → Validation → Test</b></em>
            <em>1h held-out 负荷 MAE <b>{fmt(forecast?.model?.held_out_test_mae_by_horizon?.['1']?.terminal_load_kw, 1)} kW</b></em>
            <em>推理窃取测试未来行 <b>{forecast?.model?.future_test_rows_accessed_during_inference ? 'YES · BLOCK' : 'NO'}</b></em>
            <em>边界 <b>终端负荷为工程派生目标</b></em>
          </article>
        </div>
      </section>

      <section className="runtime-decision-section">
        <div className="runtime-section-title">
          <strong><ShieldCheck size={15} />推荐→投影→审批→执行→回执</strong>
          <span className={`decision-status ${decisionStatus}`}>{decisionStatus}</span>
        </div>
        <div className="runtime-decision-flow">
          {[
            ['输入快照', decision?.input_snapshot?.snapshot_sha256 ? '完成' : '等待'],
            ['模型推理', decision?.forecast?.model_sha256 ? '完成' : '等待'],
            ['安全投影', decision?.safety_projection ? '完成' : '等待'],
            ['人工审批', requiredApprovals ? `${approvals.length}/${requiredApprovals}` : '等待'],
            ['模拟执行', receipt?.status ?? '等待'],
            ['KPI 回写', receipt?.result_snapshot_sha256 ? '完成' : '等待'],
            ['审计链', decision?.audit_events?.length ? `${decision.audit_events.length} events` : '等待'],
          ].map(([label, value], index) => (
            <span key={label}><i>{index + 1}</i><small>{label}</small><b>{value}</b></span>
          ))}
        </div>
        <div className="runtime-decision-grid">
          <article>
            <strong>推荐动作 / Recommended</strong>
            {Object.entries(recommendedAction).length ? Object.entries(recommendedAction).map(([key, value]) => <span key={key}>{key}<b>{fmt(value, 1)}</b></span>) : <em>点击“生成当前推荐”调用运行 MPC。</em>}
          </article>
          <article>
            <strong>安全投影后 / Projected</strong>
            {Object.entries(projectedAction).length ? Object.entries(projectedAction).map(([key, value]) => <span key={key}>{key}<b>{fmt(value, 1)}</b></span>) : <em>尚未生成投影结果。</em>}
            <small>触发约束 {decision?.safety_projection?.triggered_constraints?.length ?? 0} 条</small>
          </article>
          <article>
            <strong>执行回执 / Receipt</strong>
            <span>ACK<b>{receipt?.ack_id ? shortHash(receipt.ack_id) : '--'}</b></span>
            <span>模式<b>{receipt?.mode ?? 'simulation_only'}</b></span>
            <span>生产下发<b>FALSE</b></span>
            <span>失败原因<b>{receipt?.failure_reason ?? 'none'}</b></span>
          </article>
          <article>
            <strong>KPI 变化 / Delta</strong>
            <span>能耗<b>{fmt(kpiDelta.energy_kwh, 1)} kWh</b></span>
            <span>碳排<b>{fmt(kpiDelta.carbon_kg, 1)} kg</b></span>
            <span>成本<b>¥{fmt(kpiDelta.cost_cny, 1)}</b></span>
            <span>服务<b>{fmt(kpiDelta.service_fulfilment_pct, 2)} pp</b></span>
          </article>
        </div>
        <div className="runtime-actions decision-actions">
          <button id="btnRuntimeCreateDecision" type="button" disabled={busy || !snapshot?.decision_allowed} onClick={() => void onCreateDecision()}><Zap size={13} />生成当前推荐</button>
          <button id="btnRuntimeApproveSupervisor" type="button" disabled={busy || !decision || approvals.some((item: Record<string, any>) => item.approver_id === 'shift-supervisor')} onClick={() => void onApprove('shift-supervisor')}><CheckCircle2 size={13} />班组长审批</button>
          <button id="btnRuntimeApproveEnergyManager" type="button" disabled={busy || !decision || approvals.some((item: Record<string, any>) => item.approver_id === 'energy-duty-manager')} onClick={() => void onApprove('energy-duty-manager')}><CheckCircle2 size={13} />能源经理审批</button>
          <button id="btnRuntimeExecute" type="button" disabled={busy || decisionStatus !== 'approved'} onClick={() => void onExecute()}><Play size={13} />模拟执行</button>
          <button id="btnRuntimeRollback" type="button" disabled={busy || decisionStatus !== 'executed_simulation'} onClick={() => void onRollback()}><RotateCcw size={13} />回滚</button>
        </div>
      </section>

      <div className="runtime-bottom-grid">
        <section>
          <div className="runtime-section-title"><strong><Database size={15} />字段血缘与比例</strong><span>{lineage.length} fields</span></div>
          <div className="runtime-ratio-strip">
            <span>公开观测/实测锚点 <b>{fmt(classifications.measured, 1)}%</b></span>
            <span>物理/工程模拟 <b>{fmt(classifications.simulated, 1)}%</b></span>
            <span>工程派生 <b>{fmt(classifications.derived, 1)}%</b></span>
          </div>
          <div className="runtime-lineage-table">
            {lineage.map((item) => (
              <span key={item.field_id}>
                <b>{item.field_id}</b><em>{item.source_type}</em><small>{item.source_id}</small><i className={item.quality_status === '正常' || item.quality_status === '插值' ? 'ok' : 'warn'}>{item.quality_status} · {fmt(item.confidence * 100, 0)}%</i>
              </span>
            ))}
          </div>
        </section>
        <section>
          <div className="runtime-section-title"><strong><History size={15} />连续历史与异常注入</strong><span>{historyItems.length} recent steps</span></div>
          <div className="runtime-history-list">
            {historyItems.map((item: Record<string, any>) => (
              <span key={item.snapshot_sha256}><small>STEP {item.step}</small><b>{fmt(item.grid_import_kw / 1000, 2)} MW</b><em>SOC {fmt(item.battery_soc_pct, 1)}%</em><i>{item.scenario_id}</i></span>
            ))}
          </div>
          <div className="runtime-scenario-actions">
            {scenarioButtons.map(([id, label]) => <button id={`btnRuntimeScenario-${id}`} type="button" disabled={busy} key={id} onClick={() => void onInject(id)}>{label}</button>)}
          </div>
          <p><CircleAlert size={13} />需求响应与故障均是明确标注的工程事件，不是现场事故或真实结算记录。</p>
        </section>
      </div>

      <footer className="runtime-boundary-footer">
        <span>simulation_mode=<b>true</b></span>
        <span>live_data_verified=<b>false</b></span>
        <span>dispatch_allowed=<b>false</b></span>
        <span>production_authority=<b>false</b></span>
        <span>dataset=<b>{shortHash(snapshot?.dataset?.dataset_sha256)}</b></span>
      </footer>
    </div>
  );
}
