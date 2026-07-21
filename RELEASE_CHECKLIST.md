# Release checklist / 发布清单

## Source and evidence / 源码与证据

- [ ] `make test`, `make build`, and `make validate` pass from a clean checkout.
- [ ] Ruff, frontend audit, and Linux dependency audit pass.
- [ ] Generated runs, model binaries, audit logs, private datasets, submission materials, and local integrations are absent from Git.
- [ ] README screenshots come from the bundled offline benchmark and show the production boundary.
- [ ] Dataset metadata, attribution, hashes, units, assumptions, and split remain accurate.

## GitHub private review / GitHub 私有预审

- [ ] Repository visibility is `PRIVATE` until the owner approves publication.
- [ ] CI and container jobs pass on the default branch.
- [ ] Repository description, topics, license, Discussions, Issues, and vulnerability alerts are configured.
- [ ] No secret, email, local absolute path, or proprietary artifact appears in the Git history.
- [ ] Draft release notes describe the offline benchmark boundary.

## Public transition / 转为公开

- [ ] Owner manually changes visibility after final review.
- [ ] Enable branch protection, secret scanning, private vulnerability reporting, CodeQL, Dependency Review, and Scorecard where the plan supports them.
- [ ] Upload `docs/assets/social-preview.png` as the repository social preview if prepared.
- [ ] Confirm public badges, links, Discussions, issue forms, and citation metadata render correctly.
- [ ] Publish model/results only as separately reviewed release artifacts.
