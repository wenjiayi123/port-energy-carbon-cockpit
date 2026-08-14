# Local closed-loop acceptance

This procedure proves the bundled simulation chain. It does not authorize or imply physical port
dispatch.

## Start

```bash
cd port-energy-carbon-cockpit
make demo
```

Wait for the launcher to print the two URLs, keep Terminal open, and visit:

- UI: `http://127.0.0.1:5173/`
- API health: `http://127.0.0.1:8808/api/health`
- API documentation: `http://127.0.0.1:8808/docs`

Use `Control+C` in Terminal to stop processes started by the launcher.

## Browser path

1. Click the top-left **公开数据校准实时模拟** status.
2. Verify the three labels: **公开数据校准实时模拟**, **模型真实推理输出**, and
   **待切换现场数据源**.
3. Watch grid import, PV, BESS SOC/SOH/temperature, shore power, charging, reefer, HVAC,
   throughput, carbon and cost change across polls.
4. Inspect 1/3/6-hour prediction, model/data hashes and Train → Validation → Test boundary.
5. Click **生成当前推荐**. Inspect recommended versus safety-projected actions.
6. Complete **班组长审批** and **能源经理审批** when two approvals are required.
7. Click **模拟执行**. Inspect ACK, before/after KPI and delta.
8. Click **回滚**. Confirm rollback acknowledgement.
9. Scroll the field lineage table; every field must show source type, ID, quality and confidence.
10. Inject **失联**. Prediction disappears and recommendation is disabled. Click **复位** to
    recover.

## API path

Create a recommendation:

```bash
curl -sS -X POST http://127.0.0.1:8808/api/runtime/decisions \
  -H 'Content-Type: application/json' \
  -d '{"objective":"balanced","idempotency_key":"acceptance-create-001","requested_by":"operator-a"}'
```

Copy `decision_id`, then approve with two distinct people if the response requires two approvals:

```bash
curl -sS -X POST http://127.0.0.1:8808/api/runtime/decisions/DECISION_ID/approve \
  -H 'Content-Type: application/json' \
  -d '{"approver_id":"supervisor-b","decision":"approve","comment":"operations accepted","idempotency_key":"acceptance-approve-b"}'

curl -sS -X POST http://127.0.0.1:8808/api/runtime/decisions/DECISION_ID/approve \
  -H 'Content-Type: application/json' \
  -d '{"approver_id":"energy-manager-c","decision":"approve","comment":"energy accepted","idempotency_key":"acceptance-approve-c"}'
```

Execute and inspect the receipt:

```bash
curl -sS -X POST http://127.0.0.1:8808/api/runtime/decisions/DECISION_ID/execute \
  -H 'Content-Type: application/json' \
  -d '{"executor_id":"simulation-executor","idempotency_key":"acceptance-execute-001"}'

curl -sS http://127.0.0.1:8808/api/runtime/decisions/DECISION_ID/audit
```

The receipt must say `mode=simulation_only`, `production_dispatch=false`, include both snapshot
hashes and non-empty KPI deltas, and the audit endpoint must return `chain_valid=true` and
`record_sha256_valid=true`.

## Fail-closed check

```bash
curl -sS -X POST http://127.0.0.1:8808/api/runtime/scenarios/inject \
  -H 'Content-Type: application/json' \
  -d '{"scenario_id":"communications_loss","duration_steps":8,"idempotency_key":"acceptance-loss-001"}'

curl -i http://127.0.0.1:8808/api/runtime/forecast
```

The forecast must return HTTP 409. Recover with:

```bash
curl -sS -X POST http://127.0.0.1:8808/api/runtime/control \
  -H 'Content-Type: application/json' \
  -d '{"action":"reset","idempotency_key":"acceptance-reset-001"}'
```

## Release checks

```bash
make release-check
```

This verifies structure, compilation, Ruff, backend dependency audit, dependency consistency, all backend tests, the three
frozen historical benchmark reports, the v0.4.0 runtime model evidence, frontend dependency audit,
and production build. Docker image validation remains a separate check when Docker is available.
