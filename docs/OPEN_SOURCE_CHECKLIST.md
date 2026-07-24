# Open-source checklist

- [x] MIT license, contribution guide, security policy, and environment example.
- [x] Public dataset attribution, units, assumptions, train/validation/test split, and SHA-256 evidence.
- [x] Generated runs, model binaries, release archives, and private submission material ignored.
- [x] Four executable RL algorithms and one executable control baseline.
- [x] No rendering during fitting; held-out rendering only after completion.
- [x] Executable hyperparameter selection keeps test inaccessible until final-seed evaluation.
- [x] Reproducible offline benchmark report carries evidence labels and data/code hashes.
- [x] Dashboard and API tests assert dataset provenance and measured trajectory fields.
- [x] Missing production modules are visibly marked unavailable.
- [x] Initialize a local Git repository on the `main` branch.
- [x] Public repository exists at `wenjiayi123/port-energy-carbon-cockpit` (verified 2026-07-24).
- [ ] Configure this local checkout's remote and push the current verified changes.
- [x] Review the author/contact text in `LICENSE` and `SECURITY.md`.
- [ ] Run secret scanning and inspect `git status --ignored` before the first push.
- [x] Add CI for backend tests, dataset validation, and the frontend production build.
- [x] Add pinned CI actions, CodeQL, dependency review, Dependabot, Scorecard, and dependency audits.
- [x] Add API authentication gates, mutation audit logging, security headers, health, and metrics.
- [x] Add data/model cards, threat model, changelog, citation metadata, and governance policy.
- [x] Harden containers with non-root users, read-only filesystems, dropped capabilities, and loopback ports.
- [ ] Publish benchmark models/results separately from the source tree.
- [ ] Confirm private vulnerability reporting, branch protection, and required CI checks on GitHub.
- [x] Add the final GitHub repository URL to `CITATION.cff` after the repository name is chosen.

Suggested first-push commands:

```bash
git add .
git status --short
git commit -m "Open-source dataset-backed port energy-carbon RL cockpit"
```

Do not run `git add -f` on ignored artifacts or private submission folders.
