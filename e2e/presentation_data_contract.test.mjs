import test from 'node:test';
import assert from 'node:assert/strict';
import { signalNumber, sourceMix } from '../frontend/src/lib/presentationData.ts';

test('zero solar stays zero and charging is excluded from supply', () => {
  const s = {'grid.import_power_kw': {value: 1000}, 'solar.available_power_kw': {value: 0}, 'battery.power_kw': {value: -200}};
  const m = sourceMix(s);
  assert.equal(m.solarPercent, 0); assert.equal(m.batteryPercent, 0);
  assert.equal(m.gridPercent, 100); assert.equal(m.charge, 200); assert.equal(m.supply, 1000);
});
test('discharging supplies energy and normalized shares conserve 100 percent', () => {
  const s = {'grid.import_power_kw': {value: 1000}, 'solar.available_power_kw': {value: 0}, 'battery.power_kw': {value: 200}};
  const m = sourceMix(s);
  assert.equal(m.supply, 1200); assert.equal(m.charge, 0);
  assert.ok(Math.abs(m.gridPercent + m.solarPercent + m.batteryPercent - 100) < 1e-9);
});
test('missing, disconnected, boolean or nonfinite signals do not become zero', () => {
  for (const value of [null, undefined, NaN, Infinity, false, '0']) {
    assert.equal(signalNumber({x: {value}}, 'x'), undefined);
  }
  assert.equal(signalNumber({x: {value: 0}}, 'x'), 0);
  assert.equal(signalNumber({x: {value: 100, quality_status: 'disconnected'}}, 'x'), undefined);
  assert.equal(signalNumber({x: {value: 100, quality_status: '失联'}}, 'x'), undefined);
  assert.equal(sourceMix({'grid.import_power_kw': {value: 1000}}), null);
});
