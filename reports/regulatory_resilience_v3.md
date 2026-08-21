# 海事/海关检查能碳韧性策略 v3

> PREDECLARED_REGULATORY_ENERGY_STRESS_SCENARIO_NOT_FIELD_KPI。情景不是现场 KPI，生产权限关闭。

v1 全动作 SAC 和 v2 简单门控的失败结果均原样保留。v3 冻结旧四动作，以旧策略恢复服务量为下限；SAC 只提出额外恢复量，投影器以最小准备能耗执行，并拒绝即时成本劣于旧策略的提案。

在首次读取的冻结 2025 final challenge test 上，相对旧策略：成本 +0.666%，碳排 +0.688%，总延误 +0.000%，监管链延误 +0.000%，峰值 -0.601%。

| 检查 | 结果 | 数值 |
|---|---:|---:|
| development_dataset_quality | PASS | pass |
| final_dataset_quality | PASS | pass |
| minimum_training_steps | PASS | 5000 |
| validation_only_selection | PASS | 2024 validation |
| frozen_final_test | PASS | 2025 final challenge test once |
| test_window_count | PASS | 48 |
| cost_non_regression | PASS | 0.666 |
| carbon_non_regression | PASS | 0.688 |
| delay_non_regression | PASS | 0.0 |
| regulatory_delay_non_regression | PASS | 0.0 |
| peak_non_regression | PASS | -0.601 |
| cost_ci95_non_regression | PASS | 0.6452 |
| delay_ci95_non_regression | PASS | 0.0 |
| zero_mean_safety_violations | PASS | 0.0 |
| historical_and_failed_artifacts_preserved | PASS | 105 |

离线状态：**passed**；`production_authority=false`。
