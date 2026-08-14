#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BACKEND_PORT="${BACKEND_PORT:-8808}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"
BACKEND_HOST="${BACKEND_HOST:-127.0.0.1}"
FRONTEND_HOST="${FRONTEND_HOST:-127.0.0.1}"
BACKEND_PID=""
FRONTEND_PID=""
BACKEND_URL="http://$BACKEND_HOST:$BACKEND_PORT"
FRONTEND_URL="http://$FRONTEND_HOST:$FRONTEND_PORT/"

cleanup() {
  if [ -n "$FRONTEND_PID" ] && kill -0 "$FRONTEND_PID" 2>/dev/null; then
    kill "$FRONTEND_PID" 2>/dev/null || true
  fi
  if [ -n "$BACKEND_PID" ] && kill -0 "$BACKEND_PID" 2>/dev/null; then
    kill "$BACKEND_PID" 2>/dev/null || true
  fi
}

wait_for_backend() {
  local url="$BACKEND_URL/api/health"
  local attempt
  for attempt in $(seq 1 40); do
    if curl -fsS "$url" >/dev/null 2>&1; then
      return 0
    fi
    sleep 0.5
  done
  echo "backend did not become ready: $url" >&2
  return 1
}

port_is_listening() {
  local port="$1"
  command -v lsof >/dev/null 2>&1 \
    && lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1
}

is_energy_backend() {
  curl -fsS --max-time 2 "$BACKEND_URL/api/health" \
    | grep -q '"service":"energy-carbon-dispatch-cockpit"'
}

is_energy_frontend() {
  curl -fsS --max-time 2 "$FRONTEND_URL" \
    | grep -q '<title>港口能碳实时模拟与调度优化驾驶舱</title>'
}

managed_processes_alive() {
  if [ -n "$BACKEND_PID" ] && ! kill -0 "$BACKEND_PID" 2>/dev/null; then
    return 1
  fi
  if [ -n "$FRONTEND_PID" ] && ! kill -0 "$FRONTEND_PID" 2>/dev/null; then
    return 1
  fi
  return 0
}

trap cleanup INT TERM EXIT

cd "$ROOT"

if port_is_listening "$BACKEND_PORT"; then
  if is_energy_backend; then
    echo "Reusing verified energy backend on $BACKEND_URL"
  else
    echo "Port contract conflict: $BACKEND_PORT is occupied by another service." >&2
    lsof -nP -iTCP:"$BACKEND_PORT" -sTCP:LISTEN >&2 || true
    exit 2
  fi
else
  echo "Starting backend on $BACKEND_URL"
  BACKEND_HOST="$BACKEND_HOST" BACKEND_PORT="$BACKEND_PORT" bash scripts/run_backend.sh &
  BACKEND_PID="$!"
fi

wait_for_backend

if port_is_listening "$FRONTEND_PORT"; then
  if is_energy_frontend; then
    echo "Reusing verified energy frontend on $FRONTEND_URL"
  else
    echo "Port contract conflict: $FRONTEND_PORT is occupied by another service." >&2
    lsof -nP -iTCP:"$FRONTEND_PORT" -sTCP:LISTEN >&2 || true
    exit 2
  fi
else
  echo "Starting frontend on $FRONTEND_URL"
  FRONTEND_HOST="$FRONTEND_HOST" \
  FRONTEND_PORT="$FRONTEND_PORT" \
  VITE_API_TARGET="$BACKEND_URL" \
    bash scripts/run_frontend.sh &
  FRONTEND_PID="$!"
fi

echo
echo "Demo is running:"
echo "  Frontend: $FRONTEND_URL"
echo "  Backend:  $BACKEND_URL/api/health"
echo
if [ -z "$BACKEND_PID" ] && [ -z "$FRONTEND_PID" ]; then
  echo "Both verified services were already online; no duplicate process was started."
  exit 0
fi
echo "Press Ctrl+C to stop processes started by this launcher."

while managed_processes_alive; do
  sleep 1
done

echo "A demo process exited; stopping remaining services." >&2
exit 1
