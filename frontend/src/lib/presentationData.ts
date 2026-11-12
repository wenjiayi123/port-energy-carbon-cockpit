// Presentation only: missing readings remain unavailable; charging is a load.
export type Signal = { value: unknown; quality_status?: string };
export function signalNumber(signals: Record<string, Signal> | undefined, key: string): number | undefined {
  const signal = signals?.[key];
  if (!signal || ['失联', '离线', '断连', 'disconnected', 'offline', 'missing', 'stale'].includes(signal.quality_status ?? '')) return undefined;
  return typeof signal.value === 'number' && Number.isFinite(signal.value) ? signal.value : undefined;
}
export function sourceMix(signals: Record<string, Signal> | undefined) {
  const grid = signalNumber(signals, 'grid.import_power_kw');
  const solar = signalNumber(signals, 'solar.available_power_kw');
  const battery = signalNumber(signals, 'battery.power_kw');
  if (grid === undefined || solar === undefined || battery === undefined || grid < 0 || solar < 0) return null;
  const discharge = Math.max(0, battery), charge = Math.max(0, -battery);
  const supply = grid + solar + discharge;
  return { grid, solar, discharge, charge, supply,
    gridPercent: supply > 0 ? grid / supply * 100 : null,
    solarPercent: supply > 0 ? solar / supply * 100 : null,
    batteryPercent: supply > 0 ? discharge / supply * 100 : null };
}
