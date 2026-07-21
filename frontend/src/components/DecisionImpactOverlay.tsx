import {
  Activity,
  CheckCircle2,
  CircleAlert,
  Gauge,
  ShieldCheck,
  Sparkles,
  X,
  Zap,
} from 'lucide-react';

export interface DecisionImpactReport {
  id: string;
  autoCloseMs?: number;
  eyebrow: string;
  title: string;
  subtitle: string;
  algorithm: string;
  algorithmDetail: string;
  objective: string;
  scope: string;
  phases: Array<{ label: string; detail: string }>;
  actions: string[];
  risks: Array<{ level: 'guard' | 'watch'; label: string; detail: string }>;
  recommendations: string[];
  results: Array<{ label: string; value: string; detail?: string; tone?: 'green' | 'blue' | 'amber' }>;
}

export interface DecisionImpactState {
  report: DecisionImpactReport;
  phase: 'running' | 'done';
  progress: number;
  stageIndex: number;
  error?: string;
}

interface DecisionImpactOverlayProps {
  state: DecisionImpactState;
  onClose: () => void;
}

export function DecisionImpactOverlay({ state, onClose }: DecisionImpactOverlayProps) {
  const { report, phase, progress, stageIndex, error } = state;
  const activePhase = report.phases[Math.min(stageIndex, report.phases.length - 1)] ?? report.phases[0];

  if (phase === 'running') {
    return (
      <section className="decision-impact-layer running" aria-live="assertive" aria-label={`${report.title}计算中`}>
        <div className="decision-impact-scan" />
        <div className="decision-impact-orbit" aria-hidden="true">
          <i /><i /><i />
          <span><b>{Math.round(progress)}</b><small>%</small></span>
        </div>
        <div className="decision-impact-running-copy">
          <span><Sparkles size={15} />{report.eyebrow}</span>
          <h2>{report.title}</h2>
          <p>{activePhase?.detail ?? report.subtitle}</p>
          <div className="decision-impact-progress"><i style={{ width: `${progress}%` }} /></div>
          <div className="decision-impact-phase-rail">
            {report.phases.map((item, index) => (
              <span className={index < stageIndex ? 'complete' : index === stageIndex ? 'active' : ''} key={item.label}>
                <i>{index < stageIndex ? <CheckCircle2 size={13} /> : index + 1}</i>
                <b>{item.label}</b>
              </span>
            ))}
          </div>
          <div className="decision-impact-engine-strip">
            <span><Activity size={14} />策略引擎 <b>{report.algorithm}</b></span>
            <span><Gauge size={14} />优化目标 <b>{report.objective}</b></span>
            <span><Zap size={14} />作用对象 <b>{report.scope}</b></span>
          </div>
        </div>
      </section>
    );
  }

  return (
    <section className="decision-impact-layer done" aria-live="polite" aria-label={`${report.title}结果报告`}>
      <div className={`decision-impact-report ${error ? 'has-error' : ''}`}>
        <header>
          <div className="decision-impact-title-mark">
            {error ? <CircleAlert size={27} /> : <CheckCircle2 size={27} />}
          </div>
          <div>
            <span>{error ? 'EXECUTION EXCEPTION' : 'RL DECISION IMPACT REPORT'} · {report.eyebrow}</span>
            <h2>{error ? `${report.title}未完成` : report.title}</h2>
            <p>{error ?? report.subtitle}</p>
          </div>
          <button type="button" onClick={onClose} aria-label="关闭 RL 决策影响报告"><X size={20} /></button>
        </header>

        <div className="decision-impact-result-grid">
          {report.results.map((item) => (
            <article className={`tone-${item.tone ?? 'green'}`} key={item.label}>
              <small>{item.label}</small>
              <b>{item.value}</b>
              {item.detail && <span>{item.detail}</span>}
            </article>
          ))}
        </div>

        <div className="decision-impact-detail-grid">
          <article className="decision-impact-algorithm-card">
            <h3><Activity size={15} />使用的算法与目标</h3>
            <b>{report.algorithm}</b>
            <p>{report.algorithmDetail}</p>
            <span><Gauge size={13} />{report.objective}</span>
          </article>
          <article>
            <h3><Zap size={15} />执行行为</h3>
            <ul>{report.actions.map((item) => <li key={item}>{item}</li>)}</ul>
          </article>
          <article>
            <h3><ShieldCheck size={15} />风险与护栏</h3>
            <div className="decision-impact-risk-list">
              {report.risks.map((item) => (
                <span className={item.level} key={item.label}>
                  {item.level === 'guard' ? <CheckCircle2 size={13} /> : <CircleAlert size={13} />}
                  <b>{item.label}</b><small>{item.detail}</small>
                </span>
              ))}
            </div>
          </article>
          <article>
            <h3><Sparkles size={15} />值班建议</h3>
            <ul>{report.recommendations.map((item) => <li key={item}>{item}</li>)}</ul>
          </article>
        </div>

        <footer>
          <span><i />模型建议与生产执行保持分离</span>
          <b>{report.scope}</b>
          <button type="button" onClick={onClose}>确认已读 / CLOSE REPORT</button>
        </footer>
      </div>
    </section>
  );
}
