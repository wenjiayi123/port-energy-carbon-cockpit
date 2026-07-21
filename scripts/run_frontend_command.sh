#!/usr/bin/env bash
set -euo pipefail

PNPM_BIN="${PNPM_BIN:-$(command -v pnpm || true)}"
if [ -z "$PNPM_BIN" ] || [ ! -x "$PNPM_BIN" ]; then
  echo "pnpm is required; install it with corepack or set PNPM_BIN" >&2
  exit 1
fi

if ! command -v node >/dev/null 2>&1; then
  PNPM_DIR="$(cd "$(dirname "$PNPM_BIN")" && pwd)"
  BUNDLED_NODE="$PNPM_DIR/../../node/bin/node"
  if [ -x "$BUNDLED_NODE" ]; then
    export PATH="$(dirname "$BUNDLED_NODE"):$PATH"
  else
    echo "Node.js 20+ is required and was not found on PATH" >&2
    exit 1
  fi
fi

exec "$PNPM_BIN" "$@"
