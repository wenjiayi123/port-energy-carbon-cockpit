import { useEffect, useMemo, useRef, useState } from 'react';
import type { WorkspaceId } from '../lib/workspaces';
import { CheckCircle2, ChevronDown, ChevronUp, CircleAlert, MapPin, Mic2, Play, RotateCcw, ShieldCheck, Sparkles, X } from 'lucide-react';

interface DemoGuideProps {
  openToken: number;
  onNavigate: (page: WorkspaceId) => void;
  onOpenXiaoyi: () => void;
  onPrepareCommand: (command: string) => void;
}

type DemoStepAction =
  | { kind: 'selector'; selector: string }
  | { kind: 'open-xiaoyi' }
  | { kind: 'prepare-command'; command: string };

interface DemoStepOptions {
  awaitReceipt?: boolean;
  readySelector?: string;
  cleanupSelector?: string;
  reopenXiaoyiAfterCleanup?: boolean;
  manualSelector?: string;
  timeoutMs?: number;
  recoveryEvent?: string;
}

interface DemoStep extends DemoStepOptions {
  id: string;
  phase: string;
  button: string;
  location: string;
  narration: string;
  wait: string;
  action: DemoStepAction;
}

const shorePowerCommand = '小鸥，开始训练岸电优先目标';
const defaultReceiptTimeoutMs = 15000;
const directClickAdvanceMs = 260;
const phases = ['01 可信数据与孪生', '02 舷鸥跨模块联动', '03 RL 训练与价值证据', '04 审批执行闭环'];

function selectorStep(
  id: string,
  phase: string,
  button: string,
  location: string,
  narration: string,
  wait: string,
  selector: string,
  options: DemoStepOptions = {},
): DemoStep {
  return { id, phase, button, location, narration, wait, action: { kind: 'selector', selector }, ...options };
}

