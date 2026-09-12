#!/usr/bin/env bash
set -euo pipefail

resolve_pnpm() {
  if [ -n "${PNPM_BIN:-}" ]; then
    if [ -x "$PNPM_BIN" ]; then
      printf '%s\n' "$PNPM_BIN"
      return 0
    fi
    echo "PNPM_BIN is set but is not executable: $PNPM_BIN" >&2
    return 1
  fi

  if command -v pnpm >/dev/null 2>&1; then
    command -v pnpm
    return 0
  fi

  for candidate in \
    "/opt/homebrew/bin/pnpm" \
    "/usr/local/bin/pnpm" \
    "$HOME/.cache/codex-runtimes/codex-primary-runtime/dependencies/bin/fallback/pnpm" \
    "$HOME/.cache/codex-runtimes/codex-primary-runtime/dependencies/bin/pnpm"
  do
    if [ -x "$candidate" ]; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done

  return 1
}

PNPM_BIN="$(resolve_pnpm || true)"

if [ -z "$PNPM_BIN" ]; then
  if command -v corepack >/dev/null 2>&1; then
    exec corepack pnpm "$@"
  fi
  if command -v npm >/dev/null 2>&1; then
    case "${1:-}" in
      run|install|audit)
        exec npm "$@"
        ;;
      build|preview)
        exec npm run "$@"
        ;;
    esac
  fi
  echo "Node.js 20+ with Corepack is required; pnpm, Corepack, or npm was not found." >&2
  echo "Install Node.js 20+, then run: corepack enable && corepack prepare pnpm@11.7.0 --activate" >&2
  exit 1
fi

if ! command -v node >/dev/null 2>&1; then
  PNPM_DIR="$(cd "$(dirname "$PNPM_BIN")" && pwd)"
  # Finder launches have a minimal PATH. Resolve Node beside the selected
  # package manager, including both layouts of the existing local runtime.
  for candidate in \
    "$PNPM_DIR/node" \
    "$PNPM_DIR/../node/bin/node" \
    "$PNPM_DIR/../../node/bin/node"
  do
    if [ -x "$candidate" ]; then
      export PATH="$(dirname "$candidate"):$PATH"
      break
    fi
  done
  if ! command -v node >/dev/null 2>&1; then
    echo "Node.js 20+ is required and was not found on PATH" >&2
    exit 1
  fi
fi

exec "$PNPM_BIN" "$@"
