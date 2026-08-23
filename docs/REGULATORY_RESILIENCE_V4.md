# 海事/海关检查能碳韧性策略 v4

## 为什么要加入

海事局检查、海关查验、单证补充、放行和积压恢复不是普通随机延误。它们会改变船舶靠离泊节奏、岸电使用时长、场桥/岸桥负荷、堆场拥堵和恢复期峰值功率，因此会继续传导到成本、碳排、峰值和服务水平。忽略这条链路会使能碳调度在监管事件后低估负荷与积压。

权责边界同样重要：港口国监督检查可造成延误或滞留，海关 hold 未解除前货物不能移动；系统只能优化准备和放行后的恢复，不能预测、替代或绕过主管机关决定。依据：[IMO Port State Control](https://www.imo.org/en/ourwork/iiis/pages/port%20state%20control.aspx)、[CBP Intensive Exam Status](https://www.help.cbp.gov/s/article/Article-1268?language=en_US)、[CBP Manifest Hold](https://www.help.cbp.gov/s/article/Article-1267)。

## 状态与动作

`PortEnergyDispatchEnv-v4` 在 v3 的 35 维观测和 4 个既有动作之外增量扩展：

- 13 个监管链观测：海事/海关检查到达与放行、单证完备度、查验资源可用度、预计 hold 时长、三类跨时段队列、上一步新增动作等。
- 2 个新增动作：`inspection_readiness_ratio` 和 `recovery_priority_ratio`。
- 连续动作由 4 维增至 6 维；DQN 离散组合由 81 增至 729。
- 海事检查队列、海关查验队列和已放行恢复队列跨时段传播，并进入延误、能耗、碳排、成本与峰值计算。

v1-v3 的观测、动作、模型、报告和回放不改写；v4 是版本化增量环境。

## 策略训练与失败保留

三轮均使用真实 Stable-Baselines3 SAC 训练，每轮 3 个随机种子、每个种子 5,000 步；仅以 2024 validation 选种，最终结果只在冻结的 2025 final challenge test 上读取一次。

| 版本 | 策略 | 结论 | 业务解释 |
|---|---|---|---|
| v1 | 全动作 SAC | 阻断并保留 | 虽改善部分延误，但成本、碳排或安全门不同时满足 |
| v2 | 简单门控 SAC | 阻断并保留 | 成本、碳排和延误仍劣于既有策略 |
| v3 | 优势投影增量 SAC | 离线合格 | 冻结旧四动作，仅学习准备/恢复增量，并通过支配投影拒绝即时退化动作 |

v3 在 48 个独立 24 小时测试窗口上，相对既有策略：

- 场景成本降低 `0.666%`，95% CI 为 `0.6452%–0.6843%`；
- 碳排降低 `0.688%`，峰值降低 `0.601%`；
- 总延误、监管链延误、吞吐、期末积压和平均安全违规均不退化；
- 105 个受保护的既有文件哈希一致，v1/v2 失败候选仍可复核。

这里的业务价值不是“缩短政府检查时间”，而是在相同监管放行、恢复服务、吞吐和安全约束下，减少准备与恢复过程的能耗、成本、碳排和峰值负荷。

## 证据与复现

- 主报告：`reports/regulatory_resilience_v3.json`、`reports/regulatory_resilience_v3.md`
- 失败报告：`reports/regulatory_resilience_v1.*`、`reports/regulatory_resilience_v2.*`
- 训练模型：`reports/regulatory_resilience_v*_artifacts/*.zip`
- 数据与元数据：`backend/app/data/datasets/port_la_*regulatory*.csv` 及对应 metadata
- 重建数据：`make data-regulatory`
- 重跑训练：`make regulatory-benchmark`
- 校验证据：`make verify-regulatory-benchmark`
- 完整项目检查：`make release-check`

## 生产边界

当前证据是预声明的离线监管能耗压力情景，不是现场 KPI：

```text
simulation_mode=true
live_data_verified=false
dispatch_allowed=false
production_authority=false
```

进入生产前仍需完成主管机关/码头字段映射、现场标定、影子运行、联锁、回滚和验收；任一条件不满足继续 fail closed。
