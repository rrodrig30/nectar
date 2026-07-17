"""Corpus-scale alternative-preparation variant materialization, on the bulk pattern.

The transactional `materialize` stage (pipeline.py) reads every ingested recipe back out of the
graph and writes its alternative-method variants one statement at a time. That is single-threaded
and, at 2.2M recipes, client round trips per statement make it a multi-day job; parallel graph
writers instead deadlock on the shared :Nutrient nodes every HAS_NUTRIENT edge touches.

This module applies the same split the bulk ingest path uses: re-derive each recipe from the corpus
with the in-memory FDC index (pure CPU, embarrassingly parallel, no Neo4j), compute the bounded set
of alternative-method variants with the same four-channel `nutrition.compose` math, and write two
CSVs. A single-writer `LOAD CSV` then loads them, so the hot shared nodes never see concurrent
writers. The as-authored variant is already in the graph (bulk-load); this adds the alternatives
(is_as_authored=false). Output is identical to and mergeable with the transactional path: the same
variant_id (`<recipe_id>:variant:<method>`) and the same `nutrition.variants.alternative_methods`
selection.
"""
from __future__ import annotations

import logging
import multiprocessing as mp
import os
from pathlib import Path
from typing import Any

from nutriscrape.acquisition.adapters.base import RawRecipe
from nutriscrape.acquisition.adapters.datasets import RecipeNlgAdapter
from nutriscrape.bulk.export import (
    ExportStats,
    _chunked,
    _concatenate_shards,
    _default_workers,
    _nutrient_units,
    _Writers,
    ingredient_facts,
    resolve_recipe_ingredients,
)
from nutriscrape.bulk.food_index import FoodIndex
from nutriscrape.graph.client import GraphClient
from nutriscrape.knowledge.loaders import TransformCoeff, load_transforms
from nutriscrape.nutrition.compose import (
    IngredientFacts,
    compose_serving_vector,
    serving_facts,
)
from nutriscrape.nutrition.transform import Preparation
from nutriscrape.nutrition.variants import alternative_methods

logger = logging.getLogger(__name__)

# The two alt-variant CSVs. Headers mirror the as-authored variants/has_nutrient files so the load
# statements are near-identical; the difference is is_as_authored=false, set in the load.
_ALT_FILES: dict[str, list[str]] = {
    "alt_variants": ["variant_id", "recipe_id", "confidence",
                     "serving_mass_g", "energy_kcal", "fluid_ml"],
    "alt_has_nutrient": ["variant_id", "nutrient_id", "amount_per_serving", "unit",
                         "source", "confidence"],
}

_CHUNK_SIZE = 2_000


def _facts_under_method(fact: IngredientFacts, method: str) -> IngredientFacts:
    """Re-cook one ingredient under an alternative method, keeping its cut and liquid handling. The
    bulk twin of pipeline._facts_under_method, on IngredientFacts."""
    prep = Preparation(
        method=method, cut_class=fact.prep.cut_class, water_ratio=fact.prep.water_ratio,
        liquid_retained_frac=fact.prep.liquid_retained_frac, time_min=fact.prep.time_min,
        temp_c=fact.prep.temp_c,
    )
    return IngredientFacts(
        fdc_id=fact.fdc_id, food_classes=fact.food_classes, mass_g=fact.mass_g,
        prep=prep, raw_per_100g=fact.raw_per_100g, is_liquid=fact.is_liquid,
    )


