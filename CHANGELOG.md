# Changelog

All notable project changes are documented here.

## [Unreleased]

## [0.3.0] - 2026-08-08

### Added

- Per-adapter signed port snapshot envelopes with SHA-256 payload integrity,
  freshness, units, schema, monotonic sequence and replay protection.
- Persisted read-only integration readiness derived from validated evidence,
  with raw operational values excluded from local state.
- Dataset landing-readiness grading that separates expanded CSV rows from
  independent official source anchors and terminal calibration evidence.
- Causal persistence forecasts for all new training/evaluation jobs, preventing
  future held-out rows from entering observations or planning.
- Six-step risk-aware MPC deployment safety layer, paired bootstrap confidence
  intervals, CVaR tail metrics and deterministic stress tests.
- Tamper-evident mutation audit hash chaining, request body limits and a
  per-process rate-limit backstop.
- Patched frontend transitive dependency overrides, an audited cryptography
  extra and an optional neural-RL runtime separated from the integration plane.

### Changed

- `auto:latest` now fails closed unless a substantial policy has persisted
  `verified` admission evidence; blocked policies cannot silently reach the dashboard.
- Policy admission now checks causal forecasting, at least 30 held-out windows,
  confidence-bound non-regression and carbon/cost tail-risk non-regression.
- The cockpit exposes landing-data grade and live adapter readiness separately
  from the existing offline data-quality score.
- The original 0.2.0 reports, learner artifacts and resume-safe metrics remain
  frozen and independently verifiable.

## [0.2.0] - 2026-07-25

### Added

- Port LA 2020–2024 vessel-activity enhanced package with 1,238 official daily rows,
  43,848 canonical hours, source PDF hashes, declared corrections and quality codes.
- Layered v2/v3 environment contracts for port activity, weather/navigation,
  equipment availability, berth/grid limits, shore compatibility and renewables.
- Fail-closed Los Angeles, Rotterdam and Singapore live-port scenario templates.
- Five-algorithm cockpit matrix, Xiaoyi Q-style training advisor and browser-verified
  button-to-gateway evidence screenshots.
- Multi-seed 10k artifacts for PPO/SAC/TD3/DQN and a preserved 100k TD3 rejection
  package with held-out metrics and model hashes.
- Dataset quality scoring and train/test distribution-shift evidence.
- Explicit Scope 1 and location-based Scope 2 reporting with an unavailable market-based field.
- Data-driven governance and constraint alerts in the dashboard.
- Request IDs, API-key role gates, security headers, structured access logs, and mutation audit logs.
- Liveness, readiness, Prometheus metrics, and an offline model registry with artifact hashes.
- Non-root hardened containers and open-source supply-chain workflows.
- Data card, model card, threat model, and production-readiness gate.

### Changed

- New training defaults use the vessel-activity enhanced package while preserving the
  original 52,608-hour evidence baseline and benchmark.
- Scenario/data/environment mismatches now fail closed; smoke runs and safe-but-regressive
  policies cannot silently replace the publishable dashboard baseline.
- API and carbon-accounting model version advanced to 0.2.0 / 1.1.
- Docker Compose now binds to loopback and requires a production operator key.

## [0.1.0] - 2026-07-20

- Initial public benchmark: four executable RL algorithms, constrained MPC, public dataset,
  non-rendering training, held-out trajectory evaluation, and React/FastAPI cockpit.
