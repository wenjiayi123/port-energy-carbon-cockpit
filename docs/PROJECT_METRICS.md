# Project metrics and scope

## Project summary

**【工程5】CarbonOps 智慧港口 AI 能碳调度系统（独立全栈自研）**

面向港口岸电、装卸资源与储能协同配置，自研分层环境契约
`PortEnergyDispatchEnv-v1/v2/v3`：19 维能碳基准、25 维船舶活动增强环境及
35 维实港接入环境；使用岸电、岸桥、场内车辆及储能 4 维连续动作（DQN 为
81 个可审计离散组合），支持 PPO、SAC、TD3、DQN 与四步约束 MPC 同环境训练评测。

▸ **业务价值：** 基于洛杉矶港 2020–2025 官方月度 TEU、EIA 加州商业月均电价
及 EIA-930 LADWP 小时电力/碳强度构建 52,608 小时时序集（98.32% 小时碳数据
为报告值），按 2020–2023/2024/2025 划分训练、验证和测试；在覆盖 2025 全年的
48 个留出窗口、1,152 个仿真步上，约束 MPC 相对“全岸电+固定满配资源”强基线
降低能耗 **8.4%**、碳排 **8.7%**、情景成本 **7.9%**、峰值负荷 **3.2%**，
设备平均启用比例降低 **28.8%**，吞吐保持率 **99.97%**、约束满足率 **100%**。
为避免只使用固定满配这一有利分母，另在 2024 验证集从 9 个静态配置中选择
80%/80% 岸桥与场内车辆比例并冻结到 2025 测试；MPC 相对该更强基线仍降低
碳排 **2.84%**、能耗 **2.52%**、成本 **2.08%**，吞吐提高 **0.85%**，
同时峰值负荷增加 **3.38%**，完整披露多目标权衡。
（公开数据离线情景，非港口实测 KPI）

▸ **公开数据增强：** 另构建洛杉矶港 2020–2024 官方逐日船舶活动包，解析
**1,238** 条官方工作日记录并形成 43,848 小时时序；每个插值日保留质量码，
原 52,608 小时能碳包不删除。在同样 48×24 小时留出协议下，增强包的约束 MPC
相对固定满配基线降低碳排 **8.90%**、能耗 **8.85%**、情景成本 **8.22%**，
吞吐保持 **100.00%**、约束满足率 **100%**；相对验证集冻结的 80%/80%
更强基线，碳排降低 **2.77%**，同时峰值增加 **3.61%**。数据来源、原始 PDF
更正、哈希和插值比例均随包发布。（公开数据离线情景，非港口实测 KPI）

▸ **技术栈：** React 18 + TypeScript + Vite + FastAPI + Pydantic + Gymnasium +
Stable-Baselines3/PyTorch（PPO/SAC/TD3/DQN）+ 约束 MPC + Pandas/NumPy +
Docker Compose/Nginx + GitHub Actions/CodeQL

## Metric status

| Claim | Status | Evidence |
|---|---|---|
| Four RL learners plus MPC | supported | all four execute Stable-Baselines3 `learn()`; smoke tests are wiring evidence only |
| 19/25/35 observations, four continuous controls, 81 DQN actions | supported | v1/v2/v3 environment spaces and encoder tests |
| 52,608-hour chronological package | supported with boundary | EIA grid signals are hourly; port TEU remains a deterministic allocation of 72 official monthly anchors |
| 1,238 official daily vessel-activity rows | supported with boundary | Port of Los Angeles daily activity PDFs; non-business days are explicitly interpolated and quality-coded |
| 98.32% reported hourly carbon coverage | supported | 51,726 reported and 882 quality-coded imputed hours |
| 8.7% carbon and 7.9% scenario-cost reduction | supported with qualifier | held-out constrained MPC versus full-shore fixed-full-resource comparator |
| 8.90% enhanced-package carbon reduction | supported with qualifier | held-out constrained MPC versus the same fixed-full-resource comparator; not RL superiority |
| 100% constraint satisfaction | supported with qualifier | modeled grid/SOC/delay constraints over 1,152 selected test steps |
| RL convergence or superiority | not established | do not infer from smoke or short tuning runs |
| Real tariff, terminal telemetry, or field savings | not established | price, TEU allocation, physical coefficients and costs remain scenario inputs |

## Reporting scope

Keep “公开数据离线情景”, the exact strong comparator, and “非港口实测 KPI” next to
the numeric result. Re-run:

```bash
make benchmark
make verify-benchmark
```

before publishing metrics after any dataset, environment, objective, action-shield or MPC change.
