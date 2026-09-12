import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const outDir = path.resolve(process.env.UI_AUDIT_OUTPUT || 'tmp/ui-audit-2026-09-12');
await fs.mkdir(outDir, { recursive: true });
const browser = await chromium.launch({ headless: true, channel: process.env.BROWSER_CHANNEL || 'chrome' });
const context = await browser.newContext({ viewport: { width: 1600, height: 1000 } });
const page = await context.newPage();
page.setDefaultTimeout(15000);
const errors = [];
const timeline = [];
page.on('pageerror', (error) => errors.push(String(error)));
page.on('console', (message) => { if (message.type() === 'error') errors.push(message.text()); });
page.on('response', (response) => {
  if (response.url().includes('/api/')) timeline.push({ type: 'response', url: response.url(), status: response.status(), at: Date.now() });
});

async function visible(selector) { return page.locator(selector).isVisible().catch(() => false); }
async function waitForState(label, timeout = 90000) {
  const started = Date.now();
  while (Date.now() - started < timeout) {
    const drawer = await visible('.linkage-drawer');
    const panel = await visible('.top-action-panel');
    const state = await page.locator('.execution-state').innerText().catch(() => 'missing');
    timeline.push({ type: 'state', label, drawer, panel, state, at: Date.now() });
    if ((!drawer && panel) || (!drawer && /DONE|FAILED/.test(state))) return { drawer, panel, state };
    await page.waitForTimeout(500);
  }
  throw new Error(`${label} timed out: ${JSON.stringify(timeline.at(-1))}`);
}

try {
  await page.goto(process.env.UI_AUDIT_URL || 'http://127.0.0.1:5173/');
  await page.locator('.ops-row-button').first().waitFor({ timeout: 60000 });
  await page.locator('.xiaoyi-link-trigger').click();
  await page.locator('#btnXiaoyiHealthCheck:enabled').waitFor({ timeout: 30000 });
  const buttons = await page.locator('.linkage-drawer button').evaluateAll((items) => items.map((item) => item.id).filter(Boolean));
  assert(buttons.includes('btnXiaoyiRuntimeSummary'));
  await page.locator('#btnXiaoyiRuntimeSummary').click();
  const summary = await waitForState('runtime-summary');
  assert(summary.panel || summary.state === 'DONE');
  if (summary.panel) assert((await page.locator('.top-action-panel').innerText()).includes('实时闭环'));
  await page.screenshot({ path: path.join(outDir, 'hub-smoke-runtime-summary.png'), fullPage: true });
  const result = { pass: true, buttons: buttons.length, summary, errors, timeline };
  await fs.writeFile(path.join(outDir, 'hub-smoke.json'), JSON.stringify(result, null, 2));
  console.log(JSON.stringify(result, null, 2));
} catch (error) {
  const result = { pass: false, error: String(error), errors, timeline };
  await fs.writeFile(path.join(outDir, 'hub-smoke.json'), JSON.stringify(result, null, 2));
  console.error(JSON.stringify(result, null, 2));
  process.exitCode = 1;
} finally {
  await browser.close();
}
