# RL and constrained-control pipeline

## Data boundary

The default `port_la_2020_2025_hourly` package contains 52,608 contiguous hourly rows.
Port of Los Angeles monthly TEU is allocated to hours with a disclosed normalized profile.
Hourly LADWP demand and consumed-carbon intensity come from EIA's Hourly Electric Grid
Monitor; 51,726 hours are reported and 882 missing hours use a quality-coded
month-hour median. California commercial monthly electricity prices provide the monthly
mean, while disclosed LADWP time-of-use periods shape the intraday proxy.

Splits are chronological and immutable: 2020–2023 train (35,064 hours), 2024 validation
(8,784), and 2025 held-out test (8,760). Observation normalizers are fit on `train` only.
Candidate selection touches validation only. The deterministic benchmark samples 48
uniformly spaced 24-hour windows from validation and test and persists every start index.

## Environment

`PortEnergyDispatchEnv-v1` exposes 19 normalized observations:

1. current demand, grid carbon and electricity price;
2. three-hour demand, carbon and price forecast features; v0.3.0 new runs use a
   causal persistence forecast and never fill them from later held-out rows;
3. queue, grid headroom, storage SOC and prior storage action;
4. cyclical hour and month encodings;
5. import/export cargo shares;
6. accumulated normalized carbon and delay indicators (context features, not externally assigned budgets).

The continuous action is `[shore_power_ratio, crane_fleet_ratio, yard_fleet_ratio,
battery_power]`. Fleet ratios are active fractions of declared full fleet capacity, not
equipment overclocking. DQN uses 3 levels for each dimension, giving 81 explicit actions.
An action shield clips battery power to the grid limit, SOC bounds and the terminal-SOC
reachability envelope.

At each one-hour step the environment computes throughput, queue and delay, terminal
load, grid and auxiliary-fuel emissions, energy/delay/degradation cost, peak violation,
SOC and terminal-SOC compliance. Storage is modeled as an 18 MWh/5 MW system with
10%–90% SOC bounds and 95% charge/discharge efficiencies; these and terminal physical
coefficients are declared benchmark assumptions, not Port-published equipment data.

The reward is the normalized weighted sum of throughput and shore-power benefits minus
scenario cost, carbon, squared peak loading, delay, safety and storage-degradation terms.
Weights are validated and normalized. Three predeclared weight profiles are evaluated as
sensitivity evidence; the final test result is not used to select among them.

## Five methods

| ID | Family | Space | Implementation |
|---|---|---|---|
| `ppo` | RL | continuous | Stable-Baselines3 PPO |
| `sac` | RL | continuous | Stable-Baselines3 SAC |
| `td3` | RL | continuous | Stable-Baselines3 TD3 with dimension-matched exploration noise |
| `dqn` | RL | 81 discrete actions | Stable-Baselines3 DQN |
| `mpc` | control theory | constrained grid | four-step, width-four beam-search MPC with terminal-SOC value |

All RL algorithms run the real `learn()` path. Training uses `split=train` and
`render_mode=None`; validation rollouts are non-rendering. Trajectory records are produced only
after loading a completed artifact into the held-out test environment. Short runs are labelled
`RL_SMOKE_WIRING_ONLY` and do not establish convergence or superiority.

## Evidence and promotion

Each run records resolved configuration, seed, data/code hashes, measured learner steps,
callback metrics, checkpoints, final artifact, held-out evaluation and verification result.
The reproducible MPC report is separately labelled
`OFFLINE_SCENARIO_BENCHMARK_NOT_FIELD_KPI`.

Passing offline verification keeps `production_eligible=false`. Port deployment would still
require calibrated TOS/EMS/meter data, tariff contracts, shadow-mode validation, identity and
approval controls, rollback drills and an independent hard safety interlock.
