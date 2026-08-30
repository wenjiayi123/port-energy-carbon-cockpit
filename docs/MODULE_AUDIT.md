# Module audit

| Module | Current driver | Status and boundary |
|---|---|---|
| RL training | Stable-Baselines3 + Gymnasium v1–v6 | real learner steps, callbacks, checkpoints, pause/resume/stop; v6 adds 106 causal observations and 16 continuous policy outputs |
| RL progress | `model.num_timesteps` and elapsed wall time | no timer-derived progress |
| Hyperparameter selection | declared search space, `train` fit and `validation` ranking | `test` is one-way final evidence only |
| Policy test | held-out `test` split | trajectory rendering only after training |
| Baselines | PPO, SAC, TD3, DQN, MPC+OR | v6 selected PPO and completed 3×50,000-step final seeds; global result is `no_rl_policy_admitted`, MPC+OR also had 10 peak-safety violations, while crane-task and truck-flow gains remain offline domain challengers; DQN is historical v1–v5 only |
| Throughput | Port of Los Angeles 2020–2025 official monthly public data | hourly shape is deterministic, not observed telemetry |
| Electricity price | U.S. EIA California commercial monthly average | regional proxy converted at declared FX, not terminal tariff |
| Grid carbon | EPA eGRID CAMX | public factor; dataset records conversion and source |
| Energy/carbon accounting | environment transition ledger | Scope 1 auxiliary fuel and location-based Scope 2 are separate; market-based Scope 2 stays unavailable without contractual evidence |
| Data quality | schema, provenance, unit, duplicate, missing-value, and finite-value gates | score and package hash are exposed to API/UI |
| Data shift | train/test standardized mean difference | offline review signal; timestamped production drift still requires a live adapter |
| Public benchmark report | recomputed MPC/full-shore fixed-resource comparison with data/code hashes | offline scenario KPI, not field KPI or RL convergence |
| Carbon market | user-entered carbon price and scenario quota | scenario analysis, not an exchange market feed |
| IMO/EEXI indicators | unavailable in default dataset | not calculated without vessel capacity, distance, engine, speed, and fuel-consumption evidence |
| Dashboard charts | API test trajectories | no hard-coded KPI fallback series |
| Training history | persisted metrics JSONL/checkpoints | no fabricated convergence curve |
| Model registry | manifests, dataset/artifact hashes, test and verification evidence | offline lifecycle stages; production eligibility is always false |
| API security | production API keys and viewer/operator/admin roles | development may opt out; internet deployments still require per-user SSO |
| Audit and observability | request IDs, structured logs, mutation JSONL, health, readiness, Prometheus metrics | central retention/export is deployment-owned |
| Supply chain | pinned CI actions, audits, CodeQL, dependency review, Dependabot, Scorecard | branch protection and signed releases are enabled after GitHub publication |
| Weather/sea state | deterministic public-anchor supplement in v3–v5 | scenario input only; UI and replacement gate keep live weather/navigation unverified |
| Vessel identity/AIS | none in default dataset | public aggregate test-step identifiers only |
| Berth/TOS plan | abstract environment berth step | not presented as a live berth plan |
| Yard occupancy | advisory joint-planning contract | requires real box-group inventory, slots and TOS receipts before site use |
| AGV batteries/charging | v5 fleet/SOC/demand/departure/charger model and hard departure-energy projection | deterministic engineering supplement, not vehicle telemetry; site replacement requires per-vehicle/task/BMS evidence |
| Reefer flexibility | v5 connected-count/load/thermal-margin model and hard thermal shield | deterministic engineering supplement, not reefer telemetry; critical temperature safety cannot be traded by reward |
| Building flexibility | v5 critical/flexible load split and critical-load floor | declared engineering scenario; production requires building-automation feeder mapping |
| Demand response | v5 event/target/window action plus non-delivery ledger | scenario contract only; commercial service validates real baseline, meter and settlement receipts |
| Equipment health/maintenance | v5 crane/yard risk, health and maintenance envelope | modeled condition signal; production requires PLC/condition-monitoring identity and receipts |
| Renewable mix | eGRID factor plus v5 causal renewable-availability forecast | supplement is declared scenario data, not a measured generation or contract mix |
| Xiaoyi AI | optional local HTTP connector | unavailable connector falls back to a clear offline message |
| Godot sailing simulator | optional local connector | separate visualization process, not training evidence |
| Business ownership | 27-domain v6 machine-readable responsibility matrix | 16 domains use RL or hybrid strategy, one uses pure control/physics, and ten remain deterministic governance/authority/safety |
| Dispatch | dry-run packet | no direct production equipment control; external instruction gateway and PLC interlocks remain site-owned |

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
