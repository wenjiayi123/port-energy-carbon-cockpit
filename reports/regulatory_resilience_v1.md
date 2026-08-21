# 海事/海关检查能碳韧性策略 v1

> PREDECLARED_REGULATORY_ENERGY_STRESS_SCENARIO_NOT_FIELD_KPI。这是公开数据底座上的预声明压力情景，不是海事局、海关或码头现场 KPI。

## 结论

保留原有 v1–v3 和全部历史策略，新增 `PortEnergyDispatchEnv-v4`（48 维观测、6 维连续动作/729 个离散组合）。检查、扣留、放行信号均为外生；策略只控制码头准备度和放行后恢复优先级。

在独立留出测试集上，入选 SAC 相对旧固定策略：情景成本 -0.58%，总延误 -11.27%，监管链延误 +0.16%，碳排 -3.25%，期末积压 -7.19%。

## 训练与盲测协议

- 三个 SAC 种子各 5,000 个真实 learner steps；训练不渲染。
- 只用 validation 选种子；选定后才读取 test，48 个固定 24 小时窗口。
- 历史文件 93 个哈希前后一致，未覆盖旧模型、报告或失败候选。

## 离线准入门

| 检查 | 结果 | 数值 |
|---|---:|---:|
| dataset_quality | PASS | pass |
| train_validation_test_isolation | PASS | validation selected; test once |
| minimum_training_steps | PASS | 5000 |
| test_window_count | PASS | 48 |
| cost_non_regression | BLOCKED | -0.577 |
| delay_non_regression | BLOCKED | -11.266 |
| regulatory_delay_non_regression | PASS | 0.157 |
| cost_ci95_non_regression | BLOCKED | -0.8969 |
| delay_ci95_non_regression | BLOCKED | -28.3445 |
| zero_mean_safety_violations | BLOCKED | 0.020833 |
| historical_artifacts_preserved | PASS | 93 |

最终状态：**blocked**。即使通过离线门，`production_authority=false`，仍需真实监管/TOS/EMS/设备数据、现场标定、影子运行和人工授权。
