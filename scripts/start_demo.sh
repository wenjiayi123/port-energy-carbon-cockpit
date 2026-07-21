#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BACKEND_PORT="${BACKEND_PORT:-8808}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"
BACKEND_HOST="${BACKEND_HOST:-127.0.0.1}"
FRONTEND_HOST="${FRONTEND_HOST:-127.0.0.1}"
BACKEND_PID=""
FRONTEND_PID=""

cleanup() {
  if [ -n "$FRONTEND_PID" ] && kill -0 "$FRONTEND_PID" 2>/dev/null; then
    kill "$FRONTEND_PID" 2>/dev/null || true
  fi
  if [ -n "$BACKEND_PID" ] && kill -0 "$BACKEND_PID" 2>/dev/null; then
    kill "$BACKEND_PID" 2>/dev/null || true
  fi
}

wait_for_backend() {
  local url="http://$BACKEND_HOST:$BACKEND_PORT/api/health"
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

trap cleanup INT TERM EXIT

cd "$ROOT"

echo "Starting backend on http://$BACKEND_HOST:$BACKEND_PORT"
BACKEND_HOST="$BACKEND_HOST" BACKEND_PORT="$BACKEND_PORT" bash scripts/run_backend.sh &
BACKEND_PID="$!"

wait_for_backend

echo "Starting frontend on http://$FRONTEND_HOST:$FRONTEND_PORT"
FRONTEND_HOST="$FRONTEND_HOST" \
FRONTEND_PORT="$FRONTEND_PORT" \
VITE_API_TARGET="http://$BACKEND_HOST:$BACKEND_PORT" \
  bash scripts/run_frontend.sh &
FRONTEND_PID="$!"

echo
echo "Demo is running:"
echo "  Frontend: http://$FRONTEND_HOST:$FRONTEND_PORT/"
echo "  Backend:  http://$BACKEND_HOST:$BACKEND_PORT/api/health"
echo
echo "Press Ctrl+C to stop both services."

while kill -0 "$BACKEND_PID" 2>/dev/null && kill -0 "$FRONTEND_PID" 2>/dev/null; do
  sleep 1
done

echo "A demo process exited; stopping remaining services." >&2
exit 1
