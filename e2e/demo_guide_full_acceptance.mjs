import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const output = path.resolve(process.env.DEMO_GUIDE_AUDIT_OUTPUT || 'tmp/demo-guide-full');
await fs.mkdir(output, { recursive: true });

const expectedSteps = [
  '进入 3D 孪生大屏',
  '检查储能电池站',
  '演示电池过温',
  '恢复模拟',
  '场景算法与数据清单',
  'DATA 数据边界',
  '基线与优化对比',
  '舷鸥联动 / AI COPILOT',
  '低碳 / Carbon',
  '岸电 / Shore',
  '填入“岸电优先目标”',
  '训练契约 / MDP',
  '识别并执行 / Run',
  '确认执行 / Confirm',
  '确认无误，开始训练',
  '状态 / Status',
  '历史收敛曲线 / Results',
  '上线验证 / Dry-run',
  '实时 / Runtime',
  '启动模拟',
  '生成当前推荐',
  '班组长审批',
  '能源经理审批',
  '模拟执行',
  '回滚',
];

const browser = await chromium.launch({ headless: true, channel: process.env.BROWSER_CHANNEL || 'chrome' });
const context = await browser.newContext({ viewport: { width: 1800, height: 1080 } });
const page = await context.newPage();
page.setDefaultTimeout(15000);
const report = {
  recorded_at: new Date().toISOString(),
  pass: false,
  steps: [],
  recovery: null,
  guide_open_history_requests: null,
  page_errors: [],
  console_errors: [],
};
let historyRequests = 0;

page.on('pageerror', (error) => report.page_errors.push(String(error)));
page.on('console', (message) => {
  if (message.type() === 'error') report.console_errors.push(message.text());
});
page.on('request', (request) => {
  if (new URL(request.url()).pathname === '/api/rl/training/history') historyRequests += 1;
});

// The UI click path is the subject of this acceptance run. Stub only the
// expensive learner launch so the audit cannot leave an additional learner process
// behind; backend training endpoints are covered by their own integration tests.
await page.route('**/api/rl/train/start', async (route) => {
  if (route.request().method() !== 'POST') return route.continue();
  await route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      ok: true,
      result: {
        status: 'running',
        task_id: 'demo-guide-ui-acceptance',
        policy_version: 'shore-power-sac-demo',
        current_step: 1,
        total_steps: 320,
      },
    }),
  });
});

async function currentStep() {
  return page.locator('.demo-guide-steps li.is-current b').innerText();
}

async function waitForExecuted() {
  await page.locator('.demo-guide-script.is-executed').waitFor({ state: 'visible', timeout: 5000 });
  const notice = await page.locator('.demo-guide-notice').innerText();
  assert(!notice.includes('回执超时'), `step used timeout fallback: ${notice}`);
}

try {
  await page.goto(process.env.UI_AUDIT_URL || 'http://127.0.0.1:5173/');
  await page.locator('#btnDemoGuideStart').waitFor({ timeout: 60000 });
  await page.locator('#btnDemoGuideStart').click();
  await page.waitForTimeout(250);
  report.guide_open_history_requests = historyRequests;
  assert.equal(historyRequests, 0, 'opening the guide must not preload training history');
  await page.locator('.demo-guide-intro .demo-guide-primary').click();

  for (let index = 0; index < expectedSteps.length; index += 1) {
    const expected = expectedSteps[index];
    if (index === 0) assert.equal(await currentStep(), expected, 'unexpected first guide step');

    let recoveryStarted = null;
    if (expected === '确认无误，开始训练') {
      await page.getByRole('button', { name: '返回修改参数', exact: true }).click();
      recoveryStarted = Date.now();
    }

    const started = Date.now();
    await page.locator('.demo-guide > .demo-guide-primary').click();
    await page.waitForFunction(
      (label) => document.querySelector('.demo-guide-steps li.is-current b')?.textContent?.trim() === label,
      expected,
      { timeout: 3000 },
    );
    await waitForExecuted();
    const responseMs = Date.now() - started;
    if (recoveryStarted !== null) {
      report.recovery = {
        name: '训练确认弹窗丢失后单击恢复并继续',
        pass: true,
        recovery_ms: Date.now() - recoveryStarted,
      };
    }
    assert(responseMs < 4500, `${expected} took ${responseMs} ms`);
    report.steps.push({ index: index + 1, button: expected, pass: true, response_ms: responseMs });
    if (expected === '历史收敛曲线 / Results') {
      assert.equal(await page.locator('.demo-guide-result-toast').count(), 0, 'blocking result toast must not exist');
      assert.equal(await page.locator('.demo-guide-result-surface').count(), 0, 'full-screen result highlight must not exist');
      await page.screenshot({ path: path.join(output, 'history-lightweight-guide.png'), fullPage: true });
    }


  }

  await page.locator('.demo-guide > .demo-guide-primary').click();
  await page.locator('.demo-guide-finished').waitFor({ timeout: 3000 });
  assert.match(await page.locator('.demo-guide-finished').innerText(), /核心演示闭环已完成/);
  assert.equal(await page.locator('.stage-modal-layer.confirm').count(), 0, 'completed guide must not reopen old training confirmation');
  assert.equal(await page.locator('.training-studio-layer').count(), 0, 'completed guide must close presentation-only training surfaces');
  assert.equal(report.page_errors.length, 0, JSON.stringify(report.page_errors));
  assert.equal(report.console_errors.length, 0, JSON.stringify(report.console_errors));
  report.pass = true;
  await page.screenshot({ path: path.join(output, 'demo-guide-full-complete.png'), fullPage: true });
} catch (error) {
  report.error = String(error.stack || error);
  report.failed_step = await currentStep().catch(() => 'unknown');
  report.notice = await page.locator('.demo-guide-notice').innerText().catch(() => 'unavailable');
  await page.screenshot({ path: path.join(output, 'failure.png'), fullPage: true }).catch(() => {});
  process.exitCode = 1;
} finally {
  await fs.writeFile(path.join(output, 'report.json'), JSON.stringify(report, null, 2));
  await browser.close();
}

console.log(JSON.stringify(report, null, 2));
