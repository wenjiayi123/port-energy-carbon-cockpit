# CarbonOps offline benchmark

Evidence label: `OFFLINE_SCENARIO_BENCHMARK_NOT_FIELD_KPI`

This is a reproducible public-data scenario result, not a live-port KPI, field trial,
regulatory assurance, or evidence of RL convergence.

## Held-out result

- Split: `2024-01 through 2024-12`
- Test coverage: `1152` hourly simulation steps
- Primary comparator: full shore power with fixed crane/yard resources
- MPC energy reduction vs strong comparator: `8.850%`
- MPC carbon reduction vs strong comparator: `8.904%`
- MPC cost saving vs strong comparator: `8.215%`
- MPC peak-load reduction vs strong comparator: `3.193%`
- Mean equipment activation reduction: `28.767%`
- Constraint-compliant test steps: `100.000%`
- Throughput change: `+0.000%`
- Throughput retention: `100.000%`
- Peak-load change: `-3.193%`

## Harder validation-calibrated comparator

The static crane/yard ratios were selected from 9 candidates on the
`2023-01 through 2023-12` validation split only, then frozen before the
`2024-01 through 2024-12` test. Against that comparator,
MPC reduces energy by `2.656%`, carbon by
`2.765%`, and cost by
`2.108%`; throughput changes by
`+0.731%` and peak load changes by
`+3.609%` (positive means a higher peak).

The full-resource result remains useful as an over-provisioning reduction
scenario, but the validation-calibrated line is the stronger algorithmic
comparison and must not be hidden.

The primary comparator uses shore-power ratio 1.0 and fixed crane/yard ratios
1.0. MPC therefore receives no credit for introducing shore power; the measured
gain comes from dynamic equipment-resource allocation under the same shore-power
opportunity.

The former zero-shore-power transition scenario remains diagnostic only:
carbon `41.943%`, cost
`13.263%`. These larger values are explicitly
excluded from resume-safe metrics.

## Sensitivity

- Predeclared objective profiles: `3`
- Unique held-out steps per profile: `1152`
- Objective-step evaluations: `3456`
- Carbon reduction range: `8.904%–8.963%`
- Cost saving range: `8.215%–8.373%`
- Minimum constraint success: `100.000%`

## Evidence

- Dataset package SHA-256: `fbb3d1c34ccad61214119b600f09e8a6c37c13826fad6e4dde0c33cdc821758e`
- Environment SHA-256: `cb4fe5affc011ce042ea8d61585aa1f93306670f592c6a06e14645dc224ee643`
- Report status: `reproducible_offline_control_benchmark`
- RL convergence/superiority: not claimed in this report

## Resume-safe wording

“在公开数据离线情景的 1152 个留出测试时间步中，约束 MPC 相对全岸电固定资源强基线
降低能耗 `8.8%`、碳排
`8.9%`、情景成本
`8.2%`，峰值负荷降低
`3.2%`、设备平均启用比例降低
`28.8%`，吞吐保持率
`100.00%`；三组目标权重敏感性复算区间为
`8.9%–9.0%`，
约束满足率 `100%`。”

This sentence must retain the offline-scenario and comparator qualifiers.
