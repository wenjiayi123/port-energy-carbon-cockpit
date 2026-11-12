import { lazy, Suspense, useEffect, useState } from 'react';
import { ArrowRight, Box, Eye, Focus, Layers3, Maximize2, Minimize2, Minus, Pause, Play, Plus, RefreshCw, ShieldCheck, TriangleAlert, X, Zap } from 'lucide-react';
import type { RuntimeSnapshot } from './RuntimeClosedLoopPanel';
import type { WorkspaceId } from '../lib/workspaces';
import { signalNumber, sourceMix } from '../lib/presentationData';
import { twinAssets, assetIssues, type TwinAssetId } from '../lib/twinAssets';
import { n } from './EnergyWorkspace';
import type { SceneControl } from './EnergyTwinScene';
const Scene = lazy(() => import('./EnergyTwinScene'));
interface Props { snapshot: RuntimeSnapshot | null; history: Record<string, any> | null; busy: boolean; notice: string; onNavigate: (id: WorkspaceId) => void; onRefresh: () => void; onInject: (id: string) => void; onReset: () => void; }
export function EnergyTwin({ snapshot, history, busy, notice, onNavigate, onRefresh, onInject, onReset }: Props) {
  const [selected, setSelected] = useState<TwinAssetId>('grid');
  const [energy, setEnergy] = useState(true), [labels, setLabels] = useState(true), [motion, setMotion] = useState(!window.matchMedia('(prefers-reduced-motion: reduce)').matches);
  const [focused, setFocused] = useState(false), [view, setView] = useState<'energy' | 'carbon' | 'risk'>('energy');
  const [sceneKey, setSceneKey] = useState(0);
  const [control, setControl] = useState<SceneControl>({ view: 'overview', token: 0 });
  const asset = twinAssets.find((a) => a.id === selected)!;
  const get = (id: string) => signalNumber(snapshot?.signals, id);
  const value = get(asset.field), signal = snapshot?.signals[asset.field];
  const mix = sourceMix(snapshot?.signals);
  const issues = twinAssets.flatMap((a) => assetIssues(a, snapshot).map((message) => ({ id: a.id, name: a.name, message })));
  const critical = snapshot?.quality?.critical_reasons ?? [];
  const alerts = twinAssets.filter((a) => assetIssues(a, snapshot).length).map((a) => a.id);
  const activeFlows = twinAssets.filter((a) => { const v = get(a.field); return v !== undefined && Math.abs(v) > .01; }).map((a) => a.id);
  const histories: Record<string, any>[] = history?.items ?? [];
  const loads = histories.map((h) => Number(h.grid_import_kw)).filter(Number.isFinite);
  const max = Math.max(1, ...loads);
  const points = loads.map((v, i) => `${(i / Math.max(1, loads.length - 1)) * 280},${65 - v / max * 53}`).join(' ');
  function camera(view: SceneControl['view']) { setControl((c) => ({ view, token: c.token + 1 })); }
  useEffect(() => {
    if (!focused) return;
    const previous = document.activeElement as HTMLElement | null;
    const exit = document.querySelector<HTMLButtonElement>('#btnTwinExitFocus'); exit?.focus();
    const key = (event: KeyboardEvent) => { if (event.key === 'Escape') setFocused(false); if (event.key === 'Tab') { const items = Array.from(document.querySelectorAll<HTMLElement>('.energy-twin button, .energy-twin input, .energy-twin select')).filter((el) => !el.hasAttribute('disabled') && el.getClientRects().length > 0); const first = items[0], last = items[items.length - 1]; if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); } else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); } } };
    document.addEventListener('keydown', key); const old = document.body.style.overflow; document.body.style.overflow = 'hidden';
    return () => { document.removeEventListener('keydown', key); document.body.style.overflow = old; previous?.focus(); };
  }, [focused]);
  function navigate(id: WorkspaceId) { setFocused(false); onNavigate(id); }
  return <section className={`energy-twin ${focused ? 'is-focused' : ''}`} data-scenario={snapshot?.active_scenario?.scenario_id ?? "waiting"} aria-label="能碳三维孪生大屏" role={focused ? 'dialog' : undefined} aria-modal={focused || undefined}>
    <header className="twin-screen-header"><div><span><Box size={17}/> PORT DIGITAL TWIN</span><h2>港口能碳 · 三维运行态势</h2></div><div><span className="twin-source-pill"><i/>公开数据校准模拟</span><button id={focused ? 'btnTwinExitFocus' : 'btnTwinFocus'} type="button" onClick={() => setFocused(!focused)} aria-label={focused ? '退出沉浸大屏' : '进入沉浸大屏'}>{focused ? <Minimize2 size={16}/> : <Maximize2 size={16}/>}<span>{focused ? '退出大屏' : '沉浸大屏'}</span></button></div></header>
    <div className="twin-kpi-strip">{[
      ['电网输入', n(get('grid.import_power_kw') === undefined ? undefined : get('grid.import_power_kw')! / 1000, 2), 'MW'],
      ['光伏可用', n(get('solar.available_power_kw') === undefined ? undefined : get('solar.available_power_kw')! / 1000, 2), 'MW'],
      ['储能 SOC', n(get('battery.soc_pct')), '%'],
      ['本步碳排', n(get('kpi.step_carbon_kg') === undefined ? undefined : get('kpi.step_carbon_kg')! / 1000, 2), 'tCO₂e'],
      ['岸电接船', n(get('shore_power.connected_vessels'), 0), '艘'],
    ].map(([label, val, unit]) => <div key={label}><small>{label}</small><b>{val}<em>{unit}</em></b></div>)}</div>
    <div className="twin-main-layout"><div className="twin-scene-panel">
      <div className="twin-mode-tabs" role="group" aria-label="孪生分析视角">{[['energy', '能源流'], ['carbon', '低碳视角'], ['risk', '风险关注']].map(([id, label]) => <button type="button" aria-pressed={view === id} key={id} onClick={() => setView(id as typeof view)}>{label}{id === 'risk' && alerts.length > 0 && <i>{alerts.length}</i>}</button>)}</div>
      <Suspense fallback={<div className="twin-scene-loading">正在载入三维能源场景…</div>}><Scene key={sceneKey} selected={selected} onSelect={setSelected} energy={energy} reverseFlows={['grid', 'solar', ...((get('battery.power_kw') ?? 0) > 0 ? ['battery'] : [])] as TwinAssetId[]} labels={labels} animate={motion} alerts={alerts} activeFlows={activeFlows} control={control}/></Suspense>
      <div className="twin-scene-caption"><span>USLAX · ENERGY CAMPUS</span><b>{view === 'energy' ? '电源 → 能源枢纽 → 港口负荷' : view === 'carbon' ? '光伏优先 · 岸电协同 · 碳因子溯源' : '信号质量与设备关注阈值'}</b><small>设备组团示意 · 非现场测绘 / 电气单线图</small></div>
      <div className="twin-camera-controls" role="group" aria-label="三维相机控制"><button type="button" onClick={() => camera('overview')}>全港</button><button type="button" onClick={() => camera('top')}>俯视</button><button type="button" onClick={() => camera('energy')}>能源区</button><button type="button" onClick={() => camera('shore')}>岸电区</button><button type="button" aria-label="放大三维场景" onClick={() => camera('zoom-in')}><Plus size={14}/></button><button type="button" aria-label="缩小三维场景" onClick={() => camera('zoom-out')}><Minus size={14}/></button></div>
      <div className="twin-scene-bottom"><span>拖拽旋转 · 滚轮缩放 · 点选设备</span><span>STEP {snapshot?.step ?? '—'} · {snapshot?.simulator_state ?? '等待快照'}</span></div>
    </div>
    <aside className="twin-inspector"><div className="twin-inspector-heading"><span>设备检查器</span><small>ASSET INSPECTOR</small></div><div className="twin-asset-name"><i style={{ background: asset.color }}/><small>{asset.code}</small><h3>{asset.name}</h3><p>{asset.role}</p></div><div className="twin-asset-value"><strong>{n(value, 0)}<small>{asset.unit}</small></strong><span>{signal ? signal.quality_status : '等待信号'} · {signal?.source_type ?? '无来源'}</span></div>
      <dl className="twin-asset-readings">{asset.secondary.map(([label, id]) => <div key={id}><dt>{label}</dt><dd>{n(get(id))}<small>{snapshot?.signals[id]?.unit ?? ''}</small></dd></div>)}</dl>
      <button className="twin-inspect-focus" type="button" onClick={() => camera('focus')}><Focus size={15}/>定位所选设备</button>
      <div className="twin-asset-provenance"><b>数据依据</b><code>{asset.field}</code><span>{signal?.asset_id ?? '等待资产标识'} · {signal?.source_id ?? '等待来源'}</span><span>虚拟时间 {signal?.event_time ?? '—'}</span><small>设备模型代表聚合信号分组，模型数量不代表实物数量。</small></div>
      <button className="twin-primary-action" type="button" onClick={() => navigate(asset.destination)}>进入{asset.destination === 'shore' ? '岸电协同' : asset.destination === 'carbon' ? '能碳管理' : '调度与审批'}<ArrowRight size={15}/></button>
    </aside></div>
    <div className="twin-bottom-layout"><section className="twin-assets-panel"><div className="twin-small-heading"><b><Layers3 size={14}/>设备与图层</b><div><button type="button" aria-pressed={energy} onClick={() => setEnergy(!energy)}><Zap size={13}/>能流</button><button type="button" aria-pressed={labels} onClick={() => setLabels(!labels)}><Eye size={13}/>标注</button><button type="button" aria-pressed={motion} onClick={() => setMotion(!motion)}>{motion ? <Pause size={13}/> : <Play size={13}/>}动效</button></div></div><div className="twin-asset-list">{twinAssets.map((a) => <button id={`btnTwinAsset-${a.id}`} type="button" key={a.id} aria-pressed={selected === a.id} onClick={() => setSelected(a.id)}><i style={{ background: alerts.includes(a.id) ? '#ffb75e' : a.color }}/><b>{a.name}</b><span>{n(get(a.field), 0)} <small>kW</small></span></button>)}</div></section>
    <section className="twin-analysis-panel"><div className="twin-small-heading"><b>{view === 'energy' ? '电网输入 · 最近运行步' : view === 'carbon' ? '低碳供能与核算口径' : '当前运行关注'}</b><span>{view === 'energy' ? `${loads.length} STEPS` : view === 'carbon' ? 'CARBON' : `${issues.length + critical.length} ITEMS`}</span></div>
      {view === 'energy' ? <><svg viewBox="0 0 280 72" role="img" aria-label="最近运行步电网输入功率趋势"><path d="M0 20H280M0 45H280M0 68H280" stroke="#1b3b4d" fill="none"/><polyline points={points} fill="none" stroke="#56def1" strokeWidth="2"/></svg><span className="twin-analysis-note">电网 {n(mix?.gridPercent ?? undefined)}% · 光伏 {n(mix?.solarPercent ?? undefined)}% · 储能放电 {n(mix?.batteryPercent ?? undefined)}%<br/>储能充电 {n(mix?.charge, 0)} kW，单列为负荷</span></> : view === 'carbon' ? <div className="twin-carbon-readings"><span>电网碳因子 <b>{n(get('grid.carbon_factor_kg_per_kwh'), 3)} kgCO₂e/kWh</b></span><span>本步碳排 <b>{n(get('kpi.step_carbon_kg'), 0)} kgCO₂e</b></span><p>总量取运行模拟核算结果，不按模型外观分摊到设备。</p><button type="button" onClick={() => navigate('carbon')}>查看排放清单与核证 <ArrowRight size={13}/></button></div> : <div className="twin-risk-list">{!issues.length && !critical.length ? <p><ShieldCheck size={17}/>当前展示阈值内 · 质量门禁 {snapshot?.quality?.status ?? '等待'}<small>仅代表当前模拟快照，非设备安全认证。</small></p> : <>{critical.map((message: string) => <p key={message}><TriangleAlert size={14}/>{message}</p>)}{issues.map((item) => <button key={`${item.id}-${item.message}`} type="button" onClick={() => setSelected(item.id)}><TriangleAlert size={13}/>{item.name}：{item.message}</button>)}</>}</div>}
    </section></div>
    <div className="twin-action-receipt" role="status">{busy ? "正在同步运行快照…" : notice || "点选设备查看数据，或在底栏演示异常与恢复。"}</div>
    <footer className="twin-footer"><span><ShieldCheck size={13}/>模拟数据 · 生产控制关闭 · 快照 {snapshot?.snapshot_sha256?.slice(0, 12) ?? '—'}</span><div><button disabled={busy} type="button" onClick={onRefresh}><RefreshCw size={13}/>同步快照</button><button disabled={busy} id="btnTwinHeatScenario" type="button" onClick={() => { setView('risk'); setSelected('battery'); onInject('battery_overtemperature'); }}>演示电池过温</button><button disabled={busy} id="btnTwinResetScenario" type="button" onClick={onReset}>恢复模拟</button><button type="button" onClick={() => setSceneKey((k) => k + 1)}>重新载入场景</button>{focused && <button type="button" onClick={() => setFocused(false)}><X size={14}/>退出</button>}</div></footer>
  </section>;
}
