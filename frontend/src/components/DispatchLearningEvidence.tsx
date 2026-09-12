import { useEffect, useRef, useState } from 'react';
import { fetchJson } from '../lib/api';

type SeedEvidence = {
  seed: number;
  admitted: boolean;
  converged: boolean;
  comparisons: Record<string, {
    changes: Record<string, number>;
    failed_checks: string[];
  }>;
};

type Evidence = {
  available: boolean;
  champion_status: string;
  test_window_count?: number;
  seed_results?: SeedEvidence[];
  champion?: SeedEvidence | null;
};

export function DispatchLearningEvidence() {
  const [evidence, setEvidence] = useState<Evidence | null>(null);
  const [busy, setBusy] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const requestRunningRef = useRef(false);
  const [receipt, setReceipt] = useState<string>('');
  const [error, setError] = useState('');

  async function refresh() {
    if (requestRunningRef.current) return;
    requestRunningRef.current = true;
    setRefreshing(true);
    setError('');
    try {
      setEvidence(await fetchJson('/api/rl/dispatch-v7/evidence'));
    } catch (err) {
      setEvidence(null);
      setError(err instanceof Error ? err.message : '读取训练证据失败');
    } finally {
      requestRunningRef.current = false;
      setRefreshing(false);
    }
  }

  useEffect(() => { void refresh(); }, []);

  async function replay() {
    if (requestRunningRef.current) return;
    requestRunningRef.current = true;
    setBusy(true);
    setReceipt('正在连续回放 72 小时，并核对切换前后的储能、队列和服务欠账…');
    setError('');
    try {
      const result = await fetchJson('/api/rl/dispatch-v7/replay-switch', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ start_index: 0 }),
      });

      const receipts = Array.isArray(result.switch_receipts) ? result.switch_receipts : [];
      const returnedToMpc = receipts.at(-1)?.to === 'causal_mpc';
      setReceipt(`${result.status === 'passed' ? '切换验证通过' : '切换被阻止'} · ${result.steps} 小时 · `
        + `状态连续 ${receipts.filter((item: { state_preserved: boolean }) => item.state_preserved).length}/${receipts.length}`
        + ` · 安全越界 ${result.summary?.safety_violations ?? '未知'} · ${returnedToMpc ? '已回退模型预测控制' : '未确认回退，检查切换回执'}`);
    } catch (err) {
      setReceipt('');
      setError(err instanceof Error ? err.message : '切换回放失败');
    } finally {
      requestRunningRef.current = false;
      setBusy(false);
    }
  }

  const admitted = evidence?.available && evidence.champion_status === 'admitted_offline';
  const number = (value?: number) => Number.isFinite(value) ? `${value!.toFixed(2)}%` : '—';

  return (
    <section className="algorithm-production-board dispatch-learning-evidence" aria-label="v7 训练收敛与业务收益">
      <header>
        <div>
          <span>v7 训练收敛与业务收益</span>
          <small>真实序列训练 · 服务约束 · 规则与学习收益分别核算</small>
        </div>
        <b>{admitted ? '已通过离线准入' : evidence?.available ? '候选策略未准入' : '等待完整训练证据'}</b>
      </header>
      <div className="algorithm-production-summary">
        <span>评估窗口<b>{evidence?.test_window_count ?? '—'}</b><small>公开数据校准场景，非现场经营收益</small></span>
        <span>学习算法<b>交叉熵策略搜索</b><small>5 项资源与储能决策，55 个学习系数</small></span>
        <span>切换范围<b>离线／影子策略合同</b><small>保留储能状态、排队与服务欠账；现场接入需重新标定验证</small></span>
        {(evidence?.seed_results ?? []).map((seed) => (
          <span key={seed.seed}>
            随机种子 {seed.seed}
            <b>{seed.converged ? '验证回报稳定' : '尚未稳定'} · {seed.admitted ? '通过' : '未通过'}</b>
            <small>相对相同保护的非学习策略费用降低 {number(seed.comparisons?.service_reference?.changes?.settled_cost_reduction_pct)}</small>
            <small>相对最优固定参数费用降低 {number(seed.comparisons?.validation_selected_static?.changes?.settled_cost_reduction_pct)}</small>
            <small>相对模型预测控制费用降低 {number(seed.comparisons?.causal_mpc?.changes?.settled_cost_reduction_pct)}</small>
          </span>
        ))}
      </div>
      <footer>
        <button type="button" onClick={() => void refresh()} disabled={busy || refreshing}>{refreshing ? '正在刷新 v7 训练证据…' : '刷新 v7 训练证据'}</button>
        <button type="button" onClick={() => void replay()} disabled={busy || refreshing || !admitted}>
          {busy ? '正在验证策略切换…' : '验证模型预测控制 → 学习策略 → 回退'}
        </button>
        <b>生产控制权限：关闭</b>
      </footer>
      {receipt && <p role="status">{receipt}</p>}
      {error && <p role="alert">{error}</p>}
    </section>
  );
}
