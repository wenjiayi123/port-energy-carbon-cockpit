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
  "$ROOT/backend/app/api/routes_integration.py"
  "$ROOT/backend/app/integration/gateway.py"
  "$ROOT/backend/app/data/datasets/port_la_2020_2025_hourly.csv"
  "$ROOT/backend/app/data/datasets/port_la_2020_2025_monthly.csv"
  "$ROOT/backend/app/env/gymnasium_adapter.py"
  "$ROOT/backend/Dockerfile"
  "$ROOT/frontend/Dockerfile"
  "$ROOT/frontend/nginx.conf"
  "$ROOT/frontend/src/App.tsx"
  "$ROOT/scripts/start_demo.sh"
  "$ROOT/scripts/prepare_port_dataset.py"
  "$ROOT/scripts/fetch_port_la_public_dataset.py"
  "$ROOT/scripts/run_frontend_command.sh"
  "$ROOT/scripts/sign_port_snapshot.py"
  "$ROOT/configs/carbon_factors.yaml"
  "$ROOT/configs/rl_search_space.json"
  "$ROOT/docs/RL_PIPELINE.md"
  "$ROOT/docs/DATASETS.md"
  "$ROOT/docs/MODULE_AUDIT.md"
  "$ROOT/docs/RESUME_CLAIMS.md"
  "$ROOT/docs/TECHNICAL_REVIEW_2026-08.md"
  "$ROOT/reports/offline_benchmark_v3.json"
  "$ROOT/reports/port_landing_benchmark_v4.json"
  "$ROOT/reports/port_landing_benchmark_v4.md"
  "$ROOT/reports/rl_tuning_smoke.json"
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

if ! grep -q "公开离线基准 · 等待接入港口" \
  "$ROOT/frontend/src/components/PortCommandCenter.tsx"; then
  echo "missing first-clone port-integration boundary in command center" >&2
  exit 1
fi

echo "structure and default dataset ok: $ROOT"
