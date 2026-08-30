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

## Additive v5 operational-flex contract

`PortEnergyDispatchEnv-v5` preserves every earlier environment and artifact. It extends v4 to
73 observations and 10 continuous controls by adding AGV charging, reefer thermal flexibility,
building flexible load, demand response, equipment health/maintenance and shore-power reservation
state. DQN uses 243 curated coupled templates rather than the full 59,049-point Cartesian grid.

Reward terms cover carbon, shore power, cost, delay, safety, peak, storage terminal value, AGV
service, reefer safety, demand-response delivery and equipment-health exposure. Grid capacity,
battery reachability, AGV departure energy, reefer thermal safety and critical building load are
hard projections, not soft reward preferences. Authority release and physical dispatch remain
outside the action space.

See [the v5 contract](OPERATIONAL_FLEX_RL_V5.md). Its public-anchor package deliberately labels
AGV/reefer/building/demand-response/health fields as modeled supplements. A site export can replace
them through `scripts/prepare_port_dataset.py --column-map`, but training admission remains blocked
until the replacement-readiness API verifies independent measurement, signed source receipts,
lineage, calibration, 180-day shadow coverage, reconciliation and acceptance evidence.

## v6 layered hybrid policy

`PortEnergyHybridResidualEnv-v6` is continuous-only. PPO, SAC and TD3 emit ten
bounded residuals around a causal feasible controller plus six strategic
priorities. A deterministic solver turns the priorities into feasible JIT,
green-berth, crane-task, yard-slot, truck-gate and maintenance allocations.
DQN remains available only for the versioned v1–v5 discrete contracts.

The 106-dimensional observation never reads a future dataset row. Seventeen
reward terms express business value inside the safe set; grid capacity, terminal
SOC reachability, AGV departure energy, reefer thermal safety, critical building
load, berth compatibility, crane precedence, yard/gate capacity and statutory
maintenance deadlines are hard projections.

Formal selection fits PPO/SAC/TD3 candidates on `train`, ranks on `validation`,
then trains three frozen final seeds. The test benchmark compares each seed with
causal four-step MPC plus deterministic operations projection. Every seed must
pass safety, value, 95% confidence and material RL-contribution gates; otherwise
the report retains `no_rl_policy_admitted`.

The frozen 2026-08-30 v6 run selected PPO candidate 1 and completed three
50,000-step seeds. All three learned policies were safe and materially different
from the controller, but none passed the global business-value gate. Cost, peak,
crane-task lateness and truck queueing improved consistently; carbon, throughput,
total delay, shore power and berth conflicts regressed. The MPC+OR comparator also
recorded ten peak-safety violations across 48 windows, so it remains a benchmark,
not an admitted control champion. The API exposes crane-task and truck-flow results
as offline domain challengers while keeping every production authority disabled.
