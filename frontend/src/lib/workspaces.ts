export type WorkspaceId = 'overview' | 'twin' | 'runtime' | 'operations' | 'simulation' | 'carbon' | 'shore' | 'marl' | 'api';
export const workspaces: { id: WorkspaceId; title: string; en: string; description: string; group: string }[] = [
  { id: 'overview', title: '运行总览', en: 'OVERVIEW', description: '先看当前状态，再进入需要处理的业务。', group: '态势与运行' },
  { id: 'twin', title: '3D 孪生大屏', en: 'DIGITAL TWIN', description: '港区能源设备、供需流向与运行风险的空间视图。', group: '态势与运行' },
  { id: 'runtime', title: '调度与审批', en: 'DISPATCH', description: '从当前输入生成建议，经双人审批后模拟执行并核对回执。', group: '态势与运行' },
  { id: 'shore', title: '岸电协同', en: 'SHORE POWER', description: '核对岸电窗口、负荷与服务约束，查看协同策略。', group: '业务工作台' },
  { id: 'carbon', title: '能碳管理', en: 'ENERGY & CARBON', description: '查看排放来源、情景参数、计量核证与资产履约证据。', group: '业务工作台' },
  { id: 'operations', title: '作业轨迹', en: 'OPERATIONS', description: '独立测试集的泊位、岸桥、车辆与时间线回放。', group: '分析与治理' },
  { id: 'simulation', title: '仿真推演', en: 'SIMULATION', description: '业务能量联合计划与离线场景对比。', group: '分析与治理' },
  { id: 'marl', title: '策略与训练', en: 'POLICY LAB', description: '训练、留出集验证、历史证据与模型准入。', group: '分析与治理' },
  { id: 'api', title: '数据与接入', en: 'DATA & INTEGRATION', description: '数据质量、连接器状态与系统治理。', group: '分析与治理' },
];
export function readWorkspace(): WorkspaceId {
  const id = window.location.hash.replace(/^#\/?/, '').split('?')[0];
  return workspaces.some((item) => item.id === id) ? id as WorkspaceId : 'overview';
}
