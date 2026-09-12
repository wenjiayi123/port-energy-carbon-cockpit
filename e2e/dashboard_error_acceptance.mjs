import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import { createRequire } from 'node:module';

// Exercise recoverable API failures and out-of-order responses in a real browser.
// Only the read-only dashboard recomputation response is intercepted.
const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const output = path.resolve(process.env.UI_AUDIT_OUTPUT || 'tmp/ui-audit-2026-09-12');
const baseUrl = process.env.UI_AUDIT_URL || 'http://127.0.0.1:5173/';
await fs.mkdir(output, { recursive: true });
const browser = await chromium.launch({ headless: true, channel: process.env.BROWSER_CHANNEL || 'chrome' });
const context = await browser.newContext({ viewport: { width: 1600, height: 1000 } });
const fixtureResponse = await context.request.post(new URL('/api/optimization/recompute', baseUrl).href, {
  data: { green_preference: 0.5, carbon_price_cny_per_ton: 85 }, timeout: 90000,
});
assert.equal(fixtureResponse.status(), 200);
const fixture = await fixtureResponse.json();
const page = await context.newPage();
page.setDefaultTimeout(15000);
const results = [], requests = [], pageErrors = [];
page.on('pageerror', error => pageErrors.push(String(error)));
let handler;
await page.route('**/api/optimization/recompute', async route => {
  const parameters = route.request().postDataJSON();
  requests.push({ ...parameters, at: Date.now() });
  if (handler) await handler(route, parameters);
  else await fulfill(route, parameters);
});
async function fulfill(route, parameters, carbonKg = fixture.strategies[1].total_carbon_kg) {
  const snapshot = structuredClone(fixture);
  snapshot.green_preference = parameters.green_preference;
  snapshot.carbon_market.carbon_price_cny_per_ton = parameters.carbon_price_cny_per_ton;
  snapshot.strategies[1].total_carbon_kg = carbonKg;
  await route.fulfill({ status: 200, json: snapshot });
}
async function save() {
  await fs.writeFile(path.join(output, 'dashboard-errors.json'), JSON.stringify({
    recorded_at: new Date().toISOString(), fixture_source: 'local_api_response',
    results, requests, pageErrors,
  }, null, 2));
}
async function check(name, fn) {
  const start = Date.now();
  try { const detail = await fn(); results.push({ name, pass: true, ms: Date.now() - start, detail }); console.log(`PASS ${name}`); }
  catch (error) {
    results.push({ name, pass: false, ms: Date.now() - start, error: String(error) });
    console.log(`FAIL ${name}: ${error.message}`);
    await page.screenshot({ path: path.join(output, `dashboard-errors-failure-${results.length}.png`), fullPage: true });
  }
  await save();
}
async function closePanels() {
  const impact = page.locator('.decision-impact-layer.done header button');
  if (await impact.isVisible()) await impact.click();
  for (const name of ['关闭业务动作详情', '关闭顶部功能面板']) {
    const button = page.getByRole('button', { name, exact: true });
    if (await button.isVisible()) await button.click();
  }
}
const carbonKpi = page.locator('.command-kpi').filter({ hasText: '碳排放' });
async function waitUntil(check, message) {
  const deadline = Date.now() + 15000;
  while (Date.now() < deadline) {
    if (await check()) return;
    await page.waitForTimeout(80);
  }
  throw new Error(message);
}

