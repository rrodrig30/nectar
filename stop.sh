#!/usr/bin/env bash
#
# stop.sh - stop the NECTAR platform started by ./start.sh.
#
# Usage:
#   ./stop.sh              # stop services, KEEP the graph data (and ollama models)
#   ./stop.sh --volumes    # stop and DELETE all volumes (graph data, models, corpus)
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE_FILE="$ROOT/deploy/compose/podman-compose.yml"

# --- stop a locally launched API, if any ------------------------------------
if [ -f "$ROOT/.nectar-api.pid" ]; then
  API_PID="$(cat "$ROOT/.nectar-api.pid")"
  if kill "$API_PID" >/dev/null 2>&1; then
    echo "==> stopped local NECTAR API (pid $API_PID)"
  fi
  rm -f "$ROOT/.nectar-api.pid"
fi

# --- pick a compose command -------------------------------------------------
if podman compose version >/dev/null 2>&1; then
  COMPOSE=(podman compose)
elif command -v podman-compose >/dev/null 2>&1; then
  COMPOSE=(podman-compose)
else
  echo "error: need 'podman compose' or 'podman-compose' on PATH." >&2
  exit 1
fi

DOWN_ARGS=(down --remove-orphans)
if [ "${1:-}" = "--volumes" ] || [ "${1:-}" = "-v" ]; then
  echo "==> stopping services and DELETING volumes (graph data, ollama models, corpus staging)"
  DOWN_ARGS+=(--volumes)
else
  echo "==> stopping services (volumes preserved; pass --volumes to wipe the graph)"
fi

"${COMPOSE[@]}" -f "$COMPOSE_FILE" "${DOWN_ARGS[@]}"
echo "    stopped."
