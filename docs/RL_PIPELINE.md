# RL pipeline

## Data boundary

`PortDataset` validates the canonical CSV before any learner starts. A valid
dataset must contain non-negative numeric values and at least one `train` and one
`test` row. CSV, metadata, and combined dataset-package SHA-256 values are
copied into every run config; evaluations use the combined hash so changing a
physical parameter invalidates prior evidence.

The default split is January–September 2025 for training and October–December
2025 for held-out testing. The test split is never passed to `model.learn`.

## Environment

`PortEnergyDispatchEnv-v1` exposes a 12-value normalized observation:

1. hourly demand and queue;
2. grid carbon, electricity price, and fuel price;
3. cyclical hour and normalized hour;
4. import/export shares;
5. accumulated carbon and delay budgets.

Continuous actions control shore-power ratio, crane ratio, and yard-vehicle
ratio. DQN uses the Cartesian product of three levels for each control, giving
27 explicit actions.

At each one-hour step the environment computes:

- throughput as the minimum of demand, dataset-calibrated crane capacity, and yard capacity;
- queue and delay from unmet demand;
- grid load from base, crane, yard, and shore-power loads;
- auxiliary fuel from shore-power demand not supplied by the grid;
- grid carbon as `grid_kWh * grid_factor`;
- fuel carbon as `fuel_liter * 2.68 kgCO2e/liter`;
- energy and delay cost using the dataset's declared scenario prices;
- violations when grid load or delay exceeds the limits declared by the dataset.

Physical coefficients are resolved in this order: current CSV row, adjacent
metadata `environment_parameters`, then the documented public-benchmark
defaults. `sequential_rows` datasets advance through immutable TOS/EMS rows;
aggregate `profiled_period` datasets use the disclosed deterministic hourly
profile. This lets a port replace the dataset package without modifying the
learner or reward implementation.

The reward is a normalized weighted combination of throughput, carbon, shore
power, cost, delay, safety, and peak-load terms. Reward weights are validated and
normalized by the environment.

## Five baselines

| ID | Family | Space | Implementation |
|---|---|---|---|
| `ppo` | RL | continuous | Stable-Baselines3 PPO |
| `sac` | RL | continuous | Stable-Baselines3 SAC |
| `td3` | RL | continuous | Stable-Baselines3 TD3 |
| `dqn` | RL | 27 discrete actions | Stable-Baselines3 DQN |
| `mpc` | control theory | 27-point grid | three-step constrained beam-search MPC |

These algorithms were chosen because Stable-Baselines3 officially supports PPO,
SAC, TD3, and DQN and documents their action-space compatibility. See the
[official algorithm table](https://stable-baselines3.readthedocs.io/en/md-doc/guide/algos.html).

## Train, validate, then render test

Training constructs the environment with `split=train` and `render_mode=None`.
The callback records measured learner steps, rate, logger metrics, validation
rollouts on the training partition without rendering, and real checkpoint files.
ETA is derived from measured `steps / elapsed time`; no fixed-duration timer is
used.

After completion, `/api/rl/simulate` loads the saved artifact, evaluates every
row in the held-out test split, and constructs a separate environment with
`render_mode=trajectory`. Only this stage produces visualization records.

Run evidence is stored under `backend/app/data/runs/<job-id>/`:

- `config.json`: resolved inputs and dataset hash;
- `metrics.jsonl`: callback and non-rendering validation metrics;
- `checkpoints/*.zip`: measured-step checkpoints;
- `model.zip` or `mpc_policy.json`: final artifact;
- `manifest.json` and `state.json`: lifecycle evidence;
- `evaluation.json`: held-out metrics and rendered trajectories.

Run artifacts are intentionally ignored by Git. Publish benchmark results in a
release or experiment registry instead of committing binary models.

## Production promotion boundary

The verification endpoint checks the test split, dataset hash, and safety
violations. Passing verification still enables dry-run only. A production
deployment needs terminal-specific constraints, authentication, audit logging,
shadow evaluation, human approval, and an independent safety interlock.
