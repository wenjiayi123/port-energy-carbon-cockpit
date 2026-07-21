# Module audit

| Module | Current driver | Status and boundary |
|---|---|---|
| RL training | Stable-Baselines3 + Gymnasium | real learner steps, callbacks, checkpoints, pause/resume/stop |
| RL progress | `model.num_timesteps` and elapsed wall time | no timer-derived progress |
| Policy test | held-out `test` split | trajectory rendering only after training |
| Baselines | PPO, SAC, TD3, DQN, MPC | exactly four RL plus one control baseline |
| Throughput | Port of Los Angeles 2025 monthly public data | hourly shape is deterministic, not observed telemetry |
| Grid carbon | EPA eGRID CAMX | public factor; dataset records conversion and source |
| Energy/carbon accounting | environment transition ledger | Scope 1 auxiliary fuel and location-based Scope 2 are separate; market-based Scope 2 stays unavailable without contractual evidence |
| Data quality | schema, provenance, unit, duplicate, missing-value, and finite-value gates | score and package hash are exposed to API/UI |
| Data shift | train/test standardized mean difference | offline review signal; timestamped production drift still requires a live adapter |
| Carbon market | user-entered carbon price and scenario quota | scenario analysis, not an exchange market feed |
| IMO/EEXI indicators | unavailable in default dataset | not calculated without vessel capacity, distance, engine, speed, and fuel-consumption evidence |
| Dashboard charts | API test trajectories | no hard-coded KPI fallback series |
| Training history | persisted metrics JSONL/checkpoints | no fabricated convergence curve |
| Model registry | manifests, dataset/artifact hashes, test and verification evidence | offline lifecycle stages; production eligibility is always false |
| API security | production API keys and viewer/operator/admin roles | development may opt out; internet deployments still require per-user SSO |
| Audit and observability | request IDs, structured logs, mutation JSONL, health, readiness, Prometheus metrics | central retention/export is deployment-owned |
| Supply chain | pinned CI actions, audits, CodeQL, dependency review, Dependabot, Scorecard | branch protection and signed releases are enabled after GitHub publication |
| Weather/sea state | none | UI says not connected |
| Vessel identity/AIS | none in default dataset | public aggregate test-step identifiers only |
| Berth/TOS plan | abstract environment berth step | not presented as a live berth plan |
| Yard occupancy | none | UI says unavailable; no invented percentage |
| AGV batteries/charging | none | UI says unavailable; yard vehicle action remains abstract |
| Renewable mix | aggregate eGRID factor only | no synthetic solar/wind share |
| Xiaoyi AI | optional local HTTP connector | unavailable connector falls back to a clear offline message |
| Godot sailing simulator | optional local connector | separate visualization process, not training evidence |
| Dispatch | dry-run packet | no direct production equipment control |

## Recommended production adapters

1. TOS: vessel calls, berth compatibility, crane availability, moves, and actual timestamps.
2. EMS/SCADA: meter-level grid/shore-power load, equipment energy, tariffs, and peak limits.
3. AIS/weather: immutable external snapshots with timestamps and licensing metadata.
4. Equipment systems: yard vehicle/AGV state, charging availability, maintenance, and safety locks.
5. Production governance: identity-aware SSO, signed ingestion/artifacts, shadow deployment,
   rollback, central append-only audit retention, operator approvals, and an independent interlock.

Every adapter should preserve source timestamps, units, quality flags, and a
snapshot hash. Missing measurements must remain missing rather than replaced by
presentation values.