def export_alt_variants(
    raw: RawRecipe,
    index: FoodIndex,
    transforms: list[TransformCoeff],
    units: dict[str, str],
    coverage: dict[str, list[str]],
    writers: dict[str, Any],
    stats: ExportStats,
) -> None:
    """Re-derive one recipe and append its bounded alternative-method variants (each a cooked
    per-serving vector) to the alt CSVs. A recipe that yields at least one alternative variant counts
    as written; one whose only methods are the as-authored set (or resolves to nothing) is skipped."""
    resolved = resolve_recipe_ingredients(raw, index, stats)
    facts = ingredient_facts(resolved)
    if not facts:
        stats.recipes_skipped += 1
        return
    classes = {food_class for fact in facts for food_class in fact.food_classes}
    authored = {fact.prep.method for fact in facts}
    methods = alternative_methods(classes, authored, coverage)
    wrote_any = False
    for method in methods:
        method_facts = [_facts_under_method(fact, method) for fact in facts]
        cooked = compose_serving_vector(method_facts, transforms, raw.servings)
        if not cooked:
            continue
        sf = serving_facts(method_facts, cooked, raw.servings)
        variant_id = f"{raw.recipe_id}:variant:{method}"
        writers["alt_variants"].writerow([
            variant_id, raw.recipe_id,
            min((n.confidence for n in cooked.values()), default=0.5),
            sf.serving_mass_g,
            "" if sf.energy_kcal is None else sf.energy_kcal,
            "" if sf.fluid_ml is None else sf.fluid_ml,
        ])
        for nutrient_id, nutrient in cooked.items():
            writers["alt_has_nutrient"].writerow([
                variant_id, nutrient_id, nutrient.amount, units.get(nutrient_id, ""),
                nutrient.source, nutrient.confidence,
            ])
        wrote_any = True
    if wrote_any:
        stats.recipes_written += 1
    else:
        stats.recipes_skipped += 1


def _export_stream(
    recipes: Any, index: FoodIndex, transforms: list[TransformCoeff], units: dict[str, str],
    coverage: dict[str, list[str]], out: Path, log_every: int = 0,
) -> ExportStats:
    """Single-process alt-variant export of a recipe stream to the alt CSVs under `out`."""
    stats = ExportStats()
    with _Writers(out, _ALT_FILES) as writers:
        for i, raw in enumerate(recipes, start=1):
            export_alt_variants(raw, index, transforms, units, coverage, writers.writers, stats)
            if log_every and i % log_every == 0:
                logger.info("bulk-materialize: %d recipes read, %d with alt variants",
                            i, stats.recipes_written)
    return stats


# Set once in the parent before the fork pool, so each worker inherits the read-only index,
# coefficients, and coverage through copy-on-write memory instead of pickling them per task.
_INDEX: FoodIndex | None = None
_TRANSFORMS: list[TransformCoeff] | None = None
_UNITS: dict[str, str] | None = None
_COVERAGE: dict[str, list[str]] | None = None


def _export_shard(task: tuple[int, list[RawRecipe], str]) -> tuple[int, int, int]:
    """Worker entry: export one chunk's alt variants to out/shard_<idx>/*.csv, using the
    fork-inherited globals. Returns (written, skipped, unresolved)."""
    idx, recipes, out_dir = task
    assert (_INDEX is not None and _TRANSFORMS is not None and _UNITS is not None
            and _COVERAGE is not None)
    stats = _export_stream(recipes, _INDEX, _TRANSFORMS, _UNITS, _COVERAGE,
                           Path(out_dir) / f"shard_{idx}")
    return stats.recipes_written, stats.recipes_skipped, stats.ingredients_unresolved


def _load_method_coverage() -> dict[str, list[str]]:
    """food_class -> culinarily-valid cooking methods, from config/method_coverage.yaml."""
    from nutriscrape.common.config import load_config

    data = load_config("method_coverage").get("method_coverage", {}) or {}
    return {str(key): [str(method) for method in (value or [])] for key, value in data.items()}


