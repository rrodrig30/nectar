#!/usr/bin/env bash
#
# start.sh - bring up the NECTAR platform for local development.
#
# Starts Neo4j (and, best effort, Ollama), applies the graph schema, and loads the
# clinical knowledge base. These are the two batch stages that are fully functional
# today. Recipe/nutrient ingestion (make ingest/cluster/materialize) is NOT yet
# implemented - the acquisition adapters that download RecipeNLG/FDC/etc. are stubs
# (see CLAUDE.md "Repository state"), so no recipe corpus is populated here.
#
# Usage:
#   ./start.sh                 # neo4j + ollama, then schema + knowledge
#   WITH_OLLAMA=0 ./start.sh   # skip ollama (no GPU / CDI on this host)
#   WITH_API=1 ./start.sh      # also run the NECTAR API locally on :8000
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE_FILE="$ROOT/deploy/compose/podman-compose.yml"
PY="$ROOT/.venv/bin/python"

# --- configuration (override via environment) -------------------------------
# The dev compose file pins Neo4j auth to neo4j/devpassword; keep these aligned
# unless you also edit deploy/compose/podman-compose.yml.
export NEO4J_URI="${NEO4J_URI:-bolt://localhost:7687}"
export NEO4J_USER="${NEO4J_USER:-neo4j}"
export NEO4J_PASSWORD="${NEO4J_PASSWORD:-devpassword}"
WITH_OLLAMA="${WITH_OLLAMA:-1}"
WITH_API="${WITH_API:-0}"

# --- pick a compose command -------------------------------------------------
if podman compose version >/dev/null 2>&1; then
  COMPOSE=(podman compose)
elif command -v podman-compose >/dev/null 2>&1; then
  COMPOSE=(podman-compose)
else
  echo "error: need 'podman compose' (podman >= 4.4) or 'podman-compose' on PATH." >&2
  exit 1
fi

compose() { "${COMPOSE[@]}" -f "$COMPOSE_FILE" "$@"; }

# --- start infrastructure ---------------------------------------------------
echo "==> starting Neo4j"
compose up -d neo4j

if [ "$WITH_OLLAMA" = "1" ]; then
  echo "==> starting Ollama (best effort; set WITH_OLLAMA=0 to skip)"
  if ! compose up -d ollama; then
    echo "    warning: Ollama did not start (no GPU/CDI?). Continuing without it." >&2
  fi
fi

# --- wait for Neo4j to accept bolt connections ------------------------------
echo "==> waiting for Neo4j to accept connections at $NEO4J_URI"
ready=0
if [ -x "$PY" ]; then
  for _ in $(seq 1 60); do
    if "$PY" - <<'PYEOF' >/dev/null 2>&1
import os
from neo4j import GraphDatabase
d = GraphDatabase.driver(os.environ["NEO4J_URI"],
                         auth=(os.environ["NEO4J_USER"], os.environ["NEO4J_PASSWORD"]))
d.verify_connectivity()
d.close()
PYEOF
    then ready=1; break; fi
    sleep 2
  done
else
  echo "    no local .venv found; sleeping 25s for Neo4j to warm up"
  sleep 25
  ready=1
fi
if [ "$ready" != "1" ]; then
  echo "error: Neo4j did not become ready. Check 'podman logs' for the neo4j container." >&2
  exit 1
fi
echo "    Neo4j is ready"

# --- apply schema + load the clinical knowledge base ------------------------
# Runs from the local .venv if present (fastest), otherwise a one-off container.
run_stage() {
  local stage="$1"
  if [ -x "$PY" ]; then
    ( cd "$ROOT/nutriscrape" && "$PY" -m nutriscrape "$stage" )
  else
    compose run --rm \
      -e NEO4J_URI="bolt://neo4j:7687" \
      -e NEO4J_USER="$NEO4J_USER" \
      -e NEO4J_PASSWORD="$NEO4J_PASSWORD" \
      -e FDC_API_KEY="${FDC_API_KEY:-}" \
      nutriscrape "$stage"
  fi
}

echo "==> applying graph schema"
run_stage schema
echo "==> loading clinical knowledge base (rules, interactions, transforms, guidelines)"
run_stage knowledge

# Recipe ingest works over the bundled sample corpus, but resolving foods and reading raw nutrient
# amounts needs the USDA FDC API. Run it only when a key is present.
if [ -n "${FDC_API_KEY:-}" ]; then
  echo "==> ingesting the bundled sample recipe corpus (FDC_API_KEY is set)"
  run_stage ingest
else
  echo "==> skipping recipe ingest: FDC_API_KEY is not set"
  echo "    (get a free key at https://api.data.gov/signup, then: FDC_API_KEY=... ./start.sh)"
fi

# --- optionally run the NECTAR API locally ----------------------------------
if [ "$WITH_API" = "1" ] && [ -x "$PY" ]; then
  echo "==> starting NECTAR API on http://localhost:8000 (logs: $ROOT/.nectar-api.log)"
  ( cd "$ROOT/nectar" && \
    NEO4J_URI="$NEO4J_URI" NEO4J_USER="$NEO4J_USER" NEO4J_PASSWORD="$NEO4J_PASSWORD" \
    "$ROOT/.venv/bin/uvicorn" nectar.api.app:app --host 0.0.0.0 --port 8000 \
    >"$ROOT/.nectar-api.log" 2>&1 & echo $! >"$ROOT/.nectar-api.pid" )
fi

cat <<EOF

NECTAR is up.
  Neo4j browser : http://localhost:7474   (user ${NEO4J_USER})
  Bolt          : ${NEO4J_URI}
$( [ "$WITH_OLLAMA" = "1" ] && echo "  Ollama        : http://localhost:11434" )
$( [ "$WITH_API" = "1" ]    && echo "  NECTAR API    : http://localhost:8000/docs" )

Loaded: graph schema + clinical knowledge base$( [ -n "${FDC_API_KEY:-}" ] && echo " + the bundled sample recipe corpus (cooked nutrient vectors from USDA FDC)" ).

Scope note: 'make ingest' runs over a small BUNDLED sample corpus
(nutriscrape/config/samples/recipes_sample.csv), not the full RecipeNLG dataset -
the bulk download and schema.org scraping are still PDD Phase 1. 'make cluster'
and 'make materialize' still need corpus graph-readers (PDD Phase 3/5) and will
no-op with a warning until those land, so dishes are not yet formed from recipes.

Stop everything with ./stop.sh (add --volumes to also delete the graph data).
EOF
