#!/usr/bin/env bash
#
# full-reingest.sh - Approach B (fresh DB, then swap): rebuild the recipe/dish side of the graph
# from the source corpus into a SEPARATE Neo4j volume, leaving the live graph serving until you
# deliberately swap. Applies every WS-A fix (masses, transforms, method carryover, food matcher,
# idempotent writes) at corpus scale and restores any overwritten recipe ids.
#
# This script only builds and verifies the new graph. It NEVER touches the live volume or swaps -
# the swap is a manual, gated step (see deploy/runbooks/full-reingest.md). It is restartable: each
# stage writes a checkpoint, so a re-run resumes at the first unfinished stage. Every stage is
# idempotent, so re-running a completed one is harmless too.
#
# Prerequisites (the script preflights them and refuses to start otherwise):
#   - RecipeNLG corpus staged in the corpus-staging volume (NUTRISCRAPE_CORPUS path below)
#   - USDA FDC bulk CSVs staged in the fdc-staging volume (food.csv, nutrient.csv, food_nutrient.csv)
#   - podman secret nectar_neo4j_pass present (the DB password)
#   - localhost/nutriscrape:latest built from the committed WS-A code
#
# Usage:
#   deploy/scripts/full-reingest.sh                 # build + verify into the rebuild volume
#   deploy/scripts/full-reingest.sh --status        # show stage checkpoints
#   deploy/scripts/full-reingest.sh --reset         # drop checkpoints AND the rebuild volume, start over
#   deploy/scripts/full-reingest.sh --teardown      # stop+remove the rebuild Neo4j (keeps the volume)

set -euo pipefail

# --- Config (environment-overridable; nothing host-specific hardcoded) --------------------------
NETWORK="${NECTAR_NETWORK:-nectar-run}"
NUTRISCRAPE_IMAGE="${NUTRISCRAPE_IMAGE:-localhost/nutriscrape:latest}"
NEO4J_IMAGE="${NEO4J_IMAGE:-docker.io/library/neo4j:5.20}"
REBUILD_CT="${REBUILD_CT:-neo4j-rebuild}"
REBUILD_VOL="${REBUILD_VOL:-neo4j-rebuild-data}"
CORPUS_VOL="${CORPUS_VOL:-corpus-staging}"
FDC_VOL="${FDC_VOL:-fdc-staging}"
BULK_VOL="${BULK_VOL:-bulk-import}"
SECRET_NAME="${SECRET_NAME:-nectar_neo4j_pass}"
CORPUS_PATH="${NUTRISCRAPE_CORPUS:-/data/recipes_full.csv}"   # path INSIDE the container
FDC_BULK_DIR="${FDC_BULK_DIR:-/fdc}"                          # path INSIDE the container
PARALLEL="${NUTRISCRAPE_MAX_PARALLEL:-4}"
HEAP="${NEO4J_HEAP:-16G}"
PAGECACHE="${NEO4J_PAGECACHE:-24G}"
CKPT_DIR="${CKPT_DIR:-${XDG_STATE_HOME:-$HOME/.local/state}/nectar/reingest}"

# The build DAG. Default: the bulk path - bulk-export resolves the whole corpus in memory (no
# per-recipe Neo4j round-trips) and writes CSVs to the shared import volume, then bulk-load LOAD
# CSVs them single-threaded. This is the corpus-scale path (the Prefect `flow` serializes huge
# batch inputs and stalls; the single-process `ingest` is steady but ~10 recipes/s). Overrides:
#   NUTRISCRAPE_STAGES="schema knowledge fdc-import ingest cluster materialize dish-stats"   (single-process)
#   NUTRISCRAPE_STAGES="flow dish-stats"                                                     (parallel flow)
read -r -a STAGES <<< "${NUTRISCRAPE_STAGES:-schema knowledge fdc-import bulk-export bulk-load cluster bulk-materialize-export bulk-materialize-load dish-stats}"

log()  { printf '\033[1;32m[reingest]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[reingest]\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31m[reingest] error:\033[0m %s\n' "$*" >&2; exit 1; }

secret_value() { podman secret inspect "$SECRET_NAME" --showsecret --format '{{.SecretData}}' 2>/dev/null; }

teardown() { podman rm -f "$REBUILD_CT" >/dev/null 2>&1 || true; }

# --- Subcommands --------------------------------------------------------------------------------
CHECK_ONLY=0
case "${1:-}" in
  --status)
    for s in "${STAGES[@]}"; do
      [ -f "$CKPT_DIR/$s.done" ] && echo "  [x] $s" || echo "  [ ] $s"
    done
    exit 0 ;;
  --teardown) teardown; log "removed $REBUILD_CT (volume $REBUILD_VOL kept)"; exit 0 ;;
  --reset)
    teardown
    podman volume rm "$REBUILD_VOL" >/dev/null 2>&1 || true
    rm -rf "$CKPT_DIR"
    log "reset: dropped checkpoints and volume $REBUILD_VOL"; exit 0 ;;
  --check) CHECK_ONLY=1 ;;   # run preflight and exit, without starting the rebuild
  "") ;;
  *) die "unknown option: $1 (use --check | --status | --reset | --teardown)" ;;
esac

# --- Preflight ----------------------------------------------------------------------------------
command -v podman >/dev/null 2>&1 || die "podman not on PATH"
podman network exists "$NETWORK" || die "network $NETWORK missing"
podman image exists "$NUTRISCRAPE_IMAGE" || die "image $NUTRISCRAPE_IMAGE not built"
podman secret exists "$SECRET_NAME" 2>/dev/null || die "secret $SECRET_NAME missing (run provision-secrets.sh)"
podman volume exists "$CORPUS_VOL" || die "corpus volume $CORPUS_VOL missing - stage the RecipeNLG CSV first"
podman volume exists "$FDC_VOL"    || die "fdc volume $FDC_VOL missing - stage the USDA FDC bulk CSVs first"

