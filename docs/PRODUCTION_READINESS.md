# Production readiness

This repository is production-shaped but intentionally not production-authorized. It combines
public-data-calibrated realtime simulation, offline benchmarks, and a decision-support cockpit.
Passing every built-in gate does not enable autonomous equipment control.

## Implemented gates

| Area | Implemented evidence | Default state |
| --- | --- | --- |
| Carbon accounting | Seven-source port inventory contract, legacy Scope 1 auxiliary fuel and location-based Scope 2 | Two scenario sources calculated; full inventory assurance blocked |
| Market-based Scope 2 | Field and quality contract exist | Unavailable until contractual instruments are supplied |
| Carbon assets and compliance | Program/account/lot/trade/cash/approval/reconciliation/retirement contract, 12 fail-closed gates, Ed25519 registry attestation and SHA-256 ledger chain | Scenario valuation only until externally authorized evidence is supplied; trade, cash movement and filing stay disabled |
| Energy and GHG management system | Version-locked ISO 50001:2018/Amd 1:2024 and ISO 14064-1:2018 references, 15 fail-closed PDCA/assurance gates, role segregation, inventory/M&V hash links, corrective-action closure and Ed25519 assurance | 0/15 until named site evidence is supplied; certification, verification opinion and filing claims always remain external |
| Joint operations-energy planning | Named vessel/berth/crane/yard/truck/reefer/shore-power/EMS contract, per-source Ed25519 signatures, 12 fail-closed gates, joint scheduling, storage optimization and hash receipt | 0/8 source domains and 0/12 gates on public aggregate data; advisory only even after a complete signed site package passes |
| Ship-port ecosystem collaboration | Seven independently signed domains and 15 fail-closed gates for JIT-arrival consent/performance, green-berth ranking, shore-power reservation/billing, alternative-fuel safety readiness, green port fees and shared abatement value | 0/7 source domains and 0/15 gates on public activity data; vessel speed, berth writeback, shore switching, bunkering, invoicing and money movement remain disabled |
| Enterprise platform and OT security | Executable OIDC EdDSA validation, named subjects, mapped roles and signed tenant selection plus nine independently signed domains and 20 gates for messaging/time-series durability, HA/failover, immutable offsite backup, restore RPO/RTO, WORM/SIEM, four mTLS boundaries, key rotation, OT zoning, remote access and independent safety interlocks | 0/9 source domains and 0/20 gates by default; the current runtime remains single-instance with local file state and a local hash chain, so enterprise cutover, certification and OT command authority remain false |
| Electrical network digital twin | Named buses/feeders/transformers/switches/sources, radial power flow, voltage/reactive/harmonics, thermal aging, N-1, islanding, Erlang-C charging queues, storage warranty, per-source Ed25519 signatures and 14 fail-closed gates | 0/6 source domains and 0/14 gates on public aggregate data; no switching, relay-setting, island or equipment authority |
| Algorithm production qualification | Six independently signed evidence domains and 15 fail-closed gates for multi-seed/four-season pairing, probabilistic calibration, OOD fallback, explanation fidelity, action reachability, P95/P99 latency, fault injection, human veto statistics, champion/challenger confidence intervals, safety non-regression and long shadow operation | 0/6 source domains and 0/15 gates by default; existing negative results remain visible, no new algorithm is recommended, and promotion/dispatch stay disabled |
| Dataset governance | Schema, finite values, split isolation, provenance, units, package hash, quality score | Enforced |
| Landing data grade | Independent source anchors, modeled-expansion ratio, v3 fields, event lineage and parameter calibration | Separately enforced from offline quality |
| Read-only live ingestion | Per-adapter HMAC, payload hash, schema/units, freshness, monotonic sequence and replay protection | Fail-closed |
| Realtime field contract | Per-field value, unit, event/ingest time, source, quality, confidence, classification, asset/site, schema and trace | Active in calibrated simulation; live adapter pending |
| Physical/operational simulation | Energy balance, transformer reserve, battery SOC/SOH/temperature/cycles, workload/service coupling and scenario injection | Deterministic simulation only |
| Current-input forecast | Train-only Ridge fit, validation-only alpha selection, held-out metrics and model/data hashes | Active; terminal load target is engineering-derived |
| Port scenario contract | v3 weather, vessel, berth, equipment, grid, shore compatibility and renewable observations | Fail-closed |
| Distribution checks | Train/test standardized mean-difference report | Advisory or blocking at high shift |
| Model lifecycle | Candidate, validated offline, verified offline, and blocked stages | Production eligibility always false |
| Shadow decision package | Policy/artifact hash, input digests, idempotency ID, expiry and frozen rollback target | Execution authorization always false |
| Runtime decision execution | MPC/SOP comparison, action whitelist, safety projection, requester self-approval prohibition, distinct dual approval, idempotent receipt and rollback | Simulation executor only |
| Artifact integrity | SHA-256 for newly trained model/controller artifacts | Enforced for new runs |
| Runtime security | Production API-key validation, role gates, security headers, request IDs | Required in production |
| Auditability | JSON access logs and SHA-256-chained mutation audit log | Active; external WORM retention required |
| Operations | Liveness, readiness, and Prometheus-format metrics | Active |
| Container safety | Non-root users, read-only filesystems, dropped capabilities, loopback binding | Active in Compose |
| Supply chain | Pinned CI actions, patched frontend overrides, optional audited neural-RL extra, dependency audit, CodeQL, Dependabot, dependency review, Scorecard | Configured; Linux CI is authoritative for the learner image |

