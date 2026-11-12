import { ArrowRight, Box, Bot, Cable, ChartNoAxesCombined, ChevronRight, Database, FlaskConical, LayoutDashboard, Leaf, Play, ShieldCheck, Waves, Zap } from 'lucide-react';
import type { ReactNode } from 'react';
import { workspaces, type WorkspaceId } from '../lib/workspaces';
import { signalNumber, sourceMix } from '../lib/presentationData';
import type { RuntimeSnapshot } from './RuntimeClosedLoopPanel';
import type { DashboardSnapshot } from '../types/dashboard';
const icons = { overview: LayoutDashboard, twin: Box, runtime: Zap, operations: Waves, simulation: FlaskConical, carbon: Leaf, shore: Cable, marl: ChartNoAxesCombined, api: Database };
export function n(value: number | undefined, digits = 1) { return value === undefined || !Number.isFinite(value) ? '—' : (Math.abs(value) < 0.5 * 10 ** -digits ? 0 : value).toLocaleString('zh-CN', { maximumFractionDigits: digits }); }
export function EnergyWorkspace({ page, runtime, onNavigate, onDemo, onXiaoyi, children }: { page: WorkspaceId; runtime: RuntimeSnapshot | null; onNavigate: (id: WorkspaceId) => void; onDemo: () => void; onXiaoyi: () => void; children: ReactNode }) {
  const meta = workspaces.find((item) => item.id === page)!;
  return <div className={`energy-workspace workspace-${page}`}>
    <aside className="workspace-sidebar">
      <a className="workspace-brand" href="#/overview"><span><Zap size={21}/></span><div>CARBON<span>OPS</span><small>港口能碳智能工作台</small></div></a>
      <nav aria-label="能碳工作空间">{['态势与运行', '业务工作台', '分析与治理'].map((group) => <div className="workspace-nav-group" key={group}><small>{group}</small>{workspaces.filter((item) => item.group === group).map((item) => { const Icon = icons[item.id]; return <a key={item.id} href={`#/${item.id}`} onClick={(event) => { event.preventDefault(); onNavigate(item.id); }} title={item.title} aria-label={item.title} aria-current={page === item.id ? 'page' : undefined}><Icon size={17}/><em>{({ overview: "总览", twin: "孪生", runtime: "调度", shore: "岸电", carbon: "能碳", operations: "作业", simulation: "推演", marl: "策略", api: "数据" })[item.id]}</em><span>{item.title}<small>{item.en}</small></span>{page === item.id && <ChevronRight size={13}/>}</a>; })}</div>)}</nav>
      <div className="workspace-sidebar-foot"><ShieldCheck size={17}/><span>公开数据校准模拟<small>生产控制关闭 · 研发者 温家懿</small></span></div>
    </aside>
    <div className="workspace-body">
      <header className="workspace-header"><div><small>CARBONOPS / {meta.en}</small><h1>{meta.title}</h1></div><div className="workspace-header-actions"><span className={`workspace-runtime-dot ${runtime?.decision_allowed ? 'ready' : ''}`}><i/>{runtime ? runtime.simulator_state === 'running' ? '模拟运行中' : '模拟已停止' : '数据连接中'}</span><button id="btnDataDesk" type="button" aria-label="打开数据齐备检查" title="数据清单与质量" onClick={() => document.querySelector<HTMLButtonElement>(".sdd-launcher")?.click()}><Database size={16}/></button><button id="btnOpenXiaoyi" type="button" onClick={onXiaoyi}><Bot size={16}/><span>舷鸥助手</span></button><button id="btnDemoGuideStart" type="button" onClick={onDemo}><Play size={14}/><span>演示开始</span></button></div></header>
      <div className="workspace-description">{meta.description}<span>SIMULATION WORKSPACE</span></div>
      <div className="workspace-content">{children}</div>
    </div>
  </div>;
}
export function EnergyOverview({ runtime, snapshot, decision, onNavigate }: { runtime: RuntimeSnapshot | null; snapshot: DashboardSnapshot | null; decision: Record<string, any> | null; onNavigate: (id: WorkspaceId) => void }) {
  const signals = runtime?.signals;
  const mix = sourceMix(signals);
  const get = (id: string) => signalNumber(signals, id);
  const qualityIssues = runtime?.quality?.critical_reasons ?? [];
  const status = String(decision?.status ?? 'none');
  const statusLabel: Record<string, string> = { none: '尚未生成建议', awaiting_approval: '建议待双人审批', approved: '已审批 · 待模拟执行', executed_simulation: '已执行 · 可核对回执', rolled_back: '已回滚 · 可重新评估', rolled_back_simulation: '已回滚 · 可重新评估' };
  return <div className="energy-overview">
    <section className="overview-hero"><div><small>PORT ENERGY INTELLIGENCE</small><h2>看清能源流向，<br/>让每一步调度有据可依。</h2><p>电网、光伏、储能与港口负荷协同运行。<br/>从空间态势发现问题，进入业务工作台处理。</p><button type="button" onClick={() => onNavigate('twin')}>进入 3D 孪生大屏 <ArrowRight size={17}/></button></div><div className="overview-energy-orbit" aria-hidden="true"><i/><i/><i/><Zap/><span>ENERGY<br/><b>CONNECTED</b></span><small>GRID / SOLAR / STORAGE</small></div></section>
    <div className="overview-metrics">{[
      ['电网输入', n(get('grid.import_power_kw') === undefined ? undefined : get('grid.import_power_kw')! / 1000, 2), 'MW', '当前模拟功率', 'runtime'],
      ['清洁供能占比', n(mix?.solarPercent ?? undefined), '%', '光伏 / 当前总供能', 'twin'],
      ['储能荷电状态', n(get('battery.soc_pct')), '%', 'SOC · 当前模拟状态', 'twin'],
      ['本步碳排放', n(get('kpi.step_carbon_kg') === undefined ? undefined : get('kpi.step_carbon_kg')! / 1000, 2), 'tCO₂e', '当前模拟步 · 非日累计', 'carbon'],
    ].map(([title, value, unit, note, route]) => <button key={title} type="button" onClick={() => onNavigate(route as WorkspaceId)}><small>{title}<ArrowRight size={14}/></small><strong>{value}<em>{unit}</em></strong><span>{note}</span></button>)}</div>
    <div className="overview-lower"><section className="workspace-card"><div className="workspace-card-heading"><h3>当前需要关注</h3><span>RUNNING TASKS</span></div><button className="overview-task" type="button" onClick={() => onNavigate('runtime')}><span className="task-index">01</span><div><b>{qualityIssues.length ? '数据质量门禁阻断' : statusLabel[status] ?? status}</b><p>{qualityIssues.length ? qualityIssues.join('、') : '生成建议 → 班组长审批 → 能源经理审批 → 模拟执行 → 回执 / 回滚'}</p></div><ArrowRight size={18}/></button><button className="overview-task" type="button" onClick={() => onNavigate('api')}><span className="task-index">02</span><div><b>现场接入与核证仍待完成</b><p>当前为公开数据校准模拟。接入来源、签名与核证资料可在数据工作台逐项查看。</p></div><ArrowRight size={18}/></button><footer className="overview-source">运行快照 STEP {runtime?.step ?? '—'} · {runtime?.virtual_event_time ?? '等待来源'}<br/>离线测试集 {snapshot?.scenario_id ?? '等待数据'} · 与连续运行模拟分开计算</footer></section>
    <section className="workspace-card"><div className="workspace-card-heading"><h3>按任务进入</h3><span>WORKSPACES</span></div><div className="overview-task-grid">{[
      ['shore', '岸电协同', '看靠泊窗口与负荷约束'], ['carbon', '能碳管理', '看排放来源与核证资料'], ['marl', '策略与训练', '训练、验证与准入证据'], ['operations', '作业轨迹', '看独立测试集的动作回放'],
    ].map(([id, title, text]) => <button type="button" key={id} onClick={() => onNavigate(id as WorkspaceId)}><b>{title}<ArrowRight size={14}/></b><span>{text}</span></button>)}</div></section></div>
  </div>;
}