CORPUS_MNT="$(podman volume inspect "$CORPUS_VOL" --format '{{.Mountpoint}}')"
[ -n "$(ls -A "$CORPUS_MNT" 2>/dev/null)" ] || die "corpus volume $CORPUS_VOL is empty - stage recipes_full.csv"
FDC_MNT="$(podman volume inspect "$FDC_VOL" --format '{{.Mountpoint}}')"
[ -n "$(ls -A "$FDC_MNT" 2>/dev/null)" ] || die "fdc volume $FDC_VOL is empty - stage the FDC bulk CSVs"

PW="$(secret_value)"; [ -n "$PW" ] || die "could not read secret $SECRET_NAME"
mkdir -p "$CKPT_DIR"

if [ "$CHECK_ONLY" -eq 1 ]; then
  log "preflight OK - corpus and FDC staged, secret and image present. Ready to run."
  log "corpus: $CORPUS_VOL ($(du -sh "$CORPUS_MNT" 2>/dev/null | cut -f1)) -> $CORPUS_PATH in-container"
  log "launch with: NUTRISCRAPE_CORPUS=$CORPUS_PATH deploy/scripts/full-reingest.sh"
  exit 0
fi

# --- Start the rebuild Neo4j on its own volume (never the live one) ------------------------------
podman volume exists "$BULK_VOL" || podman volume create "$BULK_VOL" >/dev/null
if ! podman container exists "$REBUILD_CT"; then
  log "starting rebuild Neo4j ($REBUILD_CT) on volume $REBUILD_VOL"
  podman run -d --name "$REBUILD_CT" --network "$NETWORK" \
    -v "$REBUILD_VOL:/data" \
    -v "$BULK_VOL:/var/lib/neo4j/import" \
    -e NEO4J_AUTH="neo4j/$PW" \
    -e NEO4J_server_memory_heap_initial__size="$HEAP" \
    -e NEO4J_server_memory_heap_max__size="$HEAP" \
    -e NEO4J_server_memory_pagecache_size="$PAGECACHE" \
    -e NEO4J_db_transaction_timeout=0 \
    "$NEO4J_IMAGE" >/dev/null
elif [ "$(podman inspect "$REBUILD_CT" --format '{{.State.Status}}')" != "running" ]; then
  podman start "$REBUILD_CT" >/dev/null
fi

log "waiting for rebuild Neo4j to accept Bolt..."
for _ in $(seq 1 60); do
  if podman exec "$REBUILD_CT" cypher-shell -u neo4j -p "$PW" "RETURN 1;" >/dev/null 2>&1; then break; fi
  sleep 5
done
podman exec "$REBUILD_CT" cypher-shell -u neo4j -p "$PW" "RETURN 1;" >/dev/null 2>&1 \
  || die "$REBUILD_CT did not become ready"

# --- Run the DAG stage by stage, checkpointed ---------------------------------------------------
run_stage() {
  local stage="$1"
  podman run --rm --network "$NETWORK" \
    -e NEO4J_URI="bolt://$REBUILD_CT:7687" -e NEO4J_USER=neo4j -e NEO4J_PASSWORD="$PW" \
    -e NUTRISCRAPE_CORPUS="$CORPUS_PATH" -e NUTRISCRAPE_SOURCE_ID=recipenlg \
    -e FDC_BULK_DIR="$FDC_BULK_DIR" -e NUTRISCRAPE_MAX_PARALLEL="$PARALLEL" \
    -e BULK_OUT_DIR=/import \
    -v "$CORPUS_VOL:/data:Z" -v "$FDC_VOL:/fdc:Z" -v "$BULK_VOL:/import:Z" \
    "$NUTRISCRAPE_IMAGE" "$stage"
}

log "corpus rows: $(podman run --rm -v "$CORPUS_VOL:/data:Z" "$NUTRISCRAPE_IMAGE" \
      python -c "import sys; print(sum(1 for _ in open('$CORPUS_PATH', encoding='utf-8')) - 1)" 2>/dev/null || echo '?')"

for stage in "${STAGES[@]}"; do
  if [ -f "$CKPT_DIR/$stage.done" ]; then log "skip $stage (checkpoint present)"; continue; fi
  log "=== stage: $stage ==="
  START=$(date +%s 2>/dev/null || echo 0)
  run_stage "$stage"
  END=$(date +%s 2>/dev/null || echo 0)
  touch "$CKPT_DIR/$stage.done"
  log "stage $stage complete ($(( (END - START) / 60 )) min)"
done

# --- Report; the swap is manual (see the runbook) -----------------------------------------------
log "rebuild complete into volume $REBUILD_VOL. Acceptance snapshot:"
podman exec "$REBUILD_CT" cypher-shell -u neo4j -p "$PW" --format plain \
  "MATCH (n) RETURN labels(n)[0] AS label, count(*) AS n ORDER BY n DESC LIMIT 6;" || true
cat <<EOF

Next steps (manual, gated - see deploy/runbooks/full-reingest.md):
  1. Verify the acceptance checks in the runbook against $REBUILD_CT.
  2. Swap: stop services, point the neo4j-full quadlet Volume= at $REBUILD_VOL, restart.
  3. Keep the old volume as rollback until you are satisfied.
EOF