try {
  await page.goto(baseUrl, { waitUntil: 'domcontentloaded', timeout: 60000 });
  await page.locator('.ops-row-button').first().waitFor();
  await check('重算失败显示异常且不冒充成功', async () => {
    handler = route => route.fulfill({ status: 503, json: { detail: 'acceptance_dashboard_temporarily_unavailable' } });
    await page.locator('.scenario-controls > button').click();
    await page.locator('.decision-impact-report.has-error').waitFor();
    assert.match(await page.locator('.dashboard-sync-alert').innerText(), /acceptance_dashboard_temporarily_unavailable/);
    const report = await page.locator('.decision-impact-report').innerText();
    assert(!report.includes('RL DECISION IMPACT REPORT'));
    assert.equal(await page.locator('.decision-impact-result-grid article').count(), 0);
    await page.screenshot({ path: path.join(output, 'dashboard-recompute-failure.png'), fullPage: true });
    return report.slice(0, 800);
  });
  await check('重试恢复后清除错误并显示新快照', async () => {
    await closePanels();
    handler = (route, params) => fulfill(route, params, 123000);
    await page.getByRole('button', { name: '重试同步', exact: true }).click();
    await page.locator('.dashboard-sync-alert').waitFor({ state: 'hidden' });
    await waitUntil(async () => (await carbonKpi.innerText()).includes('123.0'), 'Recovered snapshot not displayed');
    assert.equal(pageErrors.length, 0);
    return await carbonKpi.innerText();
  });
  await check('情景重算只发一次请求且结果采用本次响应', async () => {
    const start = requests.length;
    handler = async (route, params) => {
      await new Promise(resolve => setTimeout(resolve, 500));
      await fulfill(route, params, 222222);
    };
    await page.locator('.scenario-controls > div button').nth(2).click();
    await page.locator('.decision-impact-layer.done').waitFor();
    await page.waitForTimeout(400);
    const ownRequests = requests.slice(start).filter(request => request.green_preference === 0.82);
    assert.equal(ownRequests.length, 1, JSON.stringify(ownRequests));
    const report = await page.locator('.decision-impact-report').innerText();
    assert.match(report, /222\.2 t/);
    assert.match(await carbonKpi.innerText(), /222\.2/);
    await closePanels();
    return { requests: ownRequests.length, report: report.slice(0, 600) };
  });
  await check('延迟旧响应不会覆盖较新偏好快照', async () => {
    await page.locator('.emission-chart-panel').click();
    const slider = page.locator('.top-action-panel input[type="range"]');
    let releaseOld, oldStarted = false;
    const oldResponseGate = new Promise(resolve => { releaseOld = resolve; });
    handler = async (route, params) => {
      if (params.green_preference === 1) {
        oldStarted = true;
        await oldResponseGate;
        await fulfill(route, params, 111111).catch(() => undefined);
      } else await fulfill(route, params, 987654);
    };
    await slider.focus();
    await slider.press('End');
    await waitUntil(() => oldStarted, 'First preference request did not start');
    await slider.press('Home');
    await waitUntil(async () => (await carbonKpi.innerText()).includes('987.7'), 'New preference response not displayed');
    releaseOld();
    await page.waitForTimeout(900);
    assert.equal(await slider.inputValue(), '0');
    assert.match(await carbonKpi.innerText(), /987\.7/);
    assert.equal(await page.locator('.dashboard-sync-alert').count(), 0);
    return { slider: await slider.inputValue(), kpi: await carbonKpi.innerText() };
  });
  await check('碳价输入上限和下限正确进入请求', async () => {
    handler = (route, params) => fulfill(route, params);
    const input = page.locator('.top-action-panel input[type="number"]');
    await input.fill('99999');
    await waitUntil(() => requests.at(-1).carbon_price_cny_per_ton === 1000, 'Carbon price upper boundary missing');
    assert.equal(await input.inputValue(), '1000');
    await input.fill('-5');
    await waitUntil(() => requests.at(-1).carbon_price_cny_per_ton === 0, 'Carbon price lower boundary missing');
    assert.equal(await input.inputValue(), '0');
    return requests.slice(-2);
  });
  await check('初次载入失败可恢复且没有未处理拒绝', async () => {
    handler = route => route.fulfill({ status: 502, json: { detail: [{ msg: 'acceptance_initial_snapshot_failure' }] } });
    await page.reload({ waitUntil: 'domcontentloaded', timeout: 60000 });
    await page.locator('.dashboard-sync-alert').waitFor();
    const notice = await page.locator('.dashboard-sync-alert').innerText();
    assert.match(notice, /acceptance_initial_snapshot_failure/);
    assert.match(notice, /尚未取得快照/);
    assert.equal(await page.locator('.ops-row-button').count(), 0);
    handler = (route, params) => fulfill(route, params);
    await page.getByRole('button', { name: '重试同步', exact: true }).click();
    await page.locator('.ops-row-button').first().waitFor();
    await page.locator('.dashboard-sync-alert').waitFor({ state: 'hidden' });
    assert.equal(pageErrors.length, 0, pageErrors.join('\n'));
    await page.screenshot({ path: path.join(output, 'dashboard-errors-recovered.png'), fullPage: true });
    return { notice, unhandledErrors: pageErrors.length };
  });
  await check('全部轨迹末项可滚动点击且不覆盖底部按钮', async () => {
    await closePanels();
    await page.locator('.optimization-tabs button').nth(1).click();
    await page.locator('.decision-impact-layer.done').waitFor();
    await closePanels();
    const rows = page.locator('.recommendation-list button');
    assert.equal(await rows.count(), fixture.strategies[1].trajectory.length);
    await rows.last().scrollIntoViewIfNeeded();
    const last = await rows.last().boundingBox();
    const list = await page.locator('.recommendation-list').boundingBox();
    const footer = await page.locator('.view-recommendations').boundingBox();
    assert(last.y + last.height <= list.y + list.height + 1, JSON.stringify({ last, list }));
    assert(last.y + last.height <= footer.y + 1, JSON.stringify({ last, footer }));
    await rows.last().click();
    await page.locator('.operation-detail-panel').waitFor();
    const step = fixture.strategies[1].trajectory.at(-1).step;
    assert.match(await page.locator('.operation-detail-panel').innerText(), new RegExp(`STEP ${step}`));
    await page.screenshot({ path: path.join(output, 'recommendation-final-step.png'), fullPage: true });
    return { rowCount: await rows.count(), step, list, footer };
  });
} finally {
  await save();
  await browser.close();
}
if (results.some(result => !result.pass) || pageErrors.length) process.exitCode = 1;
