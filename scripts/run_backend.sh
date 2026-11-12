#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/../backend"

# Reuse the explicitly configured local integrations when launched by Xiaoyi.
# Standalone demos may use the adjacent checkouts; explicit settings always win.
ENERGY_DESKTOP_ROOT="$(dirname "$(dirname "$PWD")")"
if [[ -z "${XIAOYI_AI_PROJECT:-}" && -f "$ENERGY_DESKTOP_ROOT/舷鸥 · GullMate/run.sh" ]]; then
  export XIAOYI_AI_PROJECT="$ENERGY_DESKTOP_ROOT/舷鸥 · GullMate"
fi
ENERGY_SAILING_CANDIDATE="${XIAOYI_SAILING_SIMULATOR_ROOT:-$ENERGY_DESKTOP_ROOT/航行模拟器}"
if [[ -z "${SAILING_SIM_PROJECT:-}" && -f "$ENERGY_SAILING_CANDIDATE/project.godot" ]]; then
  export SAILING_SIM_PROJECT="$ENERGY_SAILING_CANDIDATE"
fi
ENERGY_GODOT_CANDIDATE="${XIAOYI_GODOT_BINARY:-$ENERGY_DESKTOP_ROOT/舷鸥 · GullMate/.runtime/tools/godot-4.7.1/Godot.app/Contents/MacOS/Godot}"
if [[ -z "${SAILING_SIM_GODOT:-}" && -x "$ENERGY_GODOT_CANDIDATE" ]]; then
  export SAILING_SIM_GODOT="$ENERGY_GODOT_CANDIDATE"
fi

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
