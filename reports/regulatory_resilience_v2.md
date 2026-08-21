# 海事/海关检查能碳韧性策略 v2

> PREDECLARED_REGULATORY_ENERGY_STRESS_SCENARIO_NOT_FIELD_KPI。监管事件与 v3 接入变量是冻结压力情景，不是现场或监管机关实测 KPI。

## 结果

首轮全动作 SAC 失败候选完整保留；v2 冻结原四项能碳动作，只学习检查准备度与放行恢复优先级，并由外生放行信号启用动作。

在未参与训练、选种和门控设计的 2025 前向挑战 test 上，相对保留的旧固定策略：情景成本 -0.241%，碳排 -0.226%，总延误 -1.021%，监管链延误 -1.691%，峰值 +0.281%。

## 离线准入门

| 检查 | 结果 | 数值 |
|---|---:|---:|
| development_dataset_quality | PASS | pass |
| forward_dataset_quality | PASS | pass |
| minimum_training_steps | PASS | 5000 |
| validation_only_selection | PASS | 2024 validation |
| untouched_forward_test | PASS | 2025 test evaluated once after selection |
| forward_window_count | PASS | 48 |
| cost_non_regression | BLOCKED | -0.241 |
| carbon_non_regression | BLOCKED | -0.226 |
| delay_non_regression | BLOCKED | -1.021 |
| regulatory_delay_non_regression | BLOCKED | -1.691 |
| cost_ci95_non_regression | BLOCKED | -0.2889 |
| delay_ci95_non_regression | BLOCKED | -1.919 |
| zero_mean_safety_violations | PASS | 0.0 |
| old_and_failed_artifacts_preserved | PASS | 99 |

状态：**blocked**。生产权限始终关闭。