def run_bulk_materialize_export(
    corpus_path: str, fdc_dir: str, out_dir: str, workers: int | None = None
) -> ExportStats:
    """Stream `corpus_path` through in-memory resolution + alternative-method cooking and write the
    alt-variant CSVs under `out_dir`. Parallel over a fork pool (resolve+cook is CPU-bound and
    embarrassingly parallel); `workers` defaults to NUTRISCRAPE_MAX_PARALLEL or the CPU count."""
    from nutriscrape.common.config import default_config_dir

    logger.info("bulk-materialize: building in-memory FDC index from %s", fdc_dir)
    index = FoodIndex.from_fdc_csv(fdc_dir)
    logger.info("bulk-materialize: indexed %d FDC foods", len(index))
    transforms = load_transforms(default_config_dir())
    units = _nutrient_units()
    coverage = _load_method_coverage()
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    n_workers = workers if workers is not None else _default_workers()
    if n_workers <= 1:
        stats = _export_stream(RecipeNlgAdapter(corpus_path).recipes(), index, transforms, units,
                               coverage, out, log_every=100_000)
        logger.info("bulk-materialize: done (serial). %d recipes with alt variants, %d skipped",
                    stats.recipes_written, stats.recipes_skipped)
        return stats

    global _INDEX, _TRANSFORMS, _UNITS, _COVERAGE
    _INDEX, _TRANSFORMS, _UNITS, _COVERAGE = index, transforms, units, coverage
    tasks = (
        (idx, chunk, str(out))
        for idx, chunk in enumerate(_chunked(RecipeNlgAdapter(corpus_path).recipes(), _CHUNK_SIZE))
    )
    total = ExportStats()
    shard_count = 0
    ctx = mp.get_context("fork")   # fork so workers inherit _INDEX without pickling it
    with ctx.Pool(n_workers) as pool:
        for written, skipped, unresolved in pool.imap_unordered(_export_shard, tasks):
            total.recipes_written += written
            total.recipes_skipped += skipped
            total.ingredients_unresolved += unresolved
            shard_count += 1
            if shard_count % 50 == 0:
                logger.info("bulk-materialize: %d shards done, %d recipes with alt variants",
                            shard_count, total.recipes_written)
    _concatenate_shards(out, [out / f"shard_{i}" for i in range(shard_count)], _ALT_FILES)
    logger.info("bulk-materialize: done (%d workers). %d recipes with alt variants, %d skipped; "
                "CSVs in %s", n_workers, total.recipes_written, total.recipes_skipped, out)
    return total


# --- Load stage: single-writer LOAD CSV of the alt variants (mirrors bulk/load.py) --------------

_BATCH = 5000

_LOAD_ALT_VARIANTS = f"""
LOAD CSV WITH HEADERS FROM 'file:///alt_variants.csv' AS row
CALL {{ WITH row
  MATCH (r:Recipe {{recipe_id: row.recipe_id}})
  MERGE (v:RecipeVariant {{variant_id: row.variant_id}})
  SET v.is_as_authored = false, v.confidence = toFloat(row.confidence),
      v.serving_mass_g = toFloat(row.serving_mass_g),
      v.energy_kcal = CASE WHEN row.energy_kcal = '' THEN null ELSE toFloat(row.energy_kcal) END,
      v.fluid_ml = CASE WHEN row.fluid_ml = '' THEN null ELSE toFloat(row.fluid_ml) END
  MERGE (r)-[:HAS_VARIANT]->(v)
}} IN TRANSACTIONS OF {_BATCH} ROWS
"""

_LOAD_ALT_HAS_NUTRIENT = f"""
LOAD CSV WITH HEADERS FROM 'file:///alt_has_nutrient.csv' AS row
CALL {{ WITH row
  MATCH (v:RecipeVariant {{variant_id: row.variant_id}})
  MATCH (n:Nutrient {{nutrient_id: row.nutrient_id}})
  MERGE (v)-[h:HAS_NUTRIENT]->(n)
  SET h.amount_per_serving = toFloat(row.amount_per_serving), h.unit = row.unit,
      h.source = row.source, h.confidence = toFloat(row.confidence),
      h.computed_by = 'nutrition.compose', h.contract_version = $contract_version
}} IN TRANSACTIONS OF {_BATCH} ROWS
"""

_STEPS: list[tuple[str, str]] = [
    ("alt_variants", _LOAD_ALT_VARIANTS),
    ("alt_has_nutrient", _LOAD_ALT_HAS_NUTRIENT),
]


def run_bulk_materialize_load(client: GraphClient) -> None:
    """LOAD CSV the alt-variant CSVs (in Neo4j's import dir) in dependency order (variants before
    their nutrient edges), single-threaded so the shared :Nutrient nodes never see concurrent
    writers. Idempotent (every statement MERGEs). Assumes bulk-load created the :Recipe nodes and the
    knowledge load created the :Nutrient nodes these statements MATCH."""
    contract_version = os.environ.get("CONTRACT_VERSION", "1.0")
    for name, statement in _STEPS:
        logger.info("bulk-materialize-load: loading %s.csv ...", name)
        client.run(statement, contract_version=contract_version)
        logger.info("bulk-materialize-load: %s.csv loaded", name)
    logger.info("bulk-materialize-load: all alt-variant CSVs loaded")
