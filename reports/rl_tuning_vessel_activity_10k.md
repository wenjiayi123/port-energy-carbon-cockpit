# Enhanced-dataset RL short-budget evidence

Evidence label: `OFFLINE_RL_EXPERIMENT_NOT_FIELD_KPI`

Dataset: `port_la_2020_2024_vessel_activity_hourly`
Environment: `PortEnergyDispatchEnv-v2` (25 observations)
Protocol: fit on `train`, select hyperparameters on `validation`, report only
the frozen selection on `test`; `render_mode=None` during fit and selection.
Compute: 2 validation candidates + 3 final seeds per algorithm, 10,000 steps
per fit, 20 real Stable-Baselines3 fits in total.

## Held-out test summary

The values below are means across seeds 11, 29 and 47. Each seed covers 48
held-out episodes and 1,152 test steps.

| Algorithm | Mean reward | Carbon (kgCO2e) | Scenario cost (CNY) | Processed TEU | Peak (kW) | Safety violations |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| DQN | -3.730278 | 97,126.680 | 543,895.823 | 27,984.537 | 15,841.001 | 0 |
| PPO | 0.244317 | 98,644.380 | 568,180.173 | 28,134.218 | 15,667.259 | 0 |
| SAC | 1.129111 | 104,447.549 | 550,968.264 | 28,104.541 | 12,525.577 | 0 |
| TD3 | 1.636879 | 93,064.863 | 548,732.078 | 28,109.320 | 14,125.455 | 0 |

TD3 has the highest mean environment reward and lowest mean carbon in this
specific short-budget matrix. SAC has the lowest mean peak. DQN has the lowest
mean scenario cost but lower processed volume. These are multi-objective
trade-offs under one offline environment, not proof of convergence, field
savings or universal algorithm superiority.

## Selection results

| Algorithm | Validation-selected hyperparameters |
| --- | --- |
| DQN | learning rate 0.0003; batch 128; gamma 0.995; exploration fraction 0.4 |
| PPO | learning rate 0.0003; batch 64; gamma 0.99; entropy coefficient 0 |
| SAC | learning rate 0.0003; batch 128; gamma 0.99; tau 0.005 |
| TD3 | learning rate 0.0003; batch 256; gamma 0.995; tau 0.01 |

The machine-readable report records every candidate, seed, runtime, split,
metric, artifact path and SHA-256:
[`rl_tuning_vessel_activity_10k.json`](rl_tuning_vessel_activity_10k.json).
The adjacent model ZIP files are published so the recorded hashes can be
verified after cloning.

## Claim boundary

- This report is valid evidence that all four RL learners execute real fitting,
  validation-only selection and held-out multi-seed evaluation.
- Ten thousand steps is still a short training budget. Do not cite this report
  as convergence or production readiness.
- Production dispatch remains disabled. Port telemetry, equipment calibration,
  shadow operations and operator authorization are still required.
