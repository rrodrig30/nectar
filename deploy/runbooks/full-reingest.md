# Runbook: full corpus re-ingest (Approach B - fresh DB, then swap)

Rebuild the recipe/dish side of the graph from the source corpus, applying every WS-A fix at scale
(real gram masses, mineral-leaching transforms, method carryover, the base-food matcher, idempotent
writes) and restoring any overwritten recipe ids. The live graph keeps serving until you swap.

**Time:** a multi-hour-to-~2-day batch (the original build's recipe side ran ~18 h; `dish-stats`
alone ~3 h). Runs unattended and restartable.

**Blast radius:** none until the swap. The rebuild writes a separate `neo4j-rebuild-data` volume;
the live `neo4j-full-data` is untouched and is your rollback.

---

## 0. Prerequisites

| Requirement | Check | Fix |
|---|---|---|
| RecipeNLG corpus staged | `podman volume inspect corpus-staging` has `recipes_full.csv` | `podman volume import corpus-staging recipes_full.csv` |
| USDA FDC bulk CSVs staged | `fdc-staging` holds `food.csv`, `nutrient.csv`, `food_nutrient.csv` | download from fdc.nal.usda.gov, extract into the volume |
| DB password secret | `podman secret exists nectar_neo4j_pass` | `deploy/scripts/provision-secrets.sh` |
| Image built from WS-A code | `podman image exists localhost/nutriscrape:latest` | `podman build -t localhost/nutriscrape:latest -f nutriscrape/Containerfile .` |

The FDC layer is rebuilt from the bulk CSVs (`fdc-import`), so both the corpus **and** the FDC bulk
must be staged. The driver preflights all of this and refuses to start if anything is missing.

---

## 1. Build the new graph

Verify readiness first (preflights the prerequisites without starting anything):

```bash
deploy/scripts/full-reingest.sh --check
```

Then launch (long-running; run it detached):

```bash
deploy/scripts/full-reingest.sh
```

The driver starts a separate `neo4j-rebuild` container on the `neo4j-rebuild-data` volume, then runs
the DAG stage by stage:

```
schema -> knowledge -> fdc-import -> ingest -> cluster -> materialize -> dish-stats
```

It is **restartable**: each stage writes a checkpoint under `~/.local/state/nectar/reingest`, so a
re-run resumes at the first unfinished stage. Every stage is idempotent, so re-running a finished
one is harmless.

```bash
deploy/scripts/full-reingest.sh --status     # stage checklist
deploy/scripts/full-reingest.sh              # resume
deploy/scripts/full-reingest.sh --reset      # drop checkpoints AND the rebuild volume, start over
```

Tune `NUTRISCRAPE_MAX_PARALLEL`, `NEO4J_HEAP`, `NEO4J_PAGECACHE` to the host before launching.
Run it detached (`systemd-run --user --scope`, `tmux`, or `nohup`) since it is long.

---

## 2. Acceptance checks (against `neo4j-rebuild`, before swapping)

Do not swap until these pass. Run with the DB password:

```bash
PW=$(podman secret inspect nectar_neo4j_pass --showsecret --format '{{.SecretData}}')
q() { podman exec neo4j-rebuild cypher-shell -u neo4j -p "$PW" --format plain "$1"; }
```

1. **Scale is comparable to the live graph** (recipes/dishes in the millions):
   ```
   q "MATCH (n) RETURN labels(n)[0] AS label, count(*) AS n ORDER BY n DESC LIMIT 8;"
   ```
2. **Masses and nutrients are plausible** (no 2 g potatoes, no 14,000 kcal servings). Spot-check a
   few dishes; energy per serving should sit in a food-plausible range.
3. **The overwritten recipes are restored** (real content, not the sample):
   ```
   q "MATCH (r:Recipe) WHERE r.recipe_id IN ['recipenlg:0','recipenlg:1'] RETURN r.recipe_id, r.title;"
   ```
4. **The cooking model bites** - boiled-drained vs kept-liquid diverges on potassium for a leafy or
   root vegetable dish (the CKD scenario).
5. **Every value carries provenance** (source, confidence, evidence_tier, contract_version).

---

## 3. Swap (gated, ~1 minute of downtime)

Point the live Neo4j at the rebuilt volume by editing one line in its quadlet. The old volume is
kept as the rollback.

```bash
systemctl --user stop nectar-web nectar-api neo4j-full

# Edit ~/.config/containers/systemd/neo4j-full.container:
#   Volume=neo4j-full-data:/data   ->   Volume=neo4j-rebuild-data:/data
# (leave neo4j-full-data in place - it is the rollback)

systemctl --user daemon-reload
systemctl --user start neo4j-full nectar-api nectar-web
deploy/scripts/full-reingest.sh --teardown     # stop the now-idle rebuild container
```

Confirm the live app serves the new data:
```bash
curl -s -o /dev/null -w '%{http_code}\n' http://localhost:8082/
curl -s 'http://localhost:8082/api/dishes/search?q=chicken%20soup&limit=2'
```

---

## 4. Rollback

If anything looks wrong after the swap, revert the one line and restart:

```bash
systemctl --user stop nectar-web nectar-api neo4j-full
# neo4j-full.container: Volume=neo4j-rebuild-data:/data  ->  Volume=neo4j-full-data:/data
systemctl --user daemon-reload
systemctl --user start neo4j-full nectar-api nectar-web
```

---

## 5. Cleanup (only once you are confident, days later)

```bash
podman volume rm neo4j-full-data.old 2>/dev/null || true   # if you renamed the old one
# or, to reclaim the rollback volume when certain:
# podman volume rm neo4j-full-data     # DANGER: removes the pre-reingest graph
```

Keep the rollback volume until the new graph has served real use without issue. Disk is cheap
(each graph is ~18 GB; the host has ample free space).

---

## Notes

- **Why a full rebuild, not just ingest:** food resolution changes, so dish clustering fingerprints
  change; `cluster`, `materialize`, and `dish-stats` must re-run downstream of `ingest`.
- **Idempotency:** `clear_recipe_composition` drops each recipe's prior edges before rewriting, so
  even an in-place re-run would not double-count - but Approach B keeps the live graph clean and
  gives you a rollback, which is why it is preferred.
- **Restartability:** the DAG stages are individually idempotent; the driver's checkpoints let a
  crashed run resume rather than restart from `schema`.
