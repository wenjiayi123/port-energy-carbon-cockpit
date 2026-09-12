import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import { createRequire } from 'node:module';

// Run against an isolated local demo. No production controls or external launch
// are enabled by this harness. Set PLAYWRIGHT_MODULE if it is not on NODE_PATH.
const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const mode = process.argv[2] || 'core';
const output = path.resolve(process.env.UI_AUDIT_OUTPUT || 'tmp/ui-audit-2026-09-12');
await fs.mkdir(output, { recursive: true });
const browser = await chromium.launch({ headless: true, channel: process.env.BROWSER_CHANNEL || 'chrome' });
const context = await browser.newContext({ viewport: { width: 1600, height: 1000 } });
const page = await context.newPage();
page.setDefaultTimeout(10000);
const results = [], errors = [], responses = [];
let expectedFailure = false;
page.on('pageerror', error => errors.push({ message: String(error), expected: expectedFailure }));
page.on('console', message => { if (message.type() === 'error') errors.push({ message: message.text(), expected: expectedFailure }); });
page.on('response', response => { if (response.url().includes('/api/')) responses.push({ url: response.url(), status: response.status(), expected: expectedFailure }); });
async function save() {
  await fs.writeFile(path.join(output, `${mode}.json`), JSON.stringify({ mode, recorded_at: new Date().toISOString(), results, errors, responses }, null, 2));
}
async function check(name, fn) {
  const start = Date.now();
  try { const detail = await fn(); results.push({ name, pass: true, ms: Date.now() - start, detail }); console.log(`PASS ${name}`); }
  catch (error) { results.push({ name, pass: false, ms: Date.now() - start, error: String(error) }); console.log(`FAIL ${name}: ${error.message}`); await page.screenshot({ path: path.join(output, `${mode}-failure-${results.length}.png`), fullPage: true }).catch(() => {}); }
  await save();
}
async function ready() {
  await page.goto(process.env.UI_AUDIT_URL || 'http://127.0.0.1:5173/');
  await page.locator('.ops-row-button').first().waitFor({ timeout: 60000 });
}
async function finishImpact(allowError = false) {
  await page.locator('.decision-impact-layer.running').waitFor({ state: 'hidden', timeout: 90000 });
  const report = page.locator('.decision-impact-layer.done');
  let text = '';
  if (await report.isVisible()) {
    text = await report.innerText();
    if (!allowError) assert.equal(await report.locator('.has-error').count(), 0, text.slice(0,400));
    const close = report.locator('header button');
    if (await close.isVisible()) await close.click({timeout:1500}).catch(async error => {
      // Short replay receipts close themselves; accept only their actual removal.
      await report.waitFor({state:'hidden',timeout:6000}).catch(() => { throw error; });
    });
  }
  return text;
}
async function closePanels() {
  await finishImpact();
  for (const label of ['关闭业务动作详情','关闭顶部功能面板','关闭小懿联动面板']) {
    const button = page.getByRole('button', { name: label, exact: true });
    if (await button.isVisible()) await button.click();
  }
}
async function operation(locator, execute = false) {
  await locator.click();
  await page.locator('.operation-detail-panel').waitFor();
  const detail = await page.locator('.operation-detail-panel').innerText();
  assert(detail.includes('作用范围'));
  let report;
  if (execute) { await page.locator('.operation-primary').click(); report = await finishImpact(); }
  await closePanels();
  return { detail: detail.slice(0,450), report: report?.slice(0,500) };
}
async function runtimeClick(id) {
  await page.locator(`#${id}:enabled`).waitFor({ timeout: 30000 });
  await page.locator(`#${id}`).click();
  await page.locator('#btnRuntimeRefresh:enabled').waitFor({ timeout: 30000 });
}
async function openHub() {
  await closePanels();
  await page.locator('.xiaoyi-link-trigger').click();
  await page.locator('#btnXiaoyiHealthCheck:enabled').waitFor({ timeout: 60000 });
}
async function hubClick(id, failed = false) {
  await page.locator(`#${id}:enabled`).waitFor({timeout:60000});
  await page.locator(`#${id}`).click();
  // Panel-opening actions close the drawer asynchronously. Wait for either
  // handoff or a terminal drawer action instead of pinning the wait to a
  // button that may have just been unmounted.
  await page.waitForFunction(() => {
    const drawer = document.querySelector('.linkage-drawer');
    const drawerOpen = Boolean(drawer && getComputedStyle(drawer).display !== 'none' && drawer.getBoundingClientRect().width > 0);
    const panelOpen = Boolean(document.querySelector('.top-action-panel'));
    const state = document.querySelector('.execution-state')?.textContent ?? '';
    return panelOpen || /DONE|FAILED/.test(state) || (!drawerOpen && !document.querySelector('.decision-impact-layer.running'));
  }, null, { timeout: 90000 });
  // Panel-opening hub actions intentionally close the drawer so the panel
  // remains usable. Validate that handoff separately from drawer actions.
  if (!(await page.locator('.linkage-drawer').isVisible().catch(() => false))) {
    await page.locator('.top-action-panel').waitFor({timeout:90000});
    return { panel: (await page.locator('.top-action-panel').innerText()).slice(0, 1400) };
  }
  await finishImpact(failed);
  const state=await page.locator('.execution-state').innerText();
  assert.equal(state,failed?'FAILED':'DONE');
  return { execution: (await page.locator('.execution-result-panel').innerText()).slice(0,1400) };
}