## External evidence required before a real port deployment

1. TOS, EMS, berth/vessel, equipment, weather/navigation and shore-compatibility adapters
   that emit the v3 canonical schema with timestamped source identifiers.
2. Calibrated terminal capacities, load curves, delay costs, and safety limits approved by the port.
3. Meter and fuel records with lineage, correction policy, retention, and reconciliation procedures.
4. Supplier-specific or contractual electricity instruments for market-based Scope 2 reporting.
5. Authorized carbon-registry account ownership, allowance serials, trade/cash confirmations,
   retirement statements, trusted registry keys, and independently approved compliance rules.
6. A named management-system owner, approved policy and scope, legal/requirements register,
   energy review, site baseline and EnPIs, competency records, internal audit, closed corrective
   actions, management review and independently controlled assurance keys.
7. Named vessel calls, berth windows, crane work orders, yard inventory, truck appointments,
   reefer obligations, shore-power records and EMS slots, each signed by its source owner and
   aligned on the approved planning clock.
8. A signed green-corridor charter and separately owned vessel-operator, port-call, terminal,
   shore-power, alternative-fuel, tariff and corridor-ledger evidence; calibrated shore/fuel
   metering; parallel call, invoice and benefit-allocation reconciliation; and segregated ship/port approvals.
9. An approved single-line diagram plus named bus/feeder/transformer/switch/source records; calibrated
   impedances and ratings; time-aligned SCADA, power-quality, transformer, charging and BMS evidence;
   approved N-1/island studies; and independent short-circuit, protection, arc-flash and transient studies.
10. Frozen candidate/baseline artifacts and contracts; at least three seeds across all four seasons;
   calibrated probability forecasts; OOD fallback, explanation, action-reachability, P95/P99 latency,
   fault-injection and human-veto evidence; paired confidence intervals and safety non-regression;
   and a sufficiently long independently signed read-only shadow run.
11. An enterprise identity provider and ingress with short-lived signed tokens, MFA, named users,
   mapped roles, signed tenant membership, automated deprovisioning and cross-tenant isolation tests.
12. A quorum message bus, replicated tenant-partitioned time-series/database platform, multi-instance
   application topology, load balancer, multi-zone failover and measured post-failure capacity.
13. Encrypted immutable offsite/offline backups, hash-verified restore drills, measured RPO/RTO,
   external WORM retention, SIEM delivery/detection exercises, PKI/HSM-backed mTLS and key rotation.
