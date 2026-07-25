# TD3 100k enhanced-dataset run

Evidence label: `OFFLINE_RL_EXPERIMENT_REJECTED_FOR_POLICY_SELECTION`

This directory preserves a real 100,000-step TD3 run on
`port_la_2020_2024_vessel_activity_hourly`. Training used only the `train`
split with `render_mode=None`; the final evaluation used 48 held-out test
episodes and 1,152 test steps.

## Integrity and safety result

- Run ID: `rl-20260725-233109-6ac68e`
- Duration: 3,557.36 seconds
- Dataset package SHA-256:
  `fbb3d1c34ccad61214119b600f09e8a6c37c13826fad6e4dde0c33cdc821758e`
- Model SHA-256:
  `d2b5e4881ef3753b3be02df45dd84951bf0d1507d92adb1c708d4a90caf3efa6`
- Modeled safety violations: 0
- Modeled constraint success rate: 100%

`verification.json` reports `blocked`. Split, dataset, artifact and
safety-integrity checks passed, while four carbon/cost non-regression checks
failed.

## Policy-selection result

The policy is rejected for use as a positive performance claim:

- Carbon reduction versus the constrained control comparator: **-9.806%**
- Scenario-cost saving versus the constrained control comparator: **-10.293%**
- Peak reduction versus the constrained control comparator: **-2,884.196 kW**
- Carbon reduction versus the fixed-resource comparator: **-0.029%**
- Scenario-cost saving versus the fixed-resource comparator: **-1.232%**
- Fixed-comparator peak change: **+17.993%**
- Fixed-comparator throughput change: **0.000%**

Negative reduction/saving means the trained policy was worse on that metric.
This run is retained to prove that the project preserves unfavorable results
and applies a real selection boundary instead of reporting only favorable
curves. Use the validation-selected multi-seed report for algorithm comparison,
and keep the verified MPC reports as the current publishable performance
evidence.

## Files

- `config.json`: exact submitted configuration and package hashes.
- `manifest.json`: run lifecycle and model artifact hash.
- `metrics.jsonl`: measured learner callbacks and validation checkpoints.
- `model.zip`: final Stable-Baselines3 model.
- `evaluation.json`: held-out trajectory and metrics.
- `verification.json`: integrity, split, safety and manual-boundary checks.