const demoSteps: DemoStep[] = [
  selectorStep('twin-open', phases[0], '进入 3D 孪生大屏', '左侧工作空间', '先进入独立三维大屏，看清能源枢纽、电源和港区用能设备。空间模型为示意，所有功率来自连续模拟快照。', '三维能源场景与设备检查器打开。', 'nav a[href="#/twin"]', { awaitReceipt: true, readySelector: '.energy-twin' }),
  selectorStep('twin-battery', phases[0], '检查储能电池站', '三维大屏·设备清单', '选择储能，读取当前功率、荷电状态、健康状态与温度，并保留来源字段。', '检查器定位储能电池站。', '#btnTwinAsset-battery'),
  selectorStep('twin-heat', phases[0], '演示电池过温', '三维大屏·底栏', '注入工程过温场景，验证设备关注和质量门禁会同步改变。这里展示模拟异常，不代表现场事故。', '当前场景显示电池过温，风险列表给出温度关注。', '#btnTwinHeatScenario', { awaitReceipt: true, readySelector: '.energy-twin[data-scenario="battery_overtemperature"]', timeoutMs: 15000 }),
  selectorStep('twin-reset', phases[0], '恢复模拟', '三维大屏·底栏', '恢复正常模拟环境，再进入数据证据与调度流程。', '当前场景恢复 normal。', '#btnTwinResetScenario', { awaitReceipt: true, readySelector: '.energy-twin[data-scenario="normal"]', timeoutMs: 15000 }),
  selectorStep('trained-evidence',phases[0],'场景算法与数据清单','逐场景训练证据','逐个场景展示实际训练算法、数据集名字和数量、State状态、Reward奖励、Action动作与输出。公开观测、工程派生、训练失败和未准入候选按原始证据显示，并保留文件与哈希。','显示清单后可逐项切换核对。','[data-demo-evidence-open]',{awaitReceipt:true,readySelector:'.demo-evidence-panel[data-state="ready"]',cleanupSelector:'[data-de-close]',timeoutMs:10000}),
  selectorStep(
    'data-boundary', phases[0], 'DATA 数据边界', '中央数字孪生地图',
    '系统首先解决数据可信问题。这里把训练集、验证集、独立测试集和生产接口分开标识，公开数据校准的演示结果不会冒充现场实测。',
    '查看数据来源、数据分区与生产权限边界。', '#btnDataBoundary',
    { cleanupSelector: '#btnCloseBusinessAction' },
  ),
  selectorStep(
    'strategy-comparison', phases[0], '基线与优化对比', '作业轨迹·对比入口',
    '系统把调度方案与固定资源基线放在同一口径下比较，直接回答能耗、碳排、成本和安全约束究竟改善了多少。',
    '策略对比详情展开。', '#btnWorkspaceStrategyComparison',
    { cleanupSelector: '#btnCloseBusinessAction' },
  ),

  {
    id: 'open-xiaoyi', phase: phases[1], button: '舷鸥联动 / AI COPILOT', location: '全局工具栏·舷鸥助手',
    narration: '舷鸥不是聊天装饰。它把业务目标翻译、功能定位、RL 训练、人工审批和审计证据接成一条可操作的链。',
    wait: '舷鸥联动抽屉展开。', action: { kind: 'open-xiaoyi' }, manualSelector: '#btnOpenXiaoyi, .xiaoyi-orb',
  },
  selectorStep(
    'open-carbon', phases[1], '低碳 / Carbon', '舷鸥 · GullMate 决策面板',
    '我不需要在大屏中寻找功能，只需让舷鸥定位低碳面板。调度动作、碳价情景和排放影响随即联动展示。',
    '低碳决策面板打开。', '#btnXiaoyiOpenCarbonPanel',
    { awaitReceipt: true, readySelector: '#btnCloseTopPanel', cleanupSelector: '#btnCloseTopPanel', reopenXiaoyiAfterCleanup: true },
  ),
  selectorStep(
    'open-shore', phases[1], '岸电 / Shore', '舷鸥 · GullMate 决策面板',
    '再由舷鸥进入岸电联动：靠泊窗口、用电负荷和调度策略在同一面板协同，这正是稍后训练的业务目标。',
    '岸电联动面板打开。', '#btnXiaoyiOpenShorePanel',
    { awaitReceipt: true, readySelector: '#btnCloseTopPanel', cleanupSelector: '#btnCloseTopPanel', reopenXiaoyiAfterCleanup: true },
  ),

  {
    id: 'prepare-command', phase: phases[2], button: '填入“岸电优先目标”', location: '舷鸥指令输入框',
    narration: '现在直接用业务语言下达任务：“小鸥，开始训练岸电优先目标”。舷鸥会把这句话映射成数据、算法、奖励权重和安全护栏。',
    wait: `输入框显示“${shorePowerCommand}”。`, action: { kind: 'prepare-command', command: shorePowerCommand }, manualSelector: '#xiaoyiCommandInput',
  },
  selectorStep(
    'training-contract', phases[2], '训练契约 / MDP', 'RL 训练卡片',
    '训练前先打开契约：数据集为 43848 小时，State 106 维、Action 16 维，Reward 包含 17 项业务目标和约束。观众可以清楚看到策略看什么、改什么、如何得分。',
    '训练数据、State、Action、Reward 与安全护栏完整展开。', '#btnTrainingContract',
    { cleanupSelector: '#btnCloseTrainingContract' },
  ),
  selectorStep(
    'recognize', phases[2], '识别并执行 / Run', '舷鸥问答卡片',
    '舷鸥先识别训练意图，并明确将要调用的界面动作和人工确认要求；此时还没有启动训练。',
    '等待“确认执行”按钮出现。', '#btnXiaoyiRun',
    { awaitReceipt: true, readySelector: '#btnXiaoyiConfirm' },
  ),
  selectorStep(
    'confirm-intent', phases[2], '确认执行 / Confirm', '舷鸥问答卡片',
    '第一次确认后，舷鸥选择岸电优先目标、SAC 和 v6 数据。演示预设为320步真实训练，只核验链路；正式收敛与价值读取已封存的多种子评测。',
    '等待最终训练确认面板。', '#btnXiaoyiConfirm',
    { awaitReceipt: true, readySelector: '#btnStageConfirmTraining' },
  ),
  selectorStep(
    'confirm-training', phases[2], '确认无误，开始训练', 'RL 训练确认面板',
    '这是第二道人机门禁。确认已显示的320步演示参数后才创建真实离线训练任务；短程演示不构成收敛或收益证据，生产调度权限保持关闭。',
    '等待“训练任务已启动”回执。', '#btnStageConfirmTraining, #btnConfirmTraining',
    {
      awaitReceipt: true,
      readySelector: '#btnTrainingStartedClose',
      cleanupSelector: '#btnTrainingStartedClose',
      recoveryEvent: 'demo-guide:restore-training-confirm',
      timeoutMs: 30000,
    },
  ),
  selectorStep(
    'status', phases[2], '状态 / Status', 'RL 训练卡片',
    '宽版训练观测面板同时展示 step、进度、reward、entropy、Actor 与 Critic loss、成功率、采样速率和 ETA，避免状态栏太窄看不出变化。',
    '宽版训练状态面板展开。', '#btnTrainingStatus',
    { awaitReceipt: true, readySelector: '.training-status-modal', cleanupSelector: '#btnCloseTrainingStatus' },
  ),
  selectorStep(
    'history', phases[2], '历史收敛曲线 / Results', 'RL 训练卡片',
    '这里集中回答 RL 能优化什么：碳排最低、成本与碳排均衡、岸电优先、峰值负荷平滑和低风险试运行。每个目标都有历史曲线、业务价值和建议算法，并展示洛杉矶港、美国 EIA 与 EPA eGRID 官方来源。',
    '等待五个 RL 目标曲线、业务价值与官方数据源完整渲染。', '#btnTrainingHistory',
    { awaitReceipt: true, readySelector: '.objective-history-stage', cleanupSelector: '#btnCloseTrainingHistory', timeoutMs: 15000 },
  ),
  selectorStep(
    'dry-run', phases[2], '上线验证 / Dry-run', 'RL 训练卡片',
    '最后执行只读上线验证：核验制品、数据一致性和安全门禁，并生成 dry-run 审计记录。验证通过不等于获得生产授权。',
    '等待约束检查与 dry-run 回执。', '#btnVerifyPolicy', { awaitReceipt: true, readySelector: '.execution-state.completed', timeoutMs: 60000 },
  ),

  selectorStep(
    'open-runtime', phases[3], '实时 / Runtime', '舷鸥实时指令',
    '训练和验证之后，舷鸥把我们带入可审计的执行闭环。后续动作全部发生在实时模拟中，并保留人工审批。',
    '实时闭环面板打开。', '#btnXiaoyiOpenRuntimePanel',
    { awaitReceipt: true, readySelector: '#btnRuntimeRefresh' },
  ),
  selectorStep(
    'runtime-start', phases[3], '启动模拟', '实时闭环操作栏',
    '启动校准实时模拟器，让推荐基于持续变化的作业与能碳状态，而不是静态截图。',
    '模拟器进入 running。', '#btnRuntimeStart',
    { awaitReceipt: true, readySelector: '.runtime-closed-loop[data-runtime-state="running"][data-runtime-busy="false"]' },
  ),
  selectorStep(
    'runtime-decision', phases[3], '生成当前推荐', '实时决策卡片',
    '系统生成带理由、预期影响和风险评估的调度建议，但此时仍不能执行。',
    '推荐进入等待审批状态。', '#btnRuntimeCreateDecision',
    { awaitReceipt: true, readySelector: '.runtime-closed-loop[data-decision-state="awaiting_approval"][data-runtime-busy="false"]' },
  ),
  selectorStep(
    'runtime-supervisor', phases[3], '班组长审批', '实时决策卡片',
    '第一道人工门禁确认现场作业可行性，避免模型只优化能碳指标却破坏生产节奏。',
    '班组长审批写入审计链。', '#btnRuntimeApproveSupervisor',
    { awaitReceipt: true, readySelector: '.runtime-closed-loop[data-approvers~="shift-supervisor"][data-runtime-busy="false"]' },
  ),
  selectorStep(
    'runtime-energy', phases[3], '能源经理审批', '实时决策卡片',
    '第二道门禁确认负荷、电价和碳排影响。双人审批通过后，系统才允许模拟执行。',
    '决策状态变为 approved。', '#btnRuntimeApproveEnergyManager',
    { awaitReceipt: true, readySelector: '.runtime-closed-loop[data-decision-state="approved"][data-runtime-busy="false"]' },
  ),
  selectorStep(
    'runtime-execute', phases[3], '模拟执行', '实时决策卡片',
    '决策只在数字孪生中执行，界面同步展示状态变化、影响评估和审计记录。',
    '状态进入 executed simulation。', '#btnRuntimeExecute',
    { awaitReceipt: true, readySelector: '.runtime-closed-loop[data-decision-state="executed_simulation"][data-runtime-busy="false"]' },
  ),
  selectorStep(
    'runtime-rollback', phases[3], '回滚', '实时决策卡片',
    '最后演示可恢复性：系统依据完整审计记录回滚模拟动作，证明推荐、审批、执行和恢复都不是黑箱。',
    '回滚完成，完整闭环结束。', '#btnRuntimeRollback',
    { awaitReceipt: true, readySelector: '.runtime-closed-loop[data-decision-state="rolled_back_simulation"][data-runtime-busy="false"]', cleanupSelector: '#btnCloseTopPanel' },
  ),
];

