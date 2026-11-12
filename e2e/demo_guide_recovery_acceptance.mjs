import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const output = path.resolve(process.env.DEMO_GUIDE_AUDIT_OUTPUT || 'tmp/demo-guide-recovery');
await fs.mkdir(output, { recursive: true });

const browser = await chromium.launch({ headless: true, channel: process.env.BROWSER_CHANNEL || 'chrome' });
const context = await browser.newContext({ viewport: { width: 1600, height: 1000 } });
const page = await context.newPage();
page.setDefaultTimeout(15000);
const report = { recorded_at: new Date().toISOString(), pass: false, checks: [], page_errors: [] };
page.on('pageerror', (error) => report.page_errors.push(String(error)));

async function currentStep() {
  return page.locator('.demo-guide-steps li.is-current b').innerText();
}

try {
  await page.goto(process.env.UI_AUDIT_URL || 'http://127.0.0.1:5173/');
  await page.locator('#btnDemoGuideStart').waitFor({ timeout: 60000 });
  await page.locator('#btnDemoGuideStart').click();
  await page.locator('.demo-guide-intro .demo-guide-primary').click();
  assert.equal(await currentStep(), '进入 3D 孪生大屏');

  const fallback = page.getByRole('button', { name: '保底下一步', exact: true });
  // Recovery deliberately skips these seven preflight steps; the full acceptance suite executes them.
  for (let index = 0; index < 7; index += 1) {
    await fallback.click();
    await page.waitForFunction((expected) => Number(document.querySelector('.demo-guide')?.dataset.demoIndex) === expected, index + 1);
  }
  assert.equal(await currentStep(), '舷鸥联动 / AI COPILOT');
  report.checks.push({ name: '保底下一步不阻塞引导', pass: true });

  const started = Date.now();
  await page.locator('#btnOpenXiaoyi').click();
  await page.waitForFunction(() => document.querySelector('.demo-guide-steps li.is-current b')?.textContent?.includes('低碳'), null, { timeout: 3000 });
  const synchronized_ms = Date.now() - started;
  assert(synchronized_ms < 2200, `page-button synchronization took ${synchronized_ms} ms`);
  assert(await page.locator('.linkage-drawer').isVisible());
  report.checks.push({ name: '页面原按钮自动推进引导', pass: true, synchronized_ms });

  await page.getByRole('button', { name: '重置本步', exact: true }).click();
  assert.match(await page.locator('.demo-guide-notice').innerText(), /已重置/);
  assert.equal(await currentStep(), '低碳 / Carbon');
  report.checks.push({ name: '本步重置释放等待状态', pass: true });

  await page.locator('.demo-guide-head-actions button[aria-label="重置整个演示"]').click();
  assert(await page.locator('.demo-guide-intro').isVisible());
  report.checks.push({ name: '全局重置恢复开场', pass: true });

  await page.locator('.demo-guide-head-actions button[aria-label="关闭引导"]').click();
  if (!(await page.locator('.linkage-drawer').isVisible())) await page.locator('#btnOpenXiaoyi').click();
  await page.locator('#xiaoyiCommandInput').fill('小鸥，开始训练岸电优先目标');
  await page.locator('#btnXiaoyiRun:enabled').click();
  await page.locator('#btnXiaoyiConfirm:enabled').waitFor();
  const confirmStarted = Date.now();
  await page.locator('#btnXiaoyiConfirm').click();
  await page.locator('#btnStageConfirmTraining:enabled').waitFor({ timeout: 2800 });
  const confirm_response_ms = Date.now() - confirmStarted;
  assert(confirm_response_ms < 2200, `confirm response took ${confirm_response_ms} ms`);
  report.checks.push({ name: '确认执行快速打开训练确认面板', pass: true, confirm_response_ms });

  await page.getByRole('button', { name: '返回修改参数', exact: true }).click();
  await page.getByRole('button', { name: '关闭训练配置工作台', exact: true }).click();
  const historyStarted = Date.now();
  await page.locator('#btnTrainingHistory:enabled').click();
  await page.locator('.objective-history-stage').waitFor({ timeout: 2800 });
  const history_response_ms = Date.now() - historyStarted;
  const historyText = await page.locator('.training-history-modal').innerText();
  assert(history_response_ms < 2200, `history response took ${history_response_ms} ms`);
  for (const label of ['碳排最低', '成本·碳排均衡', '岸电优先', '峰值负荷平滑', '低风险试运行']) assert(historyText.includes(label), label);
  assert.match(historyText, /Port of Los Angeles|U\.S\. EIA|EPA eGRID/);
  report.checks.push({ name: '历史曲线与官方数据源快速展开', pass: true, history_response_ms });

  assert.equal(report.page_errors.length, 0, JSON.stringify(report.page_errors));
  report.pass = true;
  await page.screenshot({ path: path.join(output, 'demo-guide-recovery.png'), fullPage: true });
} catch (error) {
  report.error = String(error.stack || error);
  await page.screenshot({ path: path.join(output, 'failure.png'), fullPage: true }).catch(() => {});
  process.exitCode = 1;
} finally {
  await fs.writeFile(path.join(output, 'report.json'), JSON.stringify(report, null, 2));
  await browser.close();
}

console.log(JSON.stringify(report, null, 2));
