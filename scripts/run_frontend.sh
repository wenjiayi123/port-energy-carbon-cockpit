#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/../frontend"
FRONTEND_HOST="${FRONTEND_HOST:-127.0.0.1}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"
export VITE_API_TARGET="${VITE_API_TARGET:-http://127.0.0.1:8808}"

exec bash ../scripts/run_frontend_command.sh run dev -- --host "$FRONTEND_HOST" --port "$FRONTEND_PORT"
