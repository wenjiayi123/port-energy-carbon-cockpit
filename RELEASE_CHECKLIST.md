# Release checklist / 发布清单

## Source and evidence / 源码与证据

- [ ] `make test`, `make build`, and `make validate` pass from a clean checkout.
- [ ] Ruff, frontend audit, and Linux dependency audit pass.
- [ ] Generated runs, model binaries, audit logs, private datasets, submission materials, and local integrations are absent from Git.
- [ ] README screenshots come from the bundled offline benchmark and show the production boundary.
- [ ] Dataset metadata, attribution, hashes, units, assumptions, and split remain accurate.
- [ ] `python -m app.rl.benchmark verify reports/offline_benchmark_v3.json` passes.
- [ ] `make verify-runtime-evidence` passes and the runtime model/data/report SHA-256 values match.
- [ ] Runtime field classification, energy balance, SOC/temperature/capacity limits, fault injection,
  dual approval, idempotency, receipt, rollback and audit-chain tests pass.
- [ ] Browser acceptance completes one current-input forecast → recommendation → safety projection →
  dual approval → simulation execution → KPI feedback → rollback path and one fail-closed loss path.
- [ ] `GET /api/evidence/history` exposes archived/champion/current/blocked evidence without local paths.
- [ ] Resume/release claims retain the offline-scenario comparator qualifier.

## GitHub sync and review / GitHub 同步与复核

- [ ] Configure the local remote and push this verified source state.
- [ ] Confirm the public repository displays the new benchmark and resume-claim boundaries.
- [ ] CI and container jobs pass on the default branch.
- [ ] Repository description, topics, license, Discussions, Issues, and vulnerability alerts are configured.
- [ ] No secret, email, local absolute path, or proprietary artifact appears in the Git history.
- [ ] Draft release notes describe the offline benchmark boundary.
- [ ] Do not push, create a PR or publish a release until the owner explicitly approves the local result.

## Public repository controls / 公开仓库控制

- [ ] Enable branch protection, secret scanning, private vulnerability reporting, CodeQL, Dependency Review, and Scorecard where the plan supports them.
- [ ] Upload `docs/assets/social-preview.png` as the repository social preview if prepared.
- [ ] Confirm public badges, links, Discussions, issue forms, and citation metadata render correctly.
- [ ] Publish model/results only as separately reviewed release artifacts.
