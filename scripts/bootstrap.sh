#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

PYTHON_BIN="${PYTHON_BIN:-$(command -v python3 || true)}"
if [ -z "$PYTHON_BIN" ] || [ ! -x "$PYTHON_BIN" ]; then
  echo "Python 3.11+ is required; set PYTHON_BIN when it is not on PATH" >&2
  exit 1
fi
if ! "$PYTHON_BIN" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)'; then
  echo "Python 3.11+ is required; current interpreter is $("$PYTHON_BIN" -V 2>&1)" >&2
  echo "Set PYTHON_BIN to a compatible interpreter and rerun make bootstrap" >&2
  exit 1
fi

"$PYTHON_BIN" -m venv backend/.venv
source backend/.venv/bin/activate
python -m pip install --upgrade "pip==26.2.1"
python -m pip install -e "backend[dev,rl]"

cd frontend
bash ../scripts/run_frontend_command.sh install --frozen-lockfile
