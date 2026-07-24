# Threat model

## Assets

- Training datasets, metadata, source lineage, and hashes.
- Model artifacts, checkpoints, evaluations, and verification records.
- Operator actions, audit records, API keys, and deployment configuration.
- Port operational data when an external adapter is added.

## Trust boundaries

The browser, reverse proxy, API process, run-volume storage, external port adapters, and optional
Xiaoyi/simulator integrations are separate trust zones. The included benchmark has no authority
to command production equipment.

## Principal threats and controls

| Threat | Built-in control | Residual requirement |
| --- | --- | --- |
| Unauthorized training or linkage action | Mutation role gate and API key | Use SSO and per-user roles in production |
| Dataset poisoning or silent replacement | Schema checks and package SHA-256 | Signed ingestion and source reconciliation |
| Model artifact replacement | Artifact SHA-256 and registry gate | Signed releases and protected artifact store |
| Test leakage | Explicit train/validation/test split and training-only environment | Independent data review |
| Fabricated operational telemetry | Missing values remain unavailable | Verified TOS/EMS contracts |
| Secret leakage | Keys are environment-only and bodies are excluded from logs | Managed secret store and rotation |
| Repudiation | Request IDs and mutation audit JSONL | Central append-only logging and retention |
| Unsafe automated dispatch | Production eligibility hard-coded false | Human approval plus independent interlock |
| Dependency compromise | Pinned actions, audits, CodeQL, Dependabot, Scorecard | Protected branches and signed releases |
| Denial of service | Body limit and proxy timeouts | Rate limiting, quotas, autoscaling, and WAF |

## Logging rules

Logs include timestamp, request ID, method, path, status, role, client address, and duration.
Request bodies, API-key values, raw datasets, and model parameters are not written to access or
audit logs. Production deployments should forward logs to an append-only store and define a
retention and access policy.

## Non-goals

The repository does not implement vessel navigation safety, PLC control, electrical protection,
carbon-registry settlement, personal-data processing, or regulatory assurance. Those functions
must remain outside the benchmark boundary until separately engineered and certified.
