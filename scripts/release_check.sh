#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON_BIN="$ROOT/backend/.venv/bin/python"

if [ ! -x "$PYTHON_BIN" ]; then
  echo "backend virtualenv is missing; run 'make bootstrap' first" >&2
  exit 1
fi

bash "$ROOT/scripts/validate_structure.sh"
cd "$ROOT/backend"
"$PYTHON_BIN" -m compileall -q app
"$PYTHON_BIN" -m ruff check app
"$PYTHON_BIN" -m pip check
"$PYTHON_BIN" "$ROOT/scripts/audit_python_dependencies.py"
"$PYTHON_BIN" -m pytest app/tests -q

cd "$ROOT"
PYTHONPATH=backend "$PYTHON_BIN" -m app.rl.legacy_extension_verify verify reports/offline_benchmark_v3.json
PYTHONPATH=backend "$PYTHON_BIN" -m app.rl.legacy_extension_verify verify reports/offline_benchmark_vessel_activity_v1.json
PYTHONPATH=backend "$PYTHON_BIN" -m app.rl.legacy_extension_verify verify reports/port_landing_benchmark_v4.json
PYTHONPATH=backend "$PYTHON_BIN" -m app.rl.regulatory_benchmark verify reports/regulatory_resilience_v1.json
PYTHONPATH=backend "$PYTHON_BIN" -m app.rl.regulatory_shielded_benchmark verify reports/regulatory_resilience_v2.json
PYTHONPATH=backend "$PYTHON_BIN" -m app.rl.regulatory_projected_benchmark verify reports/regulatory_resilience_v3.json
"$PYTHON_BIN" scripts/export_runtime_evidence.py verify

cd "$ROOT/frontend"
bash ../scripts/run_frontend_command.sh audit --audit-level high
bash ../scripts/run_frontend_command.sh build

echo "release-check: PASS"