function isRendered(element: HTMLElement) {
  const style = window.getComputedStyle(element);
  return style.display !== 'none' && style.visibility !== 'hidden' && element.getClientRects().length > 0;
}

function findTarget(selector: string) {
  const targets = Array.from(document.querySelectorAll<HTMLButtonElement>(selector));
  return targets.find((target) => !target.disabled && isRendered(target))
    ?? targets.find((target) => !target.disabled)
    ?? targets[0]
    ?? null;
}

function selectorExists(selector?: string) {
  if (!selector) return false;
  return Array.from(document.querySelectorAll<HTMLElement>(selector)).some((target) => {
    if (!isRendered(target)) return false;
    return !(target instanceof HTMLButtonElement) || !target.disabled;
  });
}

export function DemoGuide({ openToken, onOpenXiaoyi, onPrepareCommand, onNavigate }: DemoGuideProps) {
  const [open, setOpen] = useState(false);
  const [introOpen, setIntroOpen] = useState(true);
  const [collapsed, setCollapsed] = useState(false);
  const [activeIndex, setActiveIndex] = useState(0);
  const [completed, setCompleted] = useState<string[]>([]);
  const [stepExecuted, setStepExecuted] = useState(false);
  const [targetReady, setTargetReady] = useState(true);
  const [receiptWaiting, setReceiptWaiting] = useState(false);
  const [actionPending, setActionPending] = useState(false);
  const [timedOut, setTimedOut] = useState(false);
  const [notice, setNotice] = useState('点击当前步骤即可演示。');
  const highlightTimer = useRef<number | null>(null);
  const actionTimer = useRef<number | null>(null);
  const advanceTimer = useRef<number | null>(null);
  const receiptSawBusy = useRef(false);
  const receiptStartedAt = useRef(0);
  const receiptOrigin = useRef<'guide' | 'page'>('guide');
  const guideTriggeredClick = useRef(false);
  const recoveryTriggeredForStep = useRef('');

  const pendingRun = useRef<number | null>(null);
  const activeStep = demoSteps[activeIndex];
  const finished = activeIndex >= demoSteps.length;
  const progress = Math.round((completed.length / demoSteps.length) * 100);
  const activePhase = activeStep?.phase ?? phases[phases.length - 1];
  const phaseSteps = demoSteps.filter((step) => step.phase === activePhase);
  const currentPhaseIndex = Math.max(0, phases.indexOf(activePhase));

  useEffect(() => {
    if (openToken <= 0) return;
    setOpen(true);
    setIntroOpen(true);
    setCollapsed(false);
    setActiveIndex(0);
    setCompleted([]);
    setStepExecuted(false);
    setReceiptWaiting(false);
    setActionPending(false);
    setTimedOut(false);
    receiptSawBusy.current = false;
    setNotice('演示引导已就绪，先查看开场介绍。');
  }, [openToken]);

  useEffect(() => {
    if (!open || introOpen || collapsed || finished || !activeStep || actionPending) return;
    const check = () => {
      if (stepExecuted) {
        setTargetReady(true);
        return;
      }
      if (activeStep.action.kind !== 'selector') {
        setTargetReady(!receiptWaiting);
        return;
      }

      const target = findTarget(activeStep.action.selector);
      const ready = Boolean(target && !target.disabled);
      if (!receiptWaiting) {
        if (!ready && activeStep.recoveryEvent && recoveryTriggeredForStep.current !== activeStep.id) {
          recoveryTriggeredForStep.current = activeStep.id;
          window.dispatchEvent(new CustomEvent(activeStep.recoveryEvent, { detail: { stepId: activeStep.id, mode: 'auto' } }));
          setNotice('目标确认按钮已丢失，正在自动恢复当前确认面板…');
        }
        setTargetReady(ready || Boolean(activeStep.recoveryEvent));
        return;
      }

      const receiptElapsed = Date.now() - receiptStartedAt.current;
      const receiptTimeout = activeStep.timeoutMs ?? defaultReceiptTimeoutMs;
      if (!ready) receiptSawBusy.current = true;
      const visualReady = selectorExists(activeStep.readySelector);
      const settledAfterBusy = !activeStep.readySelector && ready && receiptSawBusy.current && receiptElapsed > 520;
      const explicitReceiptReady = visualReady && receiptElapsed > 180;
      if (settledAfterBusy || explicitReceiptReady) {
        setReceiptWaiting(false);
        setTimedOut(false);
        setNotice(receiptOrigin.current === 'page'
          ? '页面原按钮已同步，引导将进入下一步。'
          : '真实功能已完成，台词保持在本步。');
        completeCurrentStep(receiptOrigin.current);
        return;
      }
      if (receiptElapsed >= receiptTimeout) {
        setReceiptWaiting(false);
        setTimedOut(true);
        setTargetReady(true);
        setNotice(`超过 ${(receiptTimeout / 1000).toFixed(1)} 秒未收到回执，已自动解锁。可重试、重置或保底下一步。`);
        return;
      }
      setTargetReady(false);
    };
    check();
    const timer = window.setInterval(check, 320);
    return () => window.clearInterval(timer);
  }, [activeStep, actionPending, collapsed, finished, introOpen, open, receiptWaiting, stepExecuted]);

  useEffect(() => {
    recoveryTriggeredForStep.current = '';
  }, [activeStep?.id]);

  useEffect(() => {
    if (!open || introOpen || collapsed || finished || !activeStep || stepExecuted || receiptWaiting) return;
    const selector = activeStep.action.kind === 'selector'
      ? activeStep.action.selector
      : activeStep.manualSelector;
    if (!selector) return;

    const onPageClick = (event: MouseEvent) => {
      if (guideTriggeredClick.current) return;
      const eventTarget = event.target;
      if (!(eventTarget instanceof Element) || !eventTarget.closest(selector)) return;
      setTimedOut(false);
      setNotice(`已捕获页面原按钮：${activeStep.button}`);
      if (activeStep.awaitReceipt) {
        beginReceiptWait('page');
      } else {
        window.setTimeout(() => completeCurrentStep('page'), 120);
      }
    };

    const onPageInput = (event: Event) => {
      if (activeStep.id !== 'prepare-command') return;
      const eventTarget = event.target;
      if (!(eventTarget instanceof HTMLTextAreaElement) || !eventTarget.matches(selector)) return;
      if (eventTarget.value.trim() !== shorePowerCommand) return;
      setNotice('已捕获页面输入，引导将同步下一步。');
      window.setTimeout(() => completeCurrentStep('page'), 100);
    };

    document.addEventListener('click', onPageClick, true);
    document.addEventListener('input', onPageInput, true);
    return () => {
      document.removeEventListener('click', onPageClick, true);
      document.removeEventListener('input', onPageInput, true);
    };
  }, [activeStep, collapsed, finished, introOpen, open, receiptWaiting, stepExecuted]);

  useEffect(() => () => {
    if (highlightTimer.current !== null) window.clearTimeout(highlightTimer.current);
    if (actionTimer.current !== null) window.clearTimeout(actionTimer.current);
    if (advanceTimer.current !== null) window.clearTimeout(advanceTimer.current);
  }, []);

  useEffect(() => {
    if (!open || introOpen || !activeStep) return;
    if (activeStep.id === 'data-boundary' || activeStep.id === 'strategy-comparison') onNavigate('operations');
    if (activeStep.id === 'open-xiaoyi') onNavigate('overview');
  }, [open, introOpen, activeStep?.id]);

  useEffect(() => {
    if (finished && open) {
      pendingRun.current = null;
      window.dispatchEvent(new Event('demo-guide:complete'));
    }
  }, [finished, open]);

  const statusText = useMemo(() => {
    if (finished) return '演示闭环已完成';
    if (stepExecuted) return '本步已执行，台词保持显示；讲完后进入下一步';
    if (timedOut) return '回执超时已解锁，不会卡住演示';
    if (receiptWaiting) return '正在等待真实功能回执…';
    if (!targetReady) return '正在等待目标按钮就绪…';
    return `当前可点：${activeStep?.button ?? ''}`;
  }, [activeStep, finished, receiptWaiting, stepExecuted, targetReady, timedOut]);

  function clearActionTimers() {
    if (actionTimer.current !== null) window.clearTimeout(actionTimer.current);
    if (advanceTimer.current !== null) window.clearTimeout(advanceTimer.current);
    actionTimer.current = null;
    advanceTimer.current = null;
  }

  function beginReceiptWait(origin: 'guide' | 'page') {
    clearActionTimers();
    receiptOrigin.current = origin;
    receiptSawBusy.current = false;
    receiptStartedAt.current = Date.now();
    setReceiptWaiting(true);
    setTargetReady(false);
    setTimedOut(false);
  }

  function completeCurrentStep(origin: 'guide' | 'page' = 'guide') {
    if (!activeStep || finished) return;
    clearActionTimers();
    if (activeStep.id === 'confirm-intent') window.dispatchEvent(new Event('demo-guide:prepare-quick-training'));
    markCurrentStepExecuted();
    if (origin !== 'page') return;
    setNotice('页面原按钮已与引导同步，即将进入下一步。');
    advanceTimer.current = window.setTimeout(() => autoAdvanceCurrentStep(), directClickAdvanceMs);
  }

  function autoAdvanceCurrentStep() {
    if (!activeStep) return;
    const cleanup = activeStep.cleanupSelector ? findTarget(activeStep.cleanupSelector) : null;
    if (cleanup && !cleanup.disabled) cleanup.click();
    if (activeStep.reopenXiaoyiAfterCleanup) {
      window.setTimeout(onOpenXiaoyi, 100);
    }
    window.setTimeout(finishAdvance, cleanup ? 180 : 60);
  }

  function flashTarget(target: HTMLElement) {
    document.querySelectorAll('.demo-guide-target').forEach((element) => element.classList.remove('demo-guide-target'));
    target.scrollIntoView({ block: 'center', inline: 'nearest', behavior: 'auto' });
    target.classList.add('demo-guide-target');
    if (highlightTimer.current !== null) window.clearTimeout(highlightTimer.current);
    highlightTimer.current = window.setTimeout(() => target.classList.remove('demo-guide-target'), 650);
  }

  function markCurrentStepExecuted() {
    if (!activeStep) return;
    setCompleted((items) => items.includes(activeStep.id) ? items : [...items, activeStep.id]);
    setStepExecuted(true);
    setTargetReady(true);
    setActionPending(false);
  }

  function finishAdvance() {
    setStepExecuted(false);
    setReceiptWaiting(false);
    setActionPending(false);
    setTimedOut(false);
    receiptSawBusy.current = false;
    setActiveIndex((index) => index + 1);
    setNotice('已进入下一步，台词与按钮已同步。');
  }

  function advanceCurrentStep() {
    if (!activeStep || !stepExecuted) return;
    setStepExecuted(false);
    setActionPending(true);
    const cleanup = activeStep.cleanupSelector ? findTarget(activeStep.cleanupSelector) : null;
    if (cleanup && !cleanup.disabled) cleanup.click();

    const afterCleanup = () => {
      if (activeStep.reopenXiaoyiAfterCleanup) onOpenXiaoyi();
      if (activeStep.reopenXiaoyiAfterCleanup) {
        advanceTimer.current = window.setTimeout(finishAdvance, 180);
      } else {
        finishAdvance();
      }
    };

    if (cleanup) {
      setNotice('正在自动收起本步详情…');
      advanceTimer.current = window.setTimeout(afterCleanup, 180);
    } else {
      afterCleanup();
    }
  }

  function animateAction(onComplete: () => void) {
    if (actionTimer.current !== null) window.clearTimeout(actionTimer.current);
    setActionPending(true);
    actionTimer.current = window.setTimeout(() => {
      setActionPending(false);
      onComplete();
    }, 80);
  }

  function triggerSelectorStep(target: HTMLButtonElement) {
    if (!activeStep || activeStep.action.kind !== 'selector') return;
    flashTarget(target);
    guideTriggeredClick.current = true;
    target.click();
    window.queueMicrotask(() => { guideTriggeredClick.current = false; });
    setNotice(`已点击：${activeStep.button}`);
    if (activeStep.awaitReceipt) {
      beginReceiptWait('guide');
      return;
    }
    animateAction(markCurrentStepExecuted);
  }

  function runCurrentStep() {
    if (!activeStep || finished || pendingRun.current !== null) return;
    if (stepExecuted) {
      pendingRun.current = activeIndex + 1;
      window.dispatchEvent(new Event("demo-evidence-close"));
      advanceCurrentStep();
      return;
    }
    if (receiptWaiting || actionPending) return;

    if (activeStep.action.kind === 'open-xiaoyi') {
      onOpenXiaoyi();
      setNotice('已打开舷鸥联动中枢。');
      animateAction(markCurrentStepExecuted);
      return;
    }
    if (activeStep.action.kind === 'prepare-command') {
      onPrepareCommand(activeStep.action.command);
      setNotice('已填入岸电优先训练任务。');
      animateAction(markCurrentStepExecuted);
      return;
    }

    if (activeStep.id === 'confirm-training') {
      setActionPending(true);
      window.dispatchEvent(new Event('demo-guide:prepare-quick-training'));
      const selector = activeStep.action.selector;
      actionTimer.current = window.setTimeout(() => {
        setActionPending(false);
        const prepared = findTarget(selector);
        if (prepared && !prepared.disabled) triggerSelectorStep(prepared);
        else setNotice('训练确认入口尚未就绪，可重置本步恢复。');
      }, 100);
      return;
    }

    const target = findTarget(activeStep.action.selector);
    if (!target || target.disabled) {
      setTargetReady(false);
      if (activeStep.recoveryEvent) {
        const recoveryEvent = activeStep.recoveryEvent;
        const selector = activeStep.action.selector;
        setActionPending(true);
        setNotice('确认按钮已丢失，正在恢复并继续本步…');
        window.dispatchEvent(new CustomEvent(recoveryEvent, { detail: { stepId: activeStep.id, mode: 'click' } }));
        actionTimer.current = window.setTimeout(() => {
          setActionPending(false);
          const recoveredTarget = findTarget(selector);
          if (!recoveredTarget || recoveredTarget.disabled) {
            setNotice('确认面板恢复失败，可点击“重置本步”再次恢复。');
            return;
          }
          setTargetReady(true);
          triggerSelectorStep(recoveredTarget);
        }, 80);
        return;
      }
      setNotice('目标按钮还未就绪，请等待当前界面完成渲染。');
      return;
    }
    triggerSelectorStep(target);
  }

  useEffect(() => {
    if (pendingRun.current !== activeIndex || stepExecuted || finished) return;
    const timer=window.setTimeout(() => { pendingRun.current=null; runCurrentStep(); },220);
    return () => window.clearTimeout(timer);
  }, [activeIndex, stepExecuted, finished]);

  function retryCurrentStep() {
    clearActionTimers();
    setReceiptWaiting(false);
    setActionPending(false);
    setTimedOut(false);
    setTargetReady(activeStep?.action.kind !== 'selector' || Boolean(findTarget(activeStep.action.selector)));
    receiptSawBusy.current = false;
    recoveryTriggeredForStep.current = '';
    if (activeStep?.recoveryEvent) {
      window.dispatchEvent(new CustomEvent(activeStep.recoveryEvent, { detail: { stepId: activeStep.id, mode: 'retry' } }));
    }
    setNotice('本步已释放，可立即重试。');
  }

  function resetCurrentStep() {
    pendingRun.current = null;
    clearActionTimers();
    const cleanup = activeStep?.cleanupSelector ? findTarget(activeStep.cleanupSelector) : null;
    if (cleanup && !cleanup.disabled) cleanup.click();
    window.dispatchEvent(new CustomEvent('demo-guide:reset-action', { detail: { stepId: activeStep?.id ?? '', mode: 'retry' } }));
    setStepExecuted(false);
    setReceiptWaiting(false);
    setActionPending(false);
    setTimedOut(false);
    setTargetReady(true);
    receiptSawBusy.current = false;
    recoveryTriggeredForStep.current = '';
    if (activeStep?.recoveryEvent) {
      const recoveryEvent = activeStep.recoveryEvent;
      const stepId = activeStep.id;
      window.setTimeout(() => {
        window.dispatchEvent(new CustomEvent(recoveryEvent, { detail: { stepId, mode: 'retry' } }));
      }, 40);
    }
    setNotice('本步界面和等待状态已重置，所需面板会自动恢复。');
  }

  function forceNextStep() {
    if (!activeStep) return;
    clearActionTimers();
    setCompleted((items) => items.includes(activeStep.id) ? items : [...items, activeStep.id]);
    setNotice('已使用演示保底：跳过当前回执，继续下一步。');
    window.dispatchEvent(new CustomEvent('demo-guide:reset-action', { detail: { stepId: activeStep.id, mode: 'skip' } }));
    autoAdvanceCurrentStep();
  }

  function reset() {
    pendingRun.current = null;
    window.dispatchEvent(new Event("demo-evidence-close"));
    clearActionTimers();
    setActiveIndex(0);
    setCompleted([]);
    setStepExecuted(false);
    setReceiptWaiting(false);
    setActionPending(false);
    setTimedOut(false);
    receiptSawBusy.current = false;
    recoveryTriggeredForStep.current = '';
    window.dispatchEvent(new CustomEvent('demo-guide:reset-action', { detail: { stepId: 'all', mode: 'all' } }));
    setIntroOpen(true);
    setCollapsed(false);
    setNotice('已重置演示顺序。');
  }

  if (!open) return null;

  return (
    <aside data-demo-index={activeIndex} className={`demo-guide${collapsed ? ' is-collapsed' : ''}`} aria-label="全系统演示引导">
      <header className="demo-guide-head">
        <div><p><Play size={13} />演示引导 <small>CORE LOOP</small></p><h2>能碳·调度·RL 闭环</h2></div>
        <div className="demo-guide-head-actions">
          <button type="button" title="重置整个演示" aria-label="重置整个演示" onClick={reset}><RotateCcw size={15} /></button>
          <button type="button" title={collapsed ? '展开引导' : '收起引导'} aria-label={collapsed ? '展开引导' : '收起引导'} onClick={() => setCollapsed((value) => !value)}>{collapsed ? <ChevronDown size={16} /> : <ChevronUp size={16} />}</button>
          <button type="button" title="关闭引导" aria-label="关闭引导" onClick={() => setOpen(false)}><X size={16} /></button>
        </div>
      </header>

      {!collapsed && introOpen && (
        <section className="demo-guide-intro">
          <div><Sparkles size={24} /><span>PORT ENERGY × SCHEDULING × RL</span></div>
          <h3>开场介绍</h3>
          <p>本系统以 RL 为核心，联合优化港口能耗、碳排、岸电、峰值负荷、调度成本和安全约束，解决策略难训练、业务价值难量化、执行难追责的问题。</p>
          <p>本次演示将突出舷鸥如何接收业务目标、组装 RL 训练任务，再通过多目标历史曲线、官方数据源和独立测试指标证明系统能优化哪些业务。</p>
          <div className="demo-guide-boundary"><ShieldCheck size={15} /><span>离线 / 公开数据演示；生产调度下发始终关闭。</span></div>
          <button className="demo-guide-primary" type="button" onClick={() => { setIntroOpen(false); setNotice('从可信数据与数字孪生开始演示。'); }}><Play size={15} />开始核心闭环演示</button>
        </section>
      )}

      {!collapsed && !introOpen && (
        <>
          <div className="demo-guide-progress"><span><i style={{ width: `${progress}%` }} /></span><b>{completed.length}/{demoSteps.length}</b><small>{progress}%</small></div>
          {!finished && <div className="demo-guide-phase"><small>PHASE {currentPhaseIndex + 1}/{phases.length}</small><b>{activePhase}</b></div>}
          {finished ? (
            <section className="demo-guide-finished"><CheckCircle2 size={34} /><h3>核心演示闭环已完成</h3><p>可信数据、数字孪生、舷鸥联动、RL 训练证据、双人审批、模拟执行与回滚均已完成。</p><button type="button" onClick={reset}><RotateCcw size={14} />重新演示</button></section>
          ) : (
            <>
              <ol className="demo-guide-steps">
                {phaseSteps.map((step) => {
                  const index = demoSteps.findIndex((item) => item.id === step.id);
                  const done = completed.includes(step.id);
                  const current = index === activeIndex;
                  const className = `${current ? 'is-current ' : ''}${done ? 'is-done' : ''}`.trim();
                  return <li className={className} key={step.id}><button type="button" disabled={!current || receiptWaiting || (!stepExecuted && actionPending)} onClick={runCurrentStep}><i>{done ? <CheckCircle2 size={14} /> : index + 1}</i><span><b>{step.button}</b><small>{step.location}</small></span>{current && <em>{stepExecuted ? '已执行' : targetReady ? '可点击' : '等待中'}</em>}</button></li>;
                })}
              </ol>
              <button type="button" data-demo-evidence-open>场景算法与数据清单</button>
              <section className={`demo-guide-script${stepExecuted ? ' is-executed' : ''}`}><div><Mic2 size={15} /><span>{stepExecuted ? '保持本步台词' : '本步台词'}</span></div><p>{activeStep.narration}</p><small><MapPin size={12} />{activeStep.location}</small><small><CircleAlert size={12} />{stepExecuted ? '界面已完成变化；讲完本段后再进入下一步。' : activeStep.wait}</small></section>
              <button className={`demo-guide-primary${stepExecuted ? ' is-next' : ''}`} type="button" disabled={pendingRun.current !== null || (!stepExecuted && (!targetReady || receiptWaiting || actionPending))} onClick={runCurrentStep}>{stepExecuted ? <CheckCircle2 size={15} /> : <Play size={15} />}{stepExecuted ? (activeIndex === demoSteps.length - 1 ? '讲解完成，结束演示' : '下一步并演示') : receiptWaiting || actionPending ? '正在执行…' : `点击：${activeStep.button}`}</button>
              <div className={`demo-guide-recovery${timedOut ? ' is-timeout' : ''}`}>
                <button type="button" onClick={retryCurrentStep} disabled={stepExecuted}>重试本步</button>
                <button type="button" onClick={resetCurrentStep}>重置本步</button>
                <button type="button" onClick={forceNextStep}>保底下一步</button>
              </div>
              <div className={`demo-guide-notice${!targetReady && !stepExecuted ? ' is-waiting' : ''}`}>{statusText}<small>{notice}</small></div>
            </>
          )}
        </>
      )}
    </aside>
  );
}
