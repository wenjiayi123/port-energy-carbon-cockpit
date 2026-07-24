# Security policy

## Supported versions

Security fixes are applied to the latest release and the default branch.

## Reporting a vulnerability

Use GitHub private vulnerability reporting after the repository is published. Until that channel
is enabled, contact the maintainer through a private channel listed on the maintainer's GitHub
profile. Do not open a public issue containing exploit details, credentials, private port data, or
the location of an exposed deployment.

Include the affected version, reproduction steps, expected impact, and any proposed mitigation.
You should receive an acknowledgment within seven days. No bounty is currently offered.

This repository is an offline decision-support benchmark. Production dispatch remains disabled
and must not be connected directly to equipment without identity-aware authorization, centralized
audit logging, port-specific safety review, rollback, and an independent operational interlock.

See `docs/THREAT_MODEL.md` for trust boundaries and residual requirements.

## Platform note

PyTorch stopped publishing current wheels for Intel macOS after the 2.2 line. A clean Linux or
Apple Silicon installation resolves a current PyTorch release; Intel macOS may resolve the legacy
2.2.2 wheel and is therefore development-only. Do not load untrusted model files on that platform,
and do not use it for a production deployment. CI and the production container audit the Linux
dependency set.
