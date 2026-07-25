# Production readiness

This repository is production-shaped but intentionally not production-authorized. It is an
offline benchmark and decision-support cockpit. Passing every built-in gate does not enable
autonomous equipment control.

## Implemented gates

| Area | Implemented evidence | Default state |
| --- | --- | --- |
| Carbon accounting | Scope 1 auxiliary fuel and location-based Scope 2 are reported separately | Active |
| Market-based Scope 2 | Field and quality contract exist | Unavailable until contractual instruments are supplied |
| Dataset governance | Schema, finite values, split isolation, provenance, units, package hash, quality score | Enforced |
| Port scenario contract | v3 weather, vessel, berth, equipment, grid, shore compatibility and renewable observations | Fail-closed |
| Distribution checks | Train/test standardized mean-difference report | Advisory or blocking at high shift |
| Model lifecycle | Candidate, validated offline, verified offline, and blocked stages | Production eligibility always false |
| Artifact integrity | SHA-256 for newly trained model/controller artifacts | Enforced for new runs |
| Runtime security | Production API-key validation, role gates, security headers, request IDs | Required in production |
| Auditability | JSON access logs and mutation-only audit log | Active |
| Operations | Liveness, readiness, and Prometheus-format metrics | Active |
| Container safety | Non-root users, read-only filesystems, dropped capabilities, loopback binding | Active in Compose |
| Supply chain | Pinned CI actions, dependency audit, CodeQL, Dependabot, dependency review, Scorecard | Configured |

## External evidence required before a real port deployment

1. TOS, EMS, berth/vessel, equipment, weather/navigation and shore-compatibility adapters
   that emit the v3 canonical schema with timestamped source identifiers.
2. Calibrated terminal capacities, load curves, delay costs, and safety limits approved by the port.
3. Meter and fuel records with lineage, correction policy, retention, and reconciliation procedures.
4. Supplier-specific or contractual electricity instruments for market-based Scope 2 reporting.
5. Identity-aware access control, secret management, TLS termination, backup, and log retention.
6. Shadow-mode validation, operator acceptance testing, rollback drills, and an independent interlock.
7. Legal review of source licenses, carbon-market rules, privacy, critical-infrastructure obligations,
   and the named port's operational procedures.

The production gate remains closed until these items are supplied and independently reviewed.

## Health and evidence endpoints

- `GET /api/health/live`: process liveness only.
- `GET /api/health/ready`: dataset, run storage, and RL-runtime readiness.
- `GET /api/metrics`: Prometheus text metrics.
- `GET /api/rl/registry`: model lifecycle, data hash, artifact hash, drift, and test status.
- `GET /api/scenarios`: per-port dataset, observation and adapter readiness.
- `GET /api/scenarios/contract`: common objectives, observations, actions and hard constraints.
- `POST /api/rlops/policies/verify`: persists split, hash, safety and carbon/cost
  non-regression checks; a safe but underperforming policy is marked `blocked`.

## Deployment modes

- `development`: authentication may be disabled for localhost development.
- `production`: the backend refuses to start unless `API_AUTH_MODE=api_key` and at least one
  key of 24 or more characters is configured.

For an internet-facing deployment, place the dashboard behind an identity-aware reverse proxy.
The shared API-key mode is suitable for a controlled internal benchmark, not as a substitute for
enterprise SSO, per-user authorization, or a hardware safety interlock.
