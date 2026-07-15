"""Bulk-load path: resolve + cook recipes in memory, export CSVs, and load them with a single
`LOAD CSV` pass. This replaces the per-recipe transactional ingest for corpus-scale runs, which is
both resolution-latency bound single-threaded and deadlocks on the shared :Nutrient supernodes when
parallelized. See ``food_index.py`` (in-memory resolution), ``export.py`` (compute -> CSV), and
``load.py`` (CSV -> Neo4j, single writer, no deadlocks)."""
