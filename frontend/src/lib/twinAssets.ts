import type { RuntimeSnapshot } from '../components/RuntimeClosedLoopPanel';
import { signalNumber } from './presentationData';
export type TwinAssetId = 'grid' | 'solar' | 'battery' | 'shore' | 'reefer' | 'charging' | 'building';
export interface TwinAsset { id: TwinAssetId; name: string; code: string; role: string; position: [number, number, number]; color: string; field: string; unit: string; secondary: [string, string][]; destination: 'runtime' | 'shore' | 'carbon'; }
export const twinAssets: TwinAsset[] = [
  { id: 'grid', name: '港区变配电站', code: 'GRID', role: '电网输入 · 能源枢纽', position: [-23, 0, -11], color: '#55bfff', field: 'grid.import_power_kw', unit: 'kW', secondary: [['变压器负载率', 'transformer.loading_pct'], ['备用裕度', 'transformer.reserve_margin_kw'], ['电网频率', 'grid.frequency_hz']], destination: 'runtime' },
  { id: 'solar', name: '屋顶光伏阵列', code: 'PV', role: '清洁电源 · 模拟可用功率', position: [-7, 0, -17], color: '#6ee7b7', field: 'solar.available_power_kw', unit: 'kW', secondary: [['本步发电', 'solar.energy_kwh'], ['光照环境温度', 'weather.ambient_temperature_c']], destination: 'carbon' },
  { id: 'battery', name: '储能电池站', code: 'BESS', role: '削峰填谷 · 正放电 / 负充电', position: [-23, 0, 7], color: '#bd9aff', field: 'battery.power_kw', unit: 'kW', secondary: [['荷电状态 SOC', 'battery.soc_pct'], ['健康状态 SOH', 'battery.soh_pct'], ['电池温度', 'battery.temperature_c']], destination: 'runtime' },
  { id: 'shore', name: '岸电与靠泊区', code: 'OPS', role: '船舶供电 · 聚合岸电负荷', position: [12, 0, 15], color: '#4ddff2', field: 'shore_power.load_kw', unit: 'kW', secondary: [['接电船数', 'shore_power.connected_vessels'], ['可用服务容量', 'shore_power.opportunity_kw']], destination: 'shore' },
  { id: 'reefer', name: '冷藏箱作业区', code: 'REEFER', role: '连续用能 · 冷链保障', position: [8, 0, -9], color: '#f4c575', field: 'reefer.load_kw', unit: 'kW', secondary: [['接电冷藏箱', 'reefer.connected_count']], destination: 'runtime' },
  { id: 'charging', name: 'AGV 充电区', code: 'EV', role: '柔性负荷 · 作业协同', position: [-9, 0, 8], color: '#74a8ff', field: 'charging.agv_load_kw', unit: 'kW', secondary: [['活跃 AGV', 'equipment.active_agvs']], destination: 'runtime' },
  { id: 'building', name: '港区综合楼', code: 'HVAC', role: '楼宇暖通 · 负荷协同', position: [23, 0, -14], color: '#8de4e6', field: 'hvac.load_kw', unit: 'kW', secondary: [['设定温度', 'hvac.setpoint_c'], ['照明负荷', 'lighting.load_kw'], ['泵与风机', 'pumps_fans.load_kw']], destination: 'runtime' },
];
export function assetIssues(asset: TwinAsset, snapshot: RuntimeSnapshot | null): string[] {
  if (!snapshot) return ['尚未取得运行快照'];
  if (signalNumber(snapshot.signals, asset.field) === undefined) return ['信号不可用 · 已停止呈现功率流'];
  const get = (id: string) => signalNumber(snapshot.signals, id);
  const issues: string[] = [];
  if (asset.id === 'grid' && (get('transformer.loading_pct') ?? 0) >= 90) issues.push('变压器负载率 ≥ 90%');
  if (asset.id === 'battery') {
    const soc = get('battery.soc_pct');
    if (soc !== undefined && (soc < 20 || soc > 90)) issues.push('SOC 超出展示关注区间 20–90%');
    const temperature = get('battery.temperature_c');
    if ((temperature ?? 0) >= 40) issues.push('电池温度 ≥ 40°C');
    else if (snapshot.active_scenario?.scenario_id === 'battery_overtemperature') issues.push('过温模拟已激活 · 温度响应中');
  }
  return issues;
}
