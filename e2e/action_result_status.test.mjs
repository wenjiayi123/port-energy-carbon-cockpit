import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';
import vm from 'node:vm';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const require = createRequire(path.join(root, 'frontend/package.json'));
const ts = require('typescript');
const source = fs.readFileSync(path.join(root, 'frontend/src/components/XiaoyiLinkageHub.tsx'), 'utf8');
const parsed = ts.createSourceFile('XiaoyiLinkageHub.tsx', source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
let declaration;
function find(node) {
  if (ts.isFunctionDeclaration(node) && node.name?.text === 'completeExecution') declaration = node.getText(parsed);
  ts.forEachChild(node, find);
}
find(parsed);
assert.ok(declaration, 'test must execute the actual production result handler');
const code = ts.transpileModule(declaration + '\nglobalThis.subject = completeExecution;', {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS },
}).outputText;

function harness() {
  const states = [];
  const context = vm.createContext({
    pretty: JSON.stringify,
    setExecution: (id, phase, instruction, details) => states.push({ id, phase, instruction, details }),
  });
  vm.runInContext(code, context);
  return { run: context.subject, states };
}

test('native smoke backend timeout must fail, including its actual error receipt', () => {
  const h = harness();
  assert.throws(() => h.run('run_sailing_rl_smoke_test', '航行动作完成：timeout。', {
    execution: { type: 'godot_headless_smoke_test', status: 'timeout', error: 'smoke_test_timeout' },
  }), /smoke_test_timeout/);
  assert.equal(h.states.at(-1).phase, 'failed');
});

test('a successful native smoke receipt completes normally', () => {
  const h = harness();
  h.run('run_sailing_rl_smoke_test', 'passed', {
    execution: { status: 'passed', returncode: 0, ok_marker: true },
  });
  assert.equal(h.states.at(-1).phase, 'completed');
});

test('existing blocked or failed verification receipts remain failures', () => {
  for (const receipt of [{ result: { status: 'blocked_missing_approval' } }, { verify: { status: 'done', ok: false } }]) {
    const h = harness();
    assert.throws(() => h.run('verify_policy', 'review needed', receipt));
    assert.equal(h.states.at(-1).phase, 'failed');
  }
});

test('execution budget exhaustion is failure while an accepted training request is reported as accepted', () => {
  const h = harness();
  assert.throws(() => h.run('bounded_action', 'budget', { execution_result: { status: 'budget_exceeded' } }));
  assert.equal(h.states.at(-1).phase, 'failed');
  h.run('start_rl_training', 'training request accepted; worker still queued', { result: { status: 'queued' } });
  assert.equal(h.states.at(-1).phase, 'completed');
  assert.match(h.states.at(-1).details.resultSummary, /worker still queued/);
});
