# Changelog

All notable project changes are documented here.

## [Unreleased]

## [0.2.0] - 2026-07-21

### Added

- Dataset quality scoring and train/test distribution-shift evidence.
- Explicit Scope 1 and location-based Scope 2 reporting with an unavailable market-based field.
- Data-driven governance and constraint alerts in the dashboard.
- Request IDs, API-key role gates, security headers, structured access logs, and mutation audit logs.
- Liveness, readiness, Prometheus metrics, and an offline model registry with artifact hashes.
- Non-root hardened containers and open-source supply-chain workflows.
- Data card, model card, threat model, and production-readiness gate.
- Inline Chinese/English project narrative, original visual assets, and asset provenance records.

### Changed

- API and carbon-accounting model version advanced to 0.2.0 / 1.1.
- Docker Compose now binds to loopback and requires a production operator key.
- HTTP training and evidence routes now accept registered dataset/run identifiers only.

## [0.1.0] - 2026-07-20

- Initial public benchmark: four executable RL algorithms, constrained MPC, public dataset,
  non-rendering training, held-out trajectory evaluation, and React/FastAPI cockpit.
