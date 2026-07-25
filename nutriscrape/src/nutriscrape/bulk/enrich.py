"""Enrich :Recipe nodes with the human-readable ingredient lines and cooking directions.

The ingestion pipeline resolves each ingredient to an FDC food for nutrition, but it does not store
the original recipe text, so the recipe view cannot show how to actually make the meal (real
quantities as written, and the step-by-step method). Both are present in the corpus. This is a fast,
ADDITIVE pass: it re-reads the corpus and sets `ingredient_lines` and `directions` on the matching
:Recipe node (by recipe_id), streamed as UNWIND batches over Bolt. No food re-resolution, no
re-clustering, and nothing is deleted, so it is safe to run against the live graph.
"""
from __future__ import annotations

import logging

from nutriscrape.acquisition.adapters.datasets import RecipeNlgAdapter
from nutriscrape.graph.client import GraphClient

logger = logging.getLogger(__name__)

# MATCH (never create): a recipe skipped at ingest (no resolved food) has no node, and is left as is.
_UPDATE = """
UNWIND $batch AS row
MATCH (r:Recipe {recipe_id: row.id})
SET r.ingredient_lines = row.ingredients, r.directions = row.directions
"""


def enrich_recipes(
    client: GraphClient, corpus_path: str, batch_size: int = 1000, log_every: int = 200_000
) -> int:
    """Set `ingredient_lines` and `directions` on every :Recipe that exists in the graph, from the
    corpus row of the same recipe_id. Returns the number of corpus rows processed (a row whose recipe
    was skipped at ingest simply matches nothing). Streams UNWIND batches so memory stays bounded."""
    batch: list[dict[str, object]] = []
    processed = 0

    def flush() -> None:
        nonlocal processed, batch
        if not batch:
            return
        client.run_write(_UPDATE, {"batch": batch})
        processed += len(batch)
        batch = []  # a fresh list; do not mutate the one just handed to run_write
        if log_every and processed % log_every == 0:
            logger.info("enrich: %d recipes processed", processed)

    for raw in RecipeNlgAdapter(corpus_path).recipes():
        batch.append({
            "id": raw.recipe_id,
            "ingredients": list(raw.ingredient_lines),
            "directions": list(raw.preparation_steps),
        })
        if len(batch) >= batch_size:
            flush()
    flush()
    logger.info("enrich: done, %d corpus rows processed", processed)
    return processed
