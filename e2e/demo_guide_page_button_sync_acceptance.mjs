import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const output = path.resolve(process.env.DEMO_GUIDE_AUDIT_OUTPUT || 'tmp/demo-guide-page-sync');
await fs.mkdir(output, { recursive: true });

const steps = [
  ['进入 3D 孪生大屏', 'nav a[href="#/twin"]', 'click'],
  ['检查储能电池站', '#btnTwinAsset-battery', 'click'],
  ['演示电池过温', '#btnTwinHeatScenario', 'click'],
  ['恢复模拟', '#btnTwinResetScenario', 'click'],
  ['场景算法与数据清单', '[data-demo-evidence-open]', 'click'],
  ['DATA 数据边界', '#btnDataBoundary', 'click'],
  ['基线与优化对比', '#btnWorkspaceStrategyComparison', 'click'],
  ['舷鸥联动 / AI COPILOT', '#btnOpenXiaoyi', 'click'],
  ['低碳 / Carbon', '#btnXiaoyiOpenCarbonPanel', 'click'],
  ['岸电 / Shore', '#btnXiaoyiOpenShorePanel', 'click'],
  ['填入“岸电优先目标”', '#xiaoyiCommandInput', 'fill'],
  ['训练契约 / MDP', '#btnTrainingContract', 'click'],
  ['识别并执行 / Run', '#btnXiaoyiRun', 'click'],
  ['确认执行 / Confirm', '#btnXiaoyiConfirm', 'click'],
  ['确认无误，开始训练', '#btnStageConfirmTraining', 'click'],
  ['状态 / Status', '#btnTrainingStatus', 'click'],
  ['历史收敛曲线 / Results', '#btnTrainingHistory', 'click'],
  ['上线验证 / Dry-run', '#btnVerifyPolicy', 'click'],
  ['实时 / Runtime', '#btnXiaoyiOpenRuntimePanel', 'click'],
  ['启动模拟', '#btnRuntimeStart', 'click'],
  ['生成当前推荐', '#btnRuntimeCreateDecision', 'click'],
  ['班组长审批', '#btnRuntimeApproveSupervisor', 'click'],
  ['能源经理审批', '#btnRuntimeApproveEnergyManager', 'click'],
  ['模拟执行', '#btnRuntimeExecute', 'click'],
  ['回滚', '#btnRuntimeRollback', 'click'],
];

const browser = await chromium.launch({ headless: true, channel: process.env.BROWSER_CHANNEL || 'chrome' });
const context = await browser.newContext({ viewport: { width: 1800, height: 1080 } });
const page = await context.newPage();
page.setDefaultTimeout(15000);
const report = { recorded_at: new Date().toISOString(), pass: false, steps: [], page_errors: [], console_errors: [] };
page.on('pageerror', (error) => report.page_errors.push(String(error)));
page.on('console', (message) => { if (message.type() === 'error') report.console_errors.push(message.text()); });

await page.route('**/api/rl/train/start', async (route) => {
  if (route.request().method() !== 'POST') return route.continue();
  await route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ ok: true, result: { status: 'running', task_id: 'page-sync-acceptance', policy_version: 'shore-power-sac-demo', current_step: 1, total_steps: 200000 } }),
  });
});

async function currentStep() {
  return page.locator('.demo-guide-steps li.is-current b').innerText();
}

try {
  await page.goto(process.env.UI_AUDIT_URL || 'http://127.0.0.1:5173/');
  await page.locator('#btnDemoGuideStart').waitFor({ timeout: 60000 });
  await page.locator('#btnDemoGuideStart').click();
  await page.locator('.demo-guide-intro .demo-guide-primary').click();

  for (let index = 0; index < steps.length; index += 1) {
    const [label, selector, action] = steps[index];
    assert.equal(await currentStep(), label, `guide was not aligned before ${label}`);
    const target = page.locator(selector).filter({ visible: true }).first();
    await target.waitFor({ state: 'visible', timeout: 5000 });
    const started = Date.now();
    if (action === 'fill') {
      await target.fill('小鸥，开始训练岸电优先目标');
    } else {
      await target.click();
    }

    if (index < steps.length - 1) {
      const nextLabel = steps[index + 1][0];
      await page.waitForFunction(
        (expected) => document.querySelector('.demo-guide-steps li.is-current b')?.textContent?.trim() === expected,
        nextLabel,
        { timeout: 5200 },
      );
    } else {
      await page.locator('.demo-guide-finished').waitFor({ timeout: 5200 });
    }
    report.steps.push({ index: index + 1, button: label, pass: true, sync_ms: Date.now() - started });
  }

  assert.equal(report.page_errors.length, 0, JSON.stringify(report.page_errors));
  assert.equal(report.console_errors.length, 0, JSON.stringify(report.console_errors));
  report.pass = true;
  await page.screenshot({ path: path.join(output, 'page-button-sync-complete.png'), fullPage: true });
} catch (error) {
  report.error = String(error.stack || error);
  report.failed_step = await currentStep().catch(() => 'unknown');
  await page.screenshot({ path: path.join(output, 'failure.png'), fullPage: true }).catch(() => {});
  process.exitCode = 1;
} finally {
  await fs.writeFile(path.join(output, 'report.json'), JSON.stringify(report, null, 2));
  await browser.close();
}

console.log(JSON.stringify(report, null, 2));
