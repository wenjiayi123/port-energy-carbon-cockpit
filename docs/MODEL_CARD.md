# Model card: PortEnergyDispatchEnv baselines

## Models

The benchmark exposes PPO, SAC, TD3, and DQN through Stable-Baselines3, plus a three-step
finite-horizon constrained MPC beam-search baseline. Algorithms share the same environment,
dataset package, constraints, and held-out evaluation path.

## Intended use

- Offline research, reproducibility, algorithm comparison, and operator decision support.
- Port transfer by replacing the canonical dataset and calibrated environment metadata.

## Prohibited use

- Autonomous production dispatch, safety-critical control, carbon-registry settlement, or claims
  of regulatory assurance without independent validation.

## Training and evaluation

Training uses only the `train` split with `render_mode=None`. Periodic validation also uses the
training split without rendering. After fitting completes, evaluation uses only `test` and may
render a trajectory. Learner progress comes from measured callbacks, not a timer.

## Evidence

Each new run records configuration, random seed, dataset package SHA-256, callback metrics,
checkpoints, model/controller artifact SHA-256, held-out evaluation, and optional persisted
verification. `GET /api/rl/registry` reports lifecycle stage and gate status.

## Limitations and risks

The default monthly public dataset has low temporal and operational resolution. Results are
sensitive to scenario assumptions, reward weights, capacity calibration, test-period shift, and
the simplified environment. An offline win over the MPC baseline does not demonstrate safe or
effective performance at a real port.

## Production gate

`production_eligible` is always false in this repository. A real deployment requires signed data,
port-specific shadow testing, operator approval, rollback, and an independent safety interlock.
