# Contributing

1. Create a focused branch and keep generated model artifacts out of Git.
2. Run `make test`, `make build`, and `make validate` before opening a pull request.
3. New datasets must include train/test splits, a metadata JSON file, source URLs,
   licensing notes, units, assumptions, and a reproducible SHA-256 hash.
4. New algorithms must report measured learner steps and metrics. Timer-derived
   progress, fabricated KPI fallbacks, and test-set use during fitting are not accepted.
5. Production connectors must default to read-only or dry-run and document the
   authentication and human-confirmation boundary.
6. Never commit credentials, raw private port data, generated runs, or model binaries.
7. Update the data/model card, threat model, or changelog when the corresponding contract changes.

Security reports must follow `SECURITY.md`; do not disclose vulnerabilities in an issue or pull request.

By contributing, you agree that your contribution is licensed under the MIT License.
