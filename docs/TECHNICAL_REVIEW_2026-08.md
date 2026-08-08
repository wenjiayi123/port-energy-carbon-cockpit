# Real-port technical review — 2026-08-08

## Review conclusion

Version 0.3.0 is suitable for public, reproducible offline research and for a
terminal-controlled **read-only shadow integration pilot**. It is not authorized
for autonomous equipment control. The repository now contains executable
ingestion and admission gates; the remaining production blockers require named
port systems, credentials, calibrated parameters, operator acceptance and an
independent OT safety path that cannot be supplied by open-source code alone.

The original 0.2.0 benchmark reports, learner artifacts and resume-safe business
metrics are frozen. Version 0.3.0 adds a separate causal robustness report; it
does not silently rewrite the original denominator or claim field performance.

## Findings and remediation

| Priority | Finding before 0.3.0 | Risk | 0.3.0 remediation | Residual gate |
| --- | --- | --- | --- | --- |
| P0 | `auto:latest` excluded short smoke runs but could still choose a substantial policy whose verification was `blocked` | A regressive model could contaminate the displayed policy and previously published value metrics | Automatic selection now requires persisted `verified` admission evidence; no eligible policy fails closed; registry stage honors blocked verification | A port policy still needs terminal acceptance and shadow evidence |
| P0 | Live-port adapters were YAML booleans, not executable evidence | A configured flag could be mistaken for a real data connection | Added `port-snapshot.v1` envelopes, per-adapter HMAC, payload SHA-256, units, field schema, freshness, sequence and replay gates; readiness derives from accepted snapshots | Port owner must issue endpoints, keys and source-system identities |
| P0 | Training observations and MPC planning could use later rows as a perfect forecast | Held-out test information could leak into a decision | Every new run records `causal_persistence_v1`; the additive environment wrapper makes later rows unavailable at decision time; legacy evidence remains hash-frozen and explicitly legacy | Replace persistence with timestamped port forecasts after shadow calibration |
| P0 | Production and offline dataset quality were represented by one score | A 100/100 completeness score could be overread as production readiness | Added a separate landing grade based on independent anchors, native resolution, event lineage, v3 fields and parameter calibration | Current public packages correctly remain production-blocked |
| P1 | Evaluation emphasized point estimates | Average improvements could hide unstable or adverse windows | Added paired bootstrap 95% intervals, per-window evidence, CVaR95 tail metrics, reserve-breach and action-variation measures | Field confidence requires a longer port-owned shadow period |
| P1 | Four RL names plus MPC did not by themselves establish deployment depth | Algorithm count could be confused with robust decision quality | Added a six-step/eight-beam risk-aware MPC safety layer with reserve, queue, delay, SOC, projection and action-slew costs; it qualifies rather than renames the five published baselines | RL production admission still needs multi-run shadow comparison and champion/challenger review |
| P1 | Mutation audit records were ordinary JSONL | Local edits were not detectable | New events form a SHA-256 hash chain with legacy-prefix support and an integrity endpoint | Export to port-owned append-only/WORM retention remains required |
| P1 | Dry-run dispatch packets were timestamp labels without policy/input binding or rollback reference | An operator could not reproduce which evidence produced a recommendation | Shadow packets now carry deterministic idempotency IDs, policy/artifact hash, admitted input digests, five-minute expiry and a frozen MPC rollback target | Physical execution and independent interlock remain external |
| P1 | Application had no request-volume backstop | Oversized or burst traffic could exhaust a single process | Added body-size enforcement and a sliding-window per-process rate limiter | A distributed gateway/WAF remains required for clustered deployment |
| P1 | The dependency graph contained vulnerable transitive frontend packages, and Intel macOS could only resolve an obsolete PyTorch wheel | Open-source builds could pass feature tests while carrying known supply-chain risk | Pinned patched PostCSS/Nanoid overrides, upgraded the data cryptography extra, separated neural RL from the integration plane, and require an audited Linux/Apple-Silicon learner runtime | Intel macOS remains unsupported for neural training; GitHub Linux CI is the release gate |
| P1 | Raw row count hid modeled expansion | 43,848 rows could be mistaken for 43,848 independent terminal measurements | Landing assessment reports 1,238 official daily anchors, modeled expansion ratio, reported-day coverage and missing v3 evidence | Acquire event-level TOS/EMS/SCADA and meter records |
| P2 | UI exposed offline quality and dispatch state but not live evidence readiness | Operators could miss the difference between a good CSV and connected sources | Cockpit now shows landing data grade, ready adapters and fail-closed snapshot integrity | Full operator workflow requires port UX acceptance testing |