14. Approved IT/industrial-DMZ/OT-control/safety zones, default-deny conduits, read-only gateway,
   recorded jump-host access, independent interlock, local manual control and an OT incident exercise.
15. Shadow-mode validation, operator acceptance testing, rollback drills, and an independent interlock.
16. Legal review of source licenses, carbon-market rules, privacy, critical-infrastructure obligations,
   and the named port's operational procedures.

The production gate remains closed until these items are supplied and independently reviewed.

## Health and evidence endpoints

- `GET /api/health/live`: process liveness only.
- `GET /api/health/ready`: dataset, run storage, and RL-runtime readiness.
- `GET /api/metrics`: Prometheus text metrics.
- `GET /api/rl/registry`: model lifecycle, data hash, artifact hash, drift, and test status.
- `GET /api/runtime/contract`: field contract, adapters, scenarios, actions and fixed production boundary.
- `GET /api/dashboard/carbon-inventory`: seven-source inventory, factor register, missing evidence, coverage and assurance gate.
- `GET /api/dashboard/measurement-verification`: claim-safe current M&V state; offline scenario differences remain separate from field savings.
- `POST /api/dashboard/measurement-verification/evaluate`: evaluate an approved site plan, boundary, interval meters, calibration, invoice reconciliation, adjustments, uncertainty, factor registry and Ed25519-signed independent review.
- `GET /api/dashboard/carbon-assets`: claim-safe scenario valuation and carbon-asset compliance state; verified registry positions are empty by default.
- `POST /api/dashboard/carbon-assets/evaluate`: reconcile program rules, registry ownership, allowance lots, trades, cash evidence, dual approval, retirement and Ed25519-signed registry attestation without executing a transaction.
- `GET /api/dashboard/energy-carbon-management`: claim-safe ISO-referenced management-system readiness; the offline default is blocked at 0/15.
- `POST /api/dashboard/energy-carbon-management/evaluate`: evaluate a complete annual PDCA evidence cycle, role segregation, linked inventory/M&V hashes, corrective-action closure and Ed25519-signed independent assurance without issuing certification.
- `GET /api/dashboard/operations-energy-plan`: fail-closed joint-planning readiness; public aggregate data remains blocked at 0/8 source domains and 0/12 gates.
- `POST /api/dashboard/operations-energy-plan/evaluate`: validate eight independently signed live source domains and solve vessel, berth, crane, yard, truck, reefer, shore-power, grid and storage constraints as an advisory-only plan.
- `GET /api/dashboard/electrical-network`: fail-closed electrical-network readiness; public aggregate data remains blocked at 0/6 source domains and 0/14 gates.
- `POST /api/dashboard/electrical-network/evaluate`: validate six independently signed site domains and assess topology, radial power flow, voltage/reactive/harmonics, transformer thermal aging, N-1, islanding, charging queues and storage warranty without issuing switch or protection commands.
- `GET /api/dashboard/algorithm-production`: fail-closed algorithm qualification state; repository evidence remains 0/6 sources and 0/15 production gates.
- `POST /api/dashboard/algorithm-production/evaluate`: evaluate six independently signed shadow-evidence domains and 15 production gates without training, promoting or dispatching a policy.
- `GET /api/dashboard/commercial-settlement`: fail-closed commercial readiness; public price and demand-response scenario values remain separate from verified bills and settlements at 0/8 sources and 0/16 gates.
- `POST /api/dashboard/commercial-settlement/evaluate`: validate eight independently signed commercial domains, reconstruct tariff and demand charges, reconcile utility/DR/ancillary/PPA/REC/tenant records, link independently reviewed M&V evidence, and calculate payback plus MACC without moving money or posting accounts.
- `GET /api/dashboard/port-collaboration`: fail-closed ship-port ecosystem readiness; public vessel activity and shore-power scenarios remain separate from verified collaboration values at 0/7 sources and 0/15 gates.
- `POST /api/dashboard/port-collaboration/evaluate`: validate seven independently signed domains and reconcile JIT arrival, berth milestones and ranking, shore-power reservation/billing, alternative-fuel readiness, port-fee incentives and shared abatement value without operational or financial authority.
- `GET /api/dashboard/enterprise-security`: distinguish executable repository controls from verified enterprise/OT site evidence; the default is 0/9 source domains and 0/20 gates.
- `POST /api/dashboard/enterprise-security/evaluate`: validate nine independently signed security domains and 20 gates covering identity/tenancy, messaging/time-series, HA/DR, WORM/SIEM, mTLS/key rotation, OT zoning, remote access and independent interlocks without authorizing cutover.
- `GET /api/dashboard/site-cutover-readiness`: aggregate thirteen implementation domains while distinguishing repository evidence from site acceptance.
- `POST /api/dashboard/site-cutover-readiness/evaluate`: bind all domains to one site, tenant, window, cutoff and release; require 180-day shadow coverage, operational drills, rollback and six independently signed approvals while retaining `production_authority=false`.
- `GET /api/security/context`: return the named subject, mapped role, allowed/selected tenant and authentication method without returning bearer-token material.
- `GET /api/runtime/snapshot`: current calibrated-simulation digital-twin snapshot and quality gate.
- `GET /api/runtime/forecast`: 1/3/6-hour current-input model inference.
- `POST /api/runtime/decisions`: runtime MPC recommendation and safety projection.
- `POST /api/runtime/decisions/{id}/approve`: persisted distinct human approval.
- `POST /api/runtime/decisions/{id}/execute`: idempotent simulation receipt and state/KPI feedback.
- `POST /api/runtime/decisions/{id}/rollback`: simulation rollback with chained audit evidence.
- `GET /api/runtime/decisions/statistics`: local simulation review, veto, receipt and latency statistics, explicitly not production-qualification evidence.
- `GET /api/evidence/history`: versioned historical, current, and blocked-candidate evidence.
- `GET /api/scenarios`: per-port dataset, observation and adapter readiness.
- `GET /api/scenarios/contract`: common objectives, observations, actions and hard constraints.
- `GET /api/integration/contract`: signed `port-snapshot.v1` envelope and feed SLAs.
- `GET /api/integration/status`: adapter freshness, resident-payload, identity/audit and dynamic time-alignment gates.
- `GET /api/integration/shadow-snapshot`: atomic `port-shadow-state.v1`; exposes all 21 values only after every six-source gate passes and otherwise returns empty observations.
- `POST /api/integration/snapshots`: validate and admit one signed read-only source snapshot.
- `GET /api/audit/integrity`: verify the local mutation-audit hash chain.
- `POST /api/rlops/policies/verify`: persists split, hash, safety and carbon/cost
  non-regression checks; a safe but underperforming policy is marked `blocked`.

## Deployment modes

- `development`: authentication may be disabled for localhost development.
- `production`: the backend refuses to start unless `API_AUTH_MODE=api_key|oidc`. API-key mode
  requires at least one 24-character key. OIDC mode requires issuer, audience, an Ed25519 public-key
  set and role map, and validates token time, MFA, named subject and signed tenant membership.
- `shadow`: additionally requires a named live port and per-adapter signing keys of at least
  32 characters. It enables read-only snapshot admission and in-memory six-source
  composition, not physical dispatch. A restart requires all six sources to resend.

Intel macOS is supported for the integration API, causal MPC and evidence replay, but not for
neural training because the platform cannot resolve a patched current PyTorch wheel. Release
learner images and PPO/SAC/TD3/DQN runs must pass the Linux CI dependency audit.

For an internet-facing deployment, place the dashboard behind an OIDC-aware ingress that performs
the authorization-code/session flow and forwards short-lived access tokens. The backend is now a
strict relying-party verifier, not an identity provider. Shared API-key mode remains suitable only
for a controlled internal benchmark. Neither authentication mode replaces WORM/SIEM, HA/DR,
segmented OT networking, local manual control or an independent hardware safety interlock.
