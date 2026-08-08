#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/../backend"
BACKEND_HOST="${BACKEND_HOST:-127.0.0.1}"
BACKEND_PORT="${BACKEND_PORT:-8808}"
PYTHON_BIN="${PYTHON_BIN:-.venv/bin/python}"
UVICORN_RELOAD="${UVICORN_RELOAD:-0}"

if [ ! -x "$PYTHON_BIN" ]; then
  echo "backend virtualenv is missing; run 'make bootstrap' first" >&2
  exit 1
fi

UVICORN_ARGS=(app.main:app --host "$BACKEND_HOST" --port "$BACKEND_PORT")
if [ "$UVICORN_RELOAD" = "1" ]; then
  UVICORN_ARGS+=(--reload)
fi

exec "$PYTHON_BIN" -m uvicorn "${UVICORN_ARGS[@]}"
