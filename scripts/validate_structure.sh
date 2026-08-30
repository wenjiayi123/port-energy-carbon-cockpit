#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-$ROOT/backend/.venv/bin/python}"

required_paths=(
  "$ROOT/backend/app/main.py"
  "$ROOT/backend/app/services/carbon_calculator.py"
  "$ROOT/backend/app/rl/environment.py"
  "$ROOT/backend/app/rl/training.py"
  "$ROOT/backend/app/rl/tuning.py"
  "$ROOT/backend/app/rl/benchmark.py"
  "$ROOT/backend/app/rl/landing_benchmark.py"
  "$ROOT/backend/app/rl/landing_readiness.py"
  "$ROOT/backend/app/rl/robust.py"
  "$ROOT/backend/app/rl/hybrid_control.py"
  "$ROOT/backend/app/rl/hybrid_business_scope.py"
  "$ROOT/backend/app/rl/hybrid_tuning.py"
  "$ROOT/backend/app/rl/hybrid_benchmark.py"
  "$ROOT/backend/app/rl/site_dataset_replacement.py"
  "$ROOT/backend/app/api/routes_integration.py"
  "$ROOT/backend/app/integration/gateway.py"
  "$ROOT/backend/app/services/runtime_simulator.py"
  "$ROOT/backend/app/services/runtime_forecast.py"
  "$ROOT/backend/app/services/runtime_decision.py"
  "$ROOT/backend/app/api/routes_runtime.py"
  "$ROOT/backend/app/data/datasets/port_la_2020_2025_hourly.csv"
  "$ROOT/backend/app/data/datasets/port_la_2020_2025_monthly.csv"
  "$ROOT/backend/app/data/datasets/port_la_2020_2024_hybrid_rl_hourly.csv"
  "$ROOT/backend/app/data/datasets/port_la_2020_2024_hybrid_rl_hourly.metadata.json"
  "$ROOT/backend/app/env/gymnasium_adapter.py"
  "$ROOT/backend/Dockerfile"
  "$ROOT/frontend/Dockerfile"
  "$ROOT/frontend/nginx.conf"
  "$ROOT/frontend/src/App.tsx"
  "$ROOT/scripts/start_demo.sh"
  "$ROOT/scripts/prepare_port_dataset.py"
  "$ROOT/scripts/build_hybrid_rl_dataset.py"
  "$ROOT/scripts/fetch_port_la_public_dataset.py"
  "$ROOT/scripts/run_frontend_command.sh"
  "$ROOT/scripts/sign_port_snapshot.py"
  "$ROOT/scripts/export_runtime_evidence.py"
  "$ROOT/scripts/audit_python_dependencies.py"
  "$ROOT/scripts/release_check.sh"
  "$ROOT/configs/carbon_factors.yaml"
  "$ROOT/configs/rl_search_space.json"
  "$ROOT/docs/RL_PIPELINE.md"
  "$ROOT/docs/HYBRID_RL_V6_DESIGN.md"
  "$ROOT/docs/DATASETS.md"
  "$ROOT/docs/MODULE_AUDIT.md"
  "$ROOT/docs/PROJECT_METRICS.md"
  "$ROOT/docs/TECHNICAL_REVIEW_2026-08.md"
  "$ROOT/docs/RUNTIME_DATA_CONTRACT.md"
  "$ROOT/docs/CLOSED_LOOP_ACCEPTANCE.md"
  "$ROOT/reports/offline_benchmark_v3.json"
  "$ROOT/reports/port_landing_benchmark_v4.json"
  "$ROOT/reports/port_landing_benchmark_v4.md"
  "$ROOT/reports/rl_tuning_smoke.json"
  "$ROOT/reports/runtime_forecast_model_v1.json"
  "$ROOT/LICENSE"
  "$ROOT/docker-compose.yml"
)

for path in "${required_paths[@]}"; do
  if [ ! -e "$path" ]; then
    echo "missing: $path"
    exit 1
  fi
done

if [ ! -x "$PYTHON_BIN" ]; then
  PYTHON_BIN="$(command -v python3 || true)"
fi
if [ -z "$PYTHON_BIN" ] || [ ! -x "$PYTHON_BIN" ]; then
  echo "python runtime not found; run 'make bootstrap' or set PYTHON_BIN" >&2
  exit 1
fi

PYTHONPATH="$ROOT/backend" "$PYTHON_BIN" -m app.rl.cli validate-data port_la_2020_2025_hourly >/dev/null
PYTHONPATH="$ROOT/backend" "$PYTHON_BIN" -m app.rl.cli validate-data port_la_2020_2024_hybrid_rl_hourly >/dev/null

if ! grep -q "公开数据校准实时模拟" \
  "$ROOT/frontend/src/components/PortCommandCenter.tsx"; then
  echo "missing public-data-calibrated runtime boundary in command center" >&2
  exit 1
fi

"$PYTHON_BIN" "$ROOT/scripts/export_runtime_evidence.py" verify >/dev/null

echo "structure and default dataset ok: $ROOT"
