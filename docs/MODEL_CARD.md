# Model card: PortEnergyDispatchEnv baselines

## Models

The benchmark exposes PPO, SAC, TD3, and DQN through Stable-Baselines3, plus a four-step
finite-horizon constrained MPC beam-search baseline. Algorithms share the same environment,
dataset package, constraints, and held-out evaluation path.

## Intended use

- Offline research, reproducibility, algorithm comparison, and operator decision support.
- Port transfer by replacing the canonical dataset and calibrated environment metadata.

## Prohibited use

- Autonomous production dispatch, safety-critical control, carbon-registry settlement, or claims
  of regulatory assurance without independent validation.

## Training and evaluation

Training uses only the `train` split with `render_mode=None`. Hyperparameter selection uses the
independent `validation` split without rendering. After model selection completes, final
evaluation uses only `test` and may render a trajectory. Learner progress comes from measured
callbacks, not a timer.

## Evidence

Each new run records configuration, random seed, dataset package SHA-256, callback metrics,
checkpoints, model/controller artifact SHA-256, held-out evaluation, and optional persisted
verification. `GET /api/rl/registry` reports lifecycle stage and gate status.
The search space and selection contract live in `configs/rl_search_space.json`.
Short runs below 10,000 steps are labelled as wiring smoke evidence, not convergence.

## Limitations and risks

The default dataset has hourly EIA grid signals but monthly Port throughput anchors allocated
through a declared profile. Results remain sensitive to physical assumptions, reward weights,
capacity calibration, test-period shift, price construction and environment simplification.
An offline win does not demonstrate safe or effective performance at a real port.

The environment models storage SOC, power, efficiency, degradation and terminal-SOC constraints.
Those values are declared scenario assumptions, not verified Port equipment specifications;
do not claim field storage-utilization gains.

## Production gate

`production_eligible` is always false in this repository. A real deployment requires signed data,
port-specific shadow testing, operator approval, rollback, and an independent safety interlock.
