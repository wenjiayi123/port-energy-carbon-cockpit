import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import fs from 'node:fs/promises';
import path from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';

const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const root = path.resolve(fileURLToPath(new URL('..', import.meta.url)));
const output = path.resolve(process.env.TRAINING_AUDIT_OUTPUT || path.join(root, 'tmp/ui-audit-2026-09-12/training-live'));
const apiBase = process.env.TRAINING_AUDIT_API || 'http://127.0.0.1:8808';
const uiBase = process.env.UI_AUDIT_URL || 'http://127.0.0.1:5173/';
const runs = path.join(root, 'backend/app/data/runs');
const active = new Set(['running', 'paused', 'stopping']);
await fs.mkdir(output, { recursive: true });

async function filesIn(directory) {
  const entries = await fs.readdir(directory, { withFileTypes: true });
  return (await Promise.all(entries.map(entry => entry.isDirectory()
    ? filesIn(path.join(directory, entry.name)) : [path.join(directory, entry.name)]))).flat();
}
async function digest(file) {
  return crypto.createHash('sha256').update(await fs.readFile(file)).digest('hex');
}
const oldFiles = [
  ...await filesIn(runs),
  path.join(root, 'reports/dispatch_v7_current.json'),
  ...await filesIn(path.join(root, 'reports/dispatch_v7_qualified_attempt_01')),
];
const beforeHashes = Object.fromEntries(await Promise.all(oldFiles.map(async file => [path.relative(root, file), await digest(file)])));
const initialJobs = new Set(await fs.readdir(runs));
await fs.writeFile(path.join(output, 'before-hashes.json'), JSON.stringify(beforeHashes, null, 2));

const browser = await chromium.launch({ headless: true, channel: 'chrome' });
const context = await browser.newContext({ viewport: { width: 1600, height: 1100 } });
const page = await context.newPage();
page.setDefaultTimeout(15000);
const report = { recorded_at: new Date().toISOString(), pass: false, events: [], page_errors: [], training_responses: [], original_file_count: oldFiles.length };
let jobId;
let startAttempted = false;
let failure;
page.on('pageerror', error => report.page_errors.push(String(error)));
page.on('response', response => {
  if (response.url().includes('/api/rl/train/')) report.training_responses.push({ url: response.url(), status: response.status() });
});
async function status() {
  const response = await context.request.get(`${apiBase}/api/rl/train/status`, { timeout: 15000 });
  assert.equal(response.status(), 200);
  return response.json();
}
async function poll(name, predicate, timeout = 60000) {
  const deadline = Date.now() + timeout;
  let current;
  while (Date.now() < deadline) {
    current = await status();
    if (jobId) assert.equal(current.job_id, jobId, 'A different training job replaced the audit job');
    if (predicate(current)) {
      report.events.push({ name, status: current.status, step: current.step, job_id: current.job_id, at: new Date().toISOString() });
      console.log(`PASS ${name}: ${current.status}, step ${current.step}`);
      return current;
    }
    if (current.status === 'failed') throw new Error(`Learner failed: ${current.error}`);
    await new Promise(resolve => setTimeout(resolve, 400));
  }
  throw new Error(`${name} timed out: ${JSON.stringify({ status: current?.status, step: current?.step })}`);
}
async function enabledClick(selector) {
  await page.locator(`${selector}:enabled`).waitFor({ timeout: 60000 });
  await page.locator(selector).click();
}
async function screenshot(name) {
  await page.screenshot({ path: path.join(output, `${name}.png`), fullPage: true });
}

