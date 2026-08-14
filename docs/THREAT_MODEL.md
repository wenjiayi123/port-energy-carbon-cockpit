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
| Runtime action bypass | Four-field action whitelist, safety projection, dual distinct approvals, requester self-approval prohibition | Independent execution channel, PLC interlock and site SOP |
| Duplicate command or retry | Required business idempotency keys with persisted replay results | Gateway-level idempotency retention and device sequence acknowledgements |
| Forged simulated/live identity | Every runtime field has exclusive measured/simulated/derived classification and source ID | Port-owned adapter certificates and source reconciliation |
| Simulator or communication loss | Quality gate blocks forecast/decision; dispatch and production authority stay false | Redundant live sources, watchdog and fail-safe device mode |
| Dependency compromise | Pinned actions, audits, CodeQL, Dependabot, Scorecard | Protected branches and signed releases |
| Denial of service | Body limit and per-process sliding-window backstop | Distributed quotas, autoscaling, reverse-proxy timeouts, and WAF |
| Snapshot spoofing or replay | Per-adapter HMAC, payload hash, freshness, snapshot ID and monotonic sequence | Managed key rotation, source mTLS and port SIEM correlation |
| Local audit alteration | SHA-256 chained mutation records and integrity endpoint | Port-owned append-only/WORM export and retention policy |

## Logging rules

Logs include timestamp, request ID, method, path, status, role, client address, and duration.
Request bodies, API-key values, raw datasets, and model parameters are not written to access or
the generic mutation log. The runtime decision record intentionally retains its whitelisted
recommended/projected action, approver IDs, receipt, hashes and KPI delta; it does not retain API
keys or raw external telemetry. Production deployments should forward logs to an append-only
store and define a retention and access policy.

## Non-goals

The repository does not implement vessel navigation safety, PLC control, electrical protection,
carbon-registry settlement, personal-data processing, or regulatory assurance. Those functions
must remain outside the benchmark boundary until separately engineered and certified.
