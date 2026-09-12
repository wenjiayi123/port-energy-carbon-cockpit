import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { mkdir, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import { tmpdir } from 'node:os';
const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_MODULE ?? 'playwright');
const baseUrl = process.env.COMPONENT_BASE_URL ?? 'http://127.0.0.1:5173';
const results = [];
const errors = [];
const browser = await chromium.launch({ channel: 'chrome', headless: true });
const page = await browser.newPage({ viewport: { width: 1600, height: 1100 } });
page.on('pageerror', error => errors.push(error.message));
let launchRequests = 0;
let trainingRequests = 0;
let actualExecutions = 0;
let launchRelease;
let executionRelease;
let trainingRelease;
let launchMode = 'deferred';
let xiaoyiOnline = false;
const asJson = (route, body, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });
await page.route('**/api/**', async route => {
  const path = new URL(route.request().url()).pathname;
  if (path === '/api/xiaoyi/launch') {
    launchRequests++;
    if (launchMode === 'deferred') return new Promise(resolve => { launchRelease = (body, status) => asJson(route, body, status).then(resolve); });
    return asJson(route, { result: { status: launchMode === 'starting' ? 'starting' : 'started' }, status: { base_url: 'mock://xiaoyi' } });
  }
  if (path === '/api/assistant/actions/execute') {
    const body = route.request().postDataJSON();
    if (body.dry_run) return asJson(route, {
      matched: true, action: { id: 'summarize_runtime_state', label: '总结实时态势' },
      will_execute: { button: { selector: '#btnXiaoyiRuntimeSummary', label: '实时态势摘要' } },
      human_confirmation: { required: false },
    });
    actualExecutions++;
    return new Promise(resolve => { executionRelease = (body, status = 200) => asJson(route, body, status).then(resolve); });
  }
  if (path === '/api/rl/train/start') {
    trainingRequests++;
    return new Promise(resolve => { trainingRelease = (body, status) => asJson(route, body, status).then(resolve); });
  }
  if (path === '/api/rl/train/status') return asJson(route, { status: 'idle', can_pause: false, can_resume: false, can_stop: false, logs: [] });
  if (path === '/api/linkage/health') return asJson(route, { summary: { runtime: '模拟器测试桩', xiaoyi: '测试桩', rl: '空闲', sailing: '测试桩' }, systems: { xiaoyi_ai: { online: xiaoyiOnline, ok: xiaoyiOnline } } });
  if (path === '/api/sailing/status') return asJson(route, { label: '隔离测试桩', process: { running: false } });
  if (path === '/api/rl/actions/registry') return asJson(route, { count: 30 });
  throw new Error(`Unmocked endpoint: ${path}`);
});
await page.route('**/__component_acceptance.html', route => route.fulfill({
  contentType: 'text/html', body: `<!doctype html><html><body><div id="root"></div><script type="module">
  import RefreshRuntime from '/@react-refresh';
  RefreshRuntime.injectIntoGlobalHook(window); window.$RefreshReg$ = () => {}; window.$RefreshSig$ = () => type => type; window.__vite_plugin_react_preamble_installed__ = true;
  const React = (await import('/node_modules/.vite/deps/react.js')).default;
  const { createRoot } = (await import('/node_modules/.vite/deps/react-dom_client.js')).default;
  const { XiaoyiLinkageHub } = await import('/src/components/XiaoyiLinkageHub.tsx');
  createRoot(document.getElementById('root')).render(React.createElement(XiaoyiLinkageHub, { onOpenTopPanel: async () => {} }));
  </script></body></html>`,
}));
const until = async (predicate, message, timeout = 12_000) => {
  const started = Date.now();
  while (!await predicate()) {
    if (Date.now() - started > timeout) throw new Error(`Timed out: ${message}`);
    await new Promise(resolve => setTimeout(resolve, 50));
  }
};
try {
  await page.goto(`${baseUrl}/__component_acceptance.html`);
  await page.locator('.xiaoyi-orb').click();
  await page.locator('#btnXiaoyiStart').evaluate(button => { button.click(); button.click(); });
  await until(() => launchRequests === 1, 'first launch');
  assert(await page.locator('#btnXiaoyiStart').isDisabled());
  await new Promise(resolve => setTimeout(resolve, 120));
  assert.equal(launchRequests, 1, 'synchronous duplicate click must dispatch once');
  await launchRelease({ detail: [{ loc: ['body', 'config'], msg: '隔离测试 422 参数错误', type: 'value_error' }] }, 422);
  await until(async () => (await page.locator('.xiaoyi-answer').innerText()).includes('隔离测试 422 参数错误'), '422 visible error');
  assert(await page.locator('#btnXiaoyiStart').isEnabled());
  assert((await page.locator('.execution-result-panel').innerText()).includes('执行失败'));
  results.push('PASS: direct button suppresses duplicate requests and recovers from structured HTTP 422');
  launchMode = 'success';
  await page.locator('#btnXiaoyiStart').click();
  await until(async () => (await page.locator('.xiaoyi-answer').innerText()).includes('mock://xiaoyi'), 'retry success');
  assert.equal(launchRequests, 2);
  results.push('PASS: failed action can be retried successfully without page reload');
  launchMode = 'starting';
  await page.locator('#btnXiaoyiStart').click();
  await until(async () => (await page.locator('.xiaoyi-answer').innerText()).includes('正在启动'), 'starting status');
  assert.equal(await page.locator('.execution-state').innerText(), 'RUNNING');
  xiaoyiOnline = true;
  await page.locator('.linkage-status-row button').click();
  await until(async () => (await page.locator('.execution-state').innerText()) === 'DONE', 'verified health online');
  assert((await page.locator('.execution-result-panel').innerText()).includes('健康检查已通过'));
  results.push('PASS: starting process stays RUNNING until a later health refresh verifies online');

  const runButton = page.getByRole('button', { name: '识别并执行 / Run', exact: true });
  await page.locator('.assistant-card textarea').fill('小懿，总结实时态势');
  await runButton.click();
  await until(() => actualExecutions === 1, 'slow mapped execution');
  await new Promise(resolve => setTimeout(resolve, 1_100));
  assert.equal(await page.locator('.xiaoyi-click-sequence .is-done').count(), 0);
  assert(await runButton.isDisabled());
  await executionRelease({ execution_result: { status: 'blocked', result: { status: 'blocked', reason: 'mock quality gate' } } });
  await until(async () => (await page.locator('.xiaoyi-answer').innerText()).includes('执行失败'), 'business failure');
  assert.equal(await page.locator('.xiaoyi-click-sequence .is-failed').count(), 1);
  assert.equal(await page.locator('.xiaoyi-click-sequence .is-done').count(), 0);
  assert(await runButton.isEnabled());
  results.push('PASS: slow automatic execution stays pending; HTTP-200 blocked receipt never becomes done');

  await page.locator('.assistant-card textarea').fill('小懿，再次总结实时态势');
  await runButton.click();
  await until(() => actualExecutions === 2, 'second mapped execution');
  await new Promise(resolve => setTimeout(resolve, 1_100));
  assert.equal(await page.locator('.xiaoyi-click-sequence .is-done').count(), 0);
  await executionRelease({ execution_result: { status: 'summarized', result: { summary: '慢接口真实返回已保留', current_kpis: { energy_kwh: 17, carbon_kg: 9, service_fulfilment_pct: 98 } } } });
  await until(async () => await page.locator('.xiaoyi-click-sequence .is-done').count() === 1, 'actual receipt marks done');
  assert((await page.locator('.xiaoyi-answer').innerText()).includes('慢接口真实返回已保留'));
  assert(!(await page.locator('.xiaoyi-answer').innerText()).includes('已完成 1 步联动'));
  results.push('PASS: automatic completion waits for actual response and preserves the returned answer');

  await page.locator('#btnOpenTrainingStudio').click();
  assert.equal(await page.locator('#trainingDataSelect').inputValue(), 'port_la_2020_2024_hybrid_rl_hourly');
  assert.equal(await page.locator('.studio-reward-grid input').count(), 17);
  assert.equal(await page.locator('#trainingAlgorithmSelect option[value=dqn]').evaluate(option => option.disabled), true);
  assert.equal(await page.locator('#trainingAlgorithmSelect option[value=dqn]').isDisabled(), true);
  assert.equal(await page.locator('#btnConfirmTraining').isDisabled(), true);
  await new Promise(resolve => setTimeout(resolve, 7_200));
  assert.equal(await page.locator('#trainingDataSelect').inputValue(), 'port_la_2020_2024_hybrid_rl_hourly');
  assert.equal(await page.locator('#trainingAlgorithmSelect option[value=dqn]').evaluate(option => option.disabled), true);
  assert.equal(await page.locator('#trainingAlgorithmSelect option[value=dqn]').isDisabled(), true);
  results.push('PASS: initial v6 locks DQN and 17 rewards; background polling preserves the editing draft');
  const totalSteps = page.locator('.training-param-grid label').filter({ hasText: '训练总步数' }).locator('input');
  const reviewButton = page.getByRole('button', { name: '生成确认面板', exact: true });
  await totalSteps.fill('1');
  await reviewButton.click();
  await until(async () => (await page.locator('.xiaoyi-answer').innerText()).includes('32–5,000,000'), 'range validation');
  assert.equal(trainingRequests, 0);
  await totalSteps.fill('32');
  await reviewButton.click();
  await until(async () => await page.locator('#btnStageConfirmTraining').isVisible(), 'valid training review');
  assert(await page.locator('#btnConfirmTraining').isEnabled());
  await totalSteps.fill('64');
  assert(await page.locator('#btnConfirmTraining').isDisabled());
  assert(await page.locator('#btnStageConfirmTraining').isDisabled());
  results.push('PASS: invalid training parameters never submit; editing a reviewed parameter invalidates both confirm buttons');
  await reviewButton.click();
  await until(async () => await page.locator('#btnStageConfirmTraining').isEnabled(), 'review regenerated');
  await page.locator('#btnStageConfirmTraining').evaluate(button => { button.click(); button.click(); });
  await until(() => trainingRequests === 1, 'single training mock request');
  assert(await page.locator('#btnConfirmTraining').isDisabled());
  await trainingRelease({ detail: '隔离训练启动失败' }, 422);
  await until(async () => (await page.locator('.xiaoyi-answer').innerText()).includes('隔离训练启动失败'), 'training failure recovery');
  assert.equal(await page.locator('.stage-modal-layer').count(), 0);
  assert(await page.locator('#btnConfirmTraining').isEnabled());
  assert.equal(trainingRequests, 1);
  results.push('PASS: training confirmation prevents duplicate submission and closes failed progress modal for retry');
  assert.deepEqual(errors, [], 'no uncaught page errors');
  const outputDir = join(tmpdir(), 'energy-component-acceptance');
  await mkdir(outputDir, { recursive: true });
  await writeFile(join(outputDir, 'results.json'), JSON.stringify({ mock_only: true, production_requests: 0, results, page_errors: errors }, null, 2));
  console.log(JSON.stringify({ status: 'passed', results, evidence: join(outputDir, 'results.json') }, null, 2));
} catch (error) {
  console.error(JSON.stringify({ page_errors: errors, body: await page.locator('body').innerText() }, null, 2));
  throw error;
} finally {
  await browser.close();
}
