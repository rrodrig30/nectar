"""Prefect orchestration: the staged batch DAG for corpus-scale runs.

Wraps the sequential stage functions in `pipeline.py` as Prefect tasks and fans the per-recipe
ingest out over parallel batches, so the embarrassingly-parallel ingest (each recipe is independent)
scales across workers instead of running one recipe at a time. Stages run in dependency order:
schema -> knowledge -> fdc-import -> (parallel ingest batches) -> cluster -> materialize. Cluster and
materialize are corpus-wide and run once every ingest batch has completed.

Idempotency plus retries give restartability: every writer MERGEs, so a retried task or a re-run
batch is safe. Parallelism is bounded by NUTRISCRAPE_MAX_PARALLEL (the number of ingest batches);
because each batch opens its own Neo4j session, this also bounds concurrent database sessions.
Parallel ingest chiefly benefits the local-resolution path (fdc-import first); running many batches
against the FDC API would only exhaust its rate limit faster.

Requires Prefect (`pip install prefect`), an optional dependency, so this module is imported only
when running the flow, never by `make check`. Run with:
`python -m nutriscrape.orchestration.flows` (or `make flow`).
"""
from __future__ import annotations

import logging
import os

from prefect import flow, task, unmapped

from nutriscrape import pipeline
from nutriscrape.acquisition.adapters.base import RawRecipe

logger = logging.getLogger(__name__)

_DEFAULT_MAX_PARALLEL = 4


def _max_parallel() -> int:
    raw = os.environ.get("NUTRISCRAPE_MAX_PARALLEL")
    if raw is None:
        return _DEFAULT_MAX_PARALLEL
    try:
        return max(1, int(raw))
    except ValueError:
        return _DEFAULT_MAX_PARALLEL


def _fdc_api_available() -> bool:
    from nutriscrape.resolution.fdc_client import FdcClient, FdcConfigError

    try:
        FdcClient()
    except FdcConfigError:
        return False
    return True


@task(retries=2, retry_delay_seconds=5)
def schema_task() -> None:
    pipeline.run_schema()


@task(retries=2, retry_delay_seconds=5)
def knowledge_task() -> None:
    pipeline.run_knowledge()


@task(retries=2, retry_delay_seconds=5)
def fdc_import_task() -> None:
    pipeline.run_fdc_import()


@task(retries=3, retry_delay_seconds=10)
def ingest_batch_task(recipes: list[RawRecipe], use_local: bool) -> int:
    return pipeline.ingest_batch(recipes, use_local)


@task(retries=2, retry_delay_seconds=5)
def cluster_task() -> None:
    pipeline.run_cluster()


@task(retries=2, retry_delay_seconds=5)
def materialize_task() -> None:
    pipeline.run_materialize()


@flow(name="nutriscrape")
def nutriscrape_flow(max_parallel: int | None = None) -> None:
    """The full corpus build as one Prefect flow. Stages run in dependency order (the direct task
    calls are sequential); the ingest step fans out over parallel batches via Prefect's default
    concurrent (thread-pool) task runner."""
    schema_task()
    knowledge_task()
    fdc_import_task()

    recipes = pipeline.acquire_recipes()
    if not recipes:
        logger.warning("flow: no recipes acquired; skipping ingest, cluster, and materialize")
        return

    use_local = pipeline.local_resolution_available()
    if not use_local and not _fdc_api_available():
        logger.warning(
            "flow: %d recipe(s) acquired but no local :Food graph (run fdc-import) and no "
            "FDC_API_KEY; skipping ingest, cluster, and materialize.",
            len(recipes),
        )
        return

    batches = pipeline.split_into_batches(recipes, max_parallel or _max_parallel())
    logger.info(
        "flow: ingesting %d recipe(s) across %d parallel batch(es) (%s resolution)",
        len(recipes), len(batches), "local" if use_local else "FDC API",
    )
    futures = ingest_batch_task.map(batches, unmapped(use_local))
    ingested = sum(future.result() for future in futures)
    logger.info("flow: ingested %d recipe(s)", ingested)

    cluster_task()
    materialize_task()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    nutriscrape_flow()