try {
  await ready();
  if (mode === 'runtime') {
    await page.locator('.command-live').click();
    for (const [id, state] of [['btnRuntimeRefresh','running'],['btnRuntimeStop','stopped'],['btnRuntimeStart','running'],['btnRuntimeReset','running']]) {
      await check(id, async () => { await runtimeClick(id); const text = await page.locator('.runtime-control-board').innerText(); assert(text.includes(state), text); return text; });
    }
    for (const id of await page.locator('[id^=btnRuntimeScenario-]').evaluateAll(bs => bs.map(b => b.id))) {
      await check(id, async () => { expectedFailure=/communications_loss|sensor_drift/.test(id); await runtimeClick(id); const text = await page.locator('.runtime-control-board').innerText(); assert(text.includes(id.replace('btnRuntimeScenario-','')), text); await runtimeClick('btnRuntimeReset'); expectedFailure=false; return text; });
    }
    await check('推荐—双人审批—模拟执行—KPI回写—回滚', async () => {
      await runtimeClick('btnRuntimeCreateDecision');
      assert(await page.locator('#btnRuntimeExecute').isDisabled());
      await runtimeClick('btnRuntimeApproveSupervisor');
      assert(await page.locator('#btnRuntimeExecute').isDisabled());
      await runtimeClick('btnRuntimeApproveEnergyManager');
      assert.equal(await page.locator('.decision-status').innerText(), 'approved');
      await runtimeClick('btnRuntimeExecute');
      assert.equal(await page.locator('.decision-status').innerText(), 'executed_simulation');
      const receipt = await page.locator('.runtime-closed-loop').innerText();
      assert(receipt.includes('simulation_only') && receipt.includes('KPI 回写'));
      await page.screenshot({ path: path.join(output,'runtime-executed.png'), fullPage:true });
      await runtimeClick('btnRuntimeRollback');
      assert.match(await page.locator('.decision-status').innerText(), /rolled_back/);
      return receipt.slice(receipt.indexOf('执行回执'), receipt.indexOf('字段血缘'));
    });
    await runtimeClick('btnRuntimeReset');
  }
  if (mode === 'core') {
    await check('初始按钮及指标盘点',async()=>({buttons:await page.locator('button').count(),kpis:await page.locator('.command-kpi').allTextContents()}));
    const groups = [['KPI','.command-kpi'],['船舶轨迹','.ops-row-button'],['泊位','.berth-row-button'],['告警','.alert-row'],['查看全部','.ops-title button'],['图形','.ops-graphic-button, .meter-button'],['孪生泊位','.twin-berth-node'],['时间记录','.schedule-table button'],['推荐','.recommendation-list button'],['摘要','.forecast-panel button']];
    for(const [name, selector] of groups) {
      const count = await page.locator(selector).count();
      if(!count) { console.log(`INVENTORY ${name}: 0 (${selector})`); continue; }
      for(let i=0;i<count;i++) await check(`${name}-${i+1}`,()=>operation(page.locator(selector).nth(i), name==='船舶轨迹'||name==='泊位'));
    }
    for(const selector of ['.twin-current-card','.twin-data-boundary','.gantt-action','.load-curve-panel','.energy-mix-panel','.baseline-panel']) await check(selector,()=>operation(page.locator(selector),true));
    await check('二维/三维切换',async()=>{await page.getByRole('button',{name:'切换二维泊位视图 / Switch to 2D berth view',exact:true}).click();assert(await page.locator('.command-twin-stage.view-2d').count());await page.getByRole('button',{name:'切换三维港区视图 / Switch to 3D port view',exact:true}).click();assert(await page.locator('.command-twin-stage.view-3d').count());});
    await check('缩放及复位',async()=>{await page.getByRole('button',{name:'放大港区视图 / Zoom in',exact:true}).click();assert.match(await page.locator('.twin-map-world').getAttribute('style'),/1.05/);await page.getByRole('button',{name:'缩小港区视图 / Zoom out',exact:true}).click();assert.match(await page.locator('.twin-map-world').getAttribute('style'),/scale\(1\)/);await page.getByRole('button',{name:'重置地图视角 / Reset map',exact:true}).click();});
    await check('测试航迹图层',async()=>{const b=page.getByTitle('显示或隐藏归一化测试航迹 / Toggle normalized test route',{exact:true});await b.click();assert.equal(await page.locator('.twin-network-route.vessel').count(),0);await b.click();assert.equal(await page.locator('.twin-network-route.vessel').count(),1);});
    await check('暂停与继续回放',async()=>{const b=page.locator('.twin-toolbar button').nth(3);if((await b.getAttribute('title')).includes('继续')) await b.click();await b.click();await finishImpact();assert(await page.locator('.command-twin-stage.paused').count());const before=await page.locator('.twin-current-card').innerText();await page.waitForTimeout(2100);assert.equal(await page.locator('.twin-current-card').innerText(),before);const ship=await page.locator('.twin-moving-vessel').boundingBox();await page.mouse.click(ship.x+ship.width/2,ship.y+ship.height/2);assert(await page.locator('.command-twin-stage.playing').count());});
    await check('推荐/全部方案页签',async()=>{for(const tab of await page.locator('.optimization-tabs button').all()){await tab.click();await finishImpact();assert.equal(await tab.getAttribute('aria-pressed'),'true');}});
    await check('API健康检查和同步',async()=>{await page.getByRole('button',{name:'打开 API 与模型治理面板 / Open API and model governance',exact:true}).click();await page.getByRole('button',{name:'健康检查',exact:true}).click();await finishImpact();const response=page.waitForResponse(r=>r.url().includes('/api/optimization/recompute')&&r.status()===200,{timeout:90000});await page.getByRole('button',{name:'重新同步',exact:true}).click();await response;const text=await page.locator('.top-action-panel').innerText();assert(text.includes('生产'));await closePanels();return text.slice(-1000);});
    await check('全屏及恢复',async()=>{await page.getByRole('button',{name:'进入全屏驾驶舱 / Fullscreen cockpit',exact:true}).click();assert(await page.evaluate(()=>!!document.fullscreenElement));await page.getByRole('button',{name:'退出全屏驾驶舱 / Exit fullscreen cockpit',exact:true}).click();assert.equal(await page.evaluate(()=>!!document.fullscreenElement),false);});
    await page.screenshot({path:path.join(output,'overview-after.png'),fullPage:true});
    for(const [width,height] of [[1280,800],[768,1024],[390,844]]) await check(`响应式-${width}`,async()=>{await page.setViewportSize({width,height});await page.waitForTimeout(200);const size=await page.evaluate(()=>({width:innerWidth,scroll:document.documentElement.scrollWidth}));assert(size.scroll<=width+1,JSON.stringify(size));await page.screenshot({path:path.join(output,`viewport-${width}.png`),fullPage:true});return size;});
  }
  if (mode === 'hub') {
    await openHub();
    await check('小懿面板按钮盘点',async()=>await page.locator('.linkage-drawer button').evaluateAll(bs=>bs.map(b=>({id:b.id,label:b.textContent,disabled:b.disabled}))));
    for(const id of ['btnXiaoyiRuntimeSummary','btnXiaoyiRuntimeHandover','btnXiaoyiRuntimeTriage','btnXiaoyiRuntimeRecommend','btnXiaoyiRuntimeExplain','btnXiaoyiRefreshDashboard','btnXiaoyiHealthCheck','btnXiaoyiCheckSailingStatus','btnXiaoyiPreferenceEfficiency','btnXiaoyiPreferenceBalanced','btnXiaoyiPreferenceLowCarbon','btnXiaoyiPreferenceShorePower','btnTrainingStatus','btnPolicyTest','btnVerifyPolicy']) await check(id,async()=>{const result=await hubClick(id);if(result.panel) { await closePanels(); await openHub(); return result.panel; } return result.execution;});
    for(const id of ['btnXiaoyiStart','btnSailingLaunch','btnSailingDemo','btnShipView','btnSailingSmoke']) await check(`${id}-未配置的明确失败`,async()=>{const result=await hubClick(id,true);return result.execution ?? result.panel;});
    for(const [id,label] of [['btnXiaoyiOpenRuntimePanel','实时闭环功能面板'],['btnXiaoyiOpenSimulationPanel','离线仿真功能面板'],['btnXiaoyiOpenMarlPanel','RL 策略功能面板'],['btnXiaoyiOpenCarbonPanel','低碳优先功能面板'],['btnXiaoyiOpenShorePanel','岸电联动功能面板'],['btnXiaoyiOpenApiPanel','API 已同步功能面板']]) {
      await check(id,async()=>{await page.locator('#'+id).click();await page.locator('.top-action-panel').waitFor();const text=await page.locator('.top-action-panel').innerText();await closePanels();await openHub();return {label,text:text.slice(0,220)};});
    }
    await check('历史收敛曲线',async()=>{await page.locator('#btnTrainingHistory').click();await page.locator('.training-history-modal').waitFor();const text=await page.locator('.training-history-modal').innerText();assert(!text.includes('NaN'));await page.getByRole('button',{name:'关闭历史训练结果',exact:true}).click();return text.slice(0,1200);});
    await check('指令中心过滤与搜索',async()=>{await page.locator('#btnOpenCommandCenter').click();const groups=await page.locator('.command-center-tabs button').all();const counts=[];for(const b of groups){await b.click();assert.match(await b.getAttribute('class'),/active/);counts.push({group:await b.innerText(),rows:await page.locator('.command-center-row').count()});}await groups[0].click();const search=page.locator('.command-center-toolbar input');await search.fill('没有这条命令-xyz');assert(await page.locator('.command-empty-state').isVisible());await search.fill('');const total=await page.locator('.command-center-row').count();assert(total>=35);await page.getByRole('button',{name:'关闭小懿指令中心',exact:true}).click();return {counts,total};});
    await check('指令填入与判断不改变运行状态',async()=>{await page.locator('#btnOpenCommandCenter').click();await page.locator('.command-center-row').filter({hasText:'健康检查'}).first().getByRole('button',{name:'填入',exact:true}).click();assert((await page.locator('.xiaoyi-card textarea, .module-xiaoyi textarea, .linkage-drawer textarea').first().inputValue()).includes('健康'));await page.locator('#btnOpenCommandCenter').click();await page.locator('.command-center-row').filter({hasText:'健康检查'}).first().getByRole('button',{name:'判断',exact:true}).click();await page.locator('#btnXiaoyiHealthCheck:enabled').waitFor({timeout:60000});return await page.locator('.execution-state').innerText();});
    await page.screenshot({path:path.join(output,'xiaoyi-hub.png'),fullPage:true});
  }
  if (mode === 'training') {
    await openHub();
    await page.locator('#btnOpenTrainingStudio').click();
    await page.locator('.training-studio-modal').waitFor();
    await check('v6初始环境与17项奖励',async()=>{assert.equal(await page.locator('#trainingDataSelect').inputValue(),'port_la_2020_2024_hybrid_rl_hourly');assert.equal(await page.locator('.studio-reward-grid input').count(),17);assert(await page.locator('#trainingAlgorithmSelect option[value=dqn]').evaluate(option=>option.disabled));assert(await page.locator('#btnConfirmTraining').isDisabled());return (await page.locator('.studio-string-grid').innerText());});
    await check('v6→v5→v6 数据/场景/奖励/算法联动',async()=>{await page.locator('#trainingDataSelect').fill('port_la_2020_2024_operational_flex_hourly');assert.equal(await page.locator('.studio-reward-grid input').count(),11);assert.equal(await page.locator('#trainingAlgorithmSelect option[value=dqn]').isDisabled(),false);assert.equal(await page.locator('.studio-string-grid input').nth(0).inputValue(),'port_la_operational_flex_benchmark');await page.locator('#trainingAlgorithmSelect').selectOption('dqn');await page.locator('#trainingDataSelect').fill('port_la_2020_2024_hybrid_rl_hourly');assert.equal(await page.locator('.studio-reward-grid input').count(),17);assert.equal(await page.locator('#trainingAlgorithmSelect').inputValue(),'ppo');});
    await check('五种优化目标',async()=>{const options=await page.locator('#trainingObjectiveSelect option').evaluateAll(os=>os.map(o=>o.value));for(const value of options){await page.locator('#trainingObjectiveSelect').selectOption(value);assert.equal(await page.locator('#trainingObjectiveSelect').inputValue(),value);}return options;});
    await check('训练预审与返回修改',async()=>{await page.getByRole('button',{name:'生成确认面板',exact:true}).click();await page.locator('.stage-modal-layer.confirm').waitFor();const text=await page.locator('.stage-modal-layer').innerText();assert(text.includes('需要人工确认'));await page.locator('.stage-modal-actions').getByRole('button',{name:/返回|调整/}).click();assert.equal(await page.locator('.stage-modal-layer').count(),0);return text.slice(0,700);});
    await page.screenshot({path:path.join(output,'training-studio.png'),fullPage:true});
    await page.getByRole('button',{name:'关闭训练配置工作台',exact:true}).click();
  }
  if(mode==='simulation') {
    await check('运行推演及报告',async()=>{await page.locator('.scenario-controls > button').click();const report=await finishImpact();await page.locator('.simulation-console').waitFor();assert.equal(await page.locator('.route-replay-node').count(),24);return report.slice(0,1000);});
    for(let i=0;i<24;i++) await check(`回放时间点-${i}`,async()=>{await page.locator('.route-replay-node').nth(i).click();await finishImpact();const time=String(i).padStart(2,'0')+':00';assert((await page.locator('.event-inspector h3').innerText()).includes(time));assert((await page.locator('.twin-current-card').innerText()).includes(time));assert(await page.locator('.command-twin-stage.paused').count());});
    await check('模拟器检查与未接入启动反馈',async()=>{await page.getByRole('button',{name:'检查模拟器',exact:true}).click();await finishImpact(true);await page.getByRole('button',{name:'启动模拟器',exact:true}).click();await finishImpact(true);return (await page.locator('.top-action-panel').innerText()).slice(-900);});
    await closePanels();
    await check('岸电面板及参数联动',async()=>{await page.getByRole('button',{name:'查看岸电窗口联动 / View shore power',exact:true}).click();await page.getByRole('button',{name:'切到岸电优先',exact:true}).click();await finishImpact();const t=await page.locator('.top-action-panel').innerText();assert(t.includes('岸电'));await closePanels();return t.slice(-900);});
    await check('碳价情景与偏好更新',async()=>{await page.locator('.emission-chart-panel').click();const input=page.getByRole('spinbutton',{name:'碳价情景',exact:true});for(const price of ['120','1000','85']){const response=page.waitForResponse(r=>r.url().includes('/api/optimization/recompute')&&r.status()===200,{timeout:90000});await input.fill(price);await response;assert.equal(await input.inputValue(),price);}for(const name of ['效率优先','均衡调度','低碳优先']){await page.getByRole('button',{name,exact:true}).click();await page.waitForTimeout(400);}const t=await page.locator('.top-action-panel').innerText();await closePanels();return t.slice(-700);});
    for(let i=0;i<3;i++) await check(`场景-${i}`,async()=>{await closePanels();const b=page.locator('.scenario-controls > div button').nth(i);await b.click();await finishImpact();assert.equal(await b.getAttribute('aria-pressed'),'true');return await page.locator('.scenario-panel').innerText();});
    await check('RL证据及v7连续72小时策略切换',async()=>{await closePanels();await page.locator('.twin-evidence-button').click();await page.getByRole('button',{name:'刷新 v7 训练证据',exact:true}).click();const replay=page.getByRole('button',{name:'验证模型预测控制 → 学习策略 → 回退',exact:true});await replay.waitFor();await page.locator('.dispatch-learning-evidence button:enabled').first().waitFor();await replay.click();await page.locator('.dispatch-learning-evidence [role=status]').filter({hasText:'切换验证通过'}).waitFor({timeout:90000});const receipt=await page.locator('.dispatch-learning-evidence [role=status]').innerText();assert(receipt.includes('72 小时')&&receipt.includes('已回退模型预测控制')&&receipt.includes('安全越界 0'));await page.getByRole('button',{name:'查看训练状态',exact:true}).click();await page.getByRole('button',{name:'读取登记策略测试',exact:true}).click();await finishImpact();await page.screenshot({path:path.join(output,'rl-evidence.png'),fullPage:true});return receipt;});
  }
} finally {
  await save();
  await browser.close();
  console.log(JSON.stringify({mode,passed:results.filter(r=>r.pass).length,failed:results.filter(r=>!r.pass).length,unexpectedErrors:errors.filter(e=>!e.expected)},null,2));
}
if(results.some(r=>!r.pass)||errors.some(e=>!e.expected)) process.exitCode=1;