try {
  const initial = await status();
  assert(!active.has(initial.status), 'Refusing to interfere with an existing active training job');
  report.initial_status = { status: initial.status, job_id: initial.job_id };
  await page.goto(uiBase);
  await page.locator('.xiaoyi-link-trigger').waitFor({ timeout: 60000 });
  await page.locator('.xiaoyi-link-trigger').click();
  await enabledClick('#btnOpenTrainingStudio');
  await page.locator('#trainingDataSelect').fill('port_la_2020_2024_operational_flex_hourly');
  await page.locator('#trainingAlgorithmSelect').selectOption('ppo');
  const totalSteps = page.locator('.studio-param-grid label').filter({ has: page.getByText('训练总步数', { exact: true }) }).locator('input');
  await totalSteps.fill('50000');
  await page.locator('.studio-param-grid label').filter({ has: page.getByText('随机种子', { exact: true }) }).locator('input').fill('20260912');
  await screenshot('configured-v5-ppo');
  await page.getByRole('button', { name: '生成确认面板', exact: true }).click();
  await page.locator('#btnStageConfirmTraining:enabled').waitFor({ timeout: 60000 });
  const preview = await status();
  assert.equal(preview.job_id, initial.job_id, 'Preview unexpectedly created a training job');
  report.events.push({ name: 'Preview did not start a job', pass: true });
  await screenshot('confirmation-required');

  const responsePromise = page.waitForResponse(response => response.url().endsWith('/api/rl/train/start') && response.request().method() === 'POST', { timeout: 60000 });
  startAttempted = true;
  await page.locator('#btnStageConfirmTraining').click();
  const response = await responsePromise;
  const started = await response.json();
  assert.equal(response.status(), 200, JSON.stringify(started));
  jobId = started.result?.job_id;
  assert(jobId && !initialJobs.has(jobId), 'Expected a new dedicated training run');
  report.job_id = jobId;
  report.start_result = started;
  assert.equal(started.result.config.algorithm, 'ppo');
  assert.equal(started.result.config.total_steps, 50000);
  assert.equal(started.result.config.dataset_id, 'port_la_2020_2024_operational_flex_hourly');
  await poll('Real learner progressed', current => current.status === 'running' && current.step > 0);
  const done = page.locator('.stage-modal-actions').getByRole('button', { name: '知道了', exact: true });
  await done.waitFor({ timeout: 60000 });
  await done.click();
  await enabledClick('#btnPauseTraining');
  await poll('Pause applied', current => current.status === 'paused');
  await page.locator('#btnPauseTraining:enabled').waitFor({ timeout: 60000 });
  assert.match(await page.locator('#btnPauseTraining').innerText(), /Resume/);
  const paused = await status();
  await new Promise(resolve => setTimeout(resolve, 1400));
  const held = await status();
  assert.equal(held.status, 'paused');
  assert.equal(held.step, paused.step, 'Training steps must remain frozen while paused');
  report.events.push({ name: 'Paused steps frozen', step: held.step, pass: true });
  await screenshot('paused');
  await enabledClick('#btnPauseTraining');
  const resumed = await poll('Resume progressed', current => current.status === 'running' && current.step > held.step);
  report.resumed_step = resumed.step;
  await enabledClick('#btnStopTraining');
  const stopped = await poll('Stop saved a real checkpoint', current => current.status === 'stopped', 60000);
  assert(stopped.step > 0 && stopped.step < 50000);
  assert(stopped.artifact_path, 'Stopping must preserve the new model artifact');
  report.final_status = stopped;
  await page.locator('#btnTrainingStatus:enabled').waitFor({ timeout: 60000 });
  await enabledClick('#btnTrainingStatus');
  await page.locator('#btnTrainingStatus:enabled').waitFor({ timeout: 60000 });
  assert(await page.locator('#btnPauseTraining').isDisabled());
  assert(await page.locator('#btnStopTraining').isDisabled());
  await screenshot('stopped-checkpoint-saved');
  const manifest = JSON.parse(await fs.readFile(path.join(runs, jobId, 'manifest.json'), 'utf8'));
  assert.equal(manifest.status, 'stopped');
  assert.equal(manifest.config.environment_id, 'PortEnergyDispatchEnv-v5');
  assert.equal(manifest.step, stopped.step);
  assert.equal(await digest(path.join(runs, jobId, 'model.zip')), manifest.artifact_sha256);
  report.new_manifest = manifest;
  assert.equal(report.page_errors.length, 0, JSON.stringify(report.page_errors));
  assert(report.training_responses.every(item => item.status < 400));
} catch (error) {
  failure = error;
  report.error = String(error.stack || error);
  await screenshot('failure').catch(() => {});
} finally {
  // UI controls are the acceptance path; direct POST is emergency cleanup only.
  // Never stop a pre-existing job or a job that replaced this audit run.
  try {
    const current = await status();
    if (!jobId && startAttempted && current.config?.seed === 20260912 && !initialJobs.has(current.job_id)) jobId = current.job_id;
    if (jobId && current.job_id === jobId && active.has(current.status)) {
      const cleanup = await context.request.post(`${apiBase}/api/rl/train/stop`);
      report.emergency_stop = { status: cleanup.status(), job_id: jobId };
      await poll('Emergency stop completed', item => !active.has(item.status), 60000);
    }
    report.cleanup_status = await status();
    assert(!jobId || report.cleanup_status.job_id !== jobId || !active.has(report.cleanup_status.status), 'Audit learner is still active');
  } catch (error) {
    report.cleanup_error = String(error);
    failure ||= error;
  }
  const afterHashes = {};
  const changed = [];
  for (const [relative, expected] of Object.entries(beforeHashes)) {
    const actual = await digest(path.join(root, relative)).catch(() => null);
    afterHashes[relative] = actual;
    if (actual !== expected) changed.push(relative);
  }
  report.changed_original_files = changed;
  if (changed.length) failure ||= new Error(`Original artifacts changed: ${changed.join(', ')}`);
  report.pass = !failure;
  await fs.writeFile(path.join(output, 'after-hashes.json'), JSON.stringify(afterHashes, null, 2));
  await fs.writeFile(path.join(output, 'training-live.json'), JSON.stringify(report, null, 2));
  await browser.close();
}
if (failure) throw failure;
console.log(`PASS training live acceptance: ${jobId}; ${oldFiles.length} original files unchanged`);