## Data finding: volume is not the primary bottleneck

The enhanced public package has 43,848 contiguous hourly rows, which is ample
for software, temporal-split and baseline experiments. Its information density
is lower than the row count suggests: the vessel workload signal is anchored by
1,238 official daily business records, non-reporting days are interpolated, TEU
is allocated from monthly totals, and equipment/load parameters are declared
scenario assumptions. The key next data investment is therefore not synthetic
row multiplication. It is independent event coverage and calibration:

1. TOS work orders, vessel calls, berth moves and completed moves with immutable event IDs.
2. EMS/SCADA and revenue-meter intervals with quality flags, corrections and reconciliation.
3. Crane, yard, storage, shore-power and grid availability at source resolution.
4. Timestamped weather/navigation observations and the forecasts actually available at decision time.
5. Terminal-approved load curves, capacities, tariffs, delay costs and safety limits.
6. Failure, maintenance and curtailment labels for stress and recovery evaluation.

## Algorithm finding: what “deeper” now means

Algorithm depth is evaluated by the complete decision protocol, not the model
name. Version 0.3.0 requires causal inputs, hard action projection, held-out
coverage, a fixed comparator, confidence bounds, tail risk, stress tests,
artifact/data hashes and a fail-closed admission decision. The risk-aware MPC
layer is deliberately separate from PPO/SAC/TD3/DQN and the published MPC
baseline so the original five-method evidence is not relabelled.

The stress evidence is not uniformly favorable: grid derating increases soft
reserve-breach steps by 7.692%, while demand, grid and equipment stress cases
all add small carbon/cost overhead versus causal legacy MPC. These results stay
published and prevent a universal-superiority claim.

For the next RL research release, a candidate should also provide at least three
predeclared seeds, validation-only hyperparameter selection, learning curves,
calibration against the risk-aware control layer, and a shadow champion/challenger
report. A long single run is not sufficient.

## Real-port acceptance sequence

1. Run v0.3.0 in `shadow` mode behind terminal identity, TLS and network controls.
2. Admit all six signed read-only feeds and retain their freshness/lineage evidence.
3. Build a separate immutable shadow dataset; do not append live rows to the frozen public benchmark.
4. Calibrate parameters and approve safety envelopes with operations, electrical and equipment owners.
5. Run at least one seasonal shadow period, planned outage cases and rollback drills.
6. Review policy business value, confidence intervals, tail risk and operational exceptions.
7. Integrate any physical command path through a separately certified adapter and independent interlock.
8. Obtain two-person change approval and a documented rollback before any controlled field trial.

The controls align with the risk-management direction in
[NIST AI RMF 1.0](https://www.nist.gov/publications/artificial-intelligence-risk-management-framework-ai-rmf-10)
and the reliability/safety emphasis of
[NIST SP 800-82 Rev. 3](https://csrc.nist.gov/pubs/sp/800/82/r3/final).
The carbon context remains the
[2023 IMO GHG Strategy](https://www.imo.org/en/OurWork/Environment/Pages/2023-IMO-Strategy-on-Reduction-of-GHG-Emissions-from-Ships.aspx);
port-specific legal conclusions still require local review. Rotterdam deployment
must additionally review the current consolidated
[EU Alternative Fuels Infrastructure Regulation](https://eur-lex.europa.eu/legal-content/en/TXT/?uri=CELEX%3A02023R1804-20260108).

## Evidence commands

```bash
make test
make build
make validate
make verify-benchmark
make verify-benchmark-enhanced
make verify-landing-benchmark
```

The full v4 causal robustness report is reproduced with `make landing-benchmark`.
Docker image build evidence comes from the Linux GitHub CI container job because
Docker is not installed on the reviewed macOS host.
