"""Compute stage of the bulk-load path: stream the corpus, resolve + cook each recipe in memory,
and write node/relationship CSVs for `bulk/load.py` to bulk-load.

No Neo4j is touched here. Resolution is an in-memory `FoodIndex` lookup and the four-channel cooked
nutrition is the same `nutrition.compose` math the transactional path uses, so every nutrient value
is still computed by the transform, never asserted. The RecipeNLG adapter streams recipes one at a
time, so the 2.2M-row corpus never has to be held in memory.
"""
from __future__ import annotations

import csv
import logging
import multiprocessing as mp
import os
from dataclasses import dataclass
from itertools import islice
from pathlib import Path
from typing import Any, Iterable, Iterator, TextIO

from nutriscrape.acquisition.adapters.base import RawRecipe
from nutriscrape.acquisition.adapters.datasets import RecipeNlgAdapter
from nutriscrape.acquisition.parse import basic_preparation, parse_ingredient_basic
from nutriscrape.bulk.food_index import FoodIndex
from nutriscrape.common.config import load_config
from nutriscrape.common.units import UnitError
from nutriscrape.extraction.preparation import ParsedPreparation
from nutriscrape.knowledge.loaders import TransformCoeff, load_transforms
from nutriscrape.nutrition.compose import IngredientFacts, compose_serving_vector
from nutriscrape.nutrition.normalize import to_canonical
from nutriscrape.nutrition.transform import Preparation
from nutriscrape.resolution.nutrient_map import classify_food

logger = logging.getLogger(__name__)

# One CSV per node/relationship kind. Headers double as LOAD CSV column names (bulk/load.py).
_FILES: dict[str, list[str]] = {
    "recipes": ["recipe_id", "title", "source_id", "license", "servings", "confidence"],
    "variants": ["variant_id", "recipe_id", "confidence"],
    "preparations": ["prep_id", "method", "cut_class", "water_ratio",
                     "liquid_retained_frac", "time_min", "temp_c"],
    "contains": ["recipe_id", "fdc_id", "raw_mass_g", "prep_id"],
    "has_nutrient": ["variant_id", "nutrient_id", "amount_per_serving", "unit",
                     "source", "confidence"],
}


@dataclass
class ExportStats:
    recipes_written: int = 0
    recipes_skipped: int = 0       # no resolved ingredient carried a nutrient vector
    ingredients_unresolved: int = 0


def _to_prep(prep: ParsedPreparation | None) -> Preparation:
    if prep is None:
        return Preparation(method="raw", liquid_retained_frac=1.0)
    return Preparation(method=prep.method, cut_class=prep.cut_class or "whole",
                       water_ratio=prep.water_ratio, liquid_retained_frac=prep.liquid_retained_frac,
                       time_min=prep.time_min, temp_c=prep.temp_c)


def _nutrient_units() -> dict[str, str]:
    """contract nutrient_id -> canonical unit, from config/nutrients.yaml (for HAS_NUTRIENT unit)."""
    data = load_config("nutrients")
    return {str(e["id"]): str(e.get("unit", "")) for e in data.get("nutrients", []) or []}


class _Writers:
    """Open csv.writer per file, header written once. Closed together via the context manager."""

    def __init__(self, out_dir: Path) -> None:
        out_dir.mkdir(parents=True, exist_ok=True)
        self._handles: dict[str, TextIO] = {}
        self.writers: dict[str, Any] = {}
        for name, header in _FILES.items():
            handle = (out_dir / f"{name}.csv").open("w", encoding="utf-8", newline="")
            writer = csv.writer(handle)
            writer.writerow(header)
            self._handles[name] = handle
            self.writers[name] = writer

    def __enter__(self) -> "_Writers":
        return self

    def __exit__(self, *exc: object) -> None:
        for handle in self._handles.values():
            handle.close()


def export_recipe(
    raw: RawRecipe,
    index: FoodIndex,
    transforms: list[TransformCoeff],
    units: dict[str, str],
    writers: dict[str, Any],
    stats: ExportStats,
) -> None:
    """Resolve + cook one recipe and append its rows to the CSVs. Mirrors `_ingest_recipe`'s compute
    (parse -> resolve -> canonical mass -> four-channel cooked vector) but writes CSV, not Neo4j."""
    ingredients = [parse_ingredient_basic(line) for line in raw.ingredient_lines]
    refs = [ing.food for ing in ingredients]
    preps = basic_preparation(raw.preparation_steps, refs)
    prep_by_ref = {p.applies_to[0]: p for p in preps if p.applies_to}

    facts: list[IngredientFacts] = []
    contains_rows: list[list[object]] = []
    prep_rows: list[list[object]] = []
    for ing in ingredients:
        resolved = index.resolve(ing.food)
        if resolved is None:
            stats.ingredients_unresolved += 1
            continue
        try:
            canonical = to_canonical(ing.quantity or 0.0, ing.unit or "g")
        except UnitError:
            continue
        prep = _to_prep(prep_by_ref.get(ing.food))
        prep_id = f"{raw.recipe_id}:{resolved.fdc_id}"
        raw_vec = index.raw_vector(resolved.fdc_id)
        prep_rows.append([prep_id, prep.method, prep.cut_class, prep.water_ratio,
                          prep.liquid_retained_frac, prep.time_min, prep.temp_c])
        contains_rows.append([raw.recipe_id, resolved.fdc_id, canonical.value, prep_id])
        if raw_vec:
            facts.append(IngredientFacts(
                fdc_id=resolved.fdc_id, food_classes=tuple(classify_food(resolved.description)),
                mass_g=canonical.value, prep=prep, raw_per_100g=raw_vec))

    if not facts:
        stats.recipes_skipped += 1
        return

    cooked = compose_serving_vector(facts, transforms, raw.servings)
    variant_id = f"{raw.recipe_id}:variant:0:as_authored"
    writers["recipes"].writerow([raw.recipe_id, raw.title, raw.source_id, raw.license,
                                 raw.servings, min((i.parse_confidence for i in ingredients),
                                                   default=0.5)])
    for row in prep_rows:
        writers["preparations"].writerow(row)
    for row in contains_rows:
        writers["contains"].writerow(row)
    writers["variants"].writerow([variant_id, raw.recipe_id,
                                  min((n.confidence for n in cooked.values()), default=0.5)])
    for nutrient_id, nutrient in cooked.items():
        writers["has_nutrient"].writerow([variant_id, nutrient_id, nutrient.amount,
                                          units.get(nutrient_id, ""), nutrient.source,
                                          nutrient.confidence])
    stats.recipes_written += 1


def _export_stream(
    recipes: Iterable[RawRecipe], index: FoodIndex, transforms: list[TransformCoeff],
    units: dict[str, str], out: Path, log_every: int = 0,
) -> ExportStats:
    """Single-process export of a recipe stream to CSVs under `out`. The parallel path runs one of
    these per worker over a shard; the serial path (workers<=1) runs it over the whole corpus."""
    stats = ExportStats()
    with _Writers(out) as writers:
        for i, raw in enumerate(recipes, start=1):
            export_recipe(raw, index, transforms, units, writers.writers, stats)
            if log_every and i % log_every == 0:
                logger.info("bulk-export: %d recipes read, %d written", i, stats.recipes_written)
    return stats


# Set once in the parent before the worker pool forks, so each worker inherits the (read-only) index
# and coefficients through copy-on-write memory instead of pickling them per task.
_INDEX: FoodIndex | None = None
_TRANSFORMS: list[TransformCoeff] | None = None
_UNITS: dict[str, str] | None = None


def _export_shard(task: tuple[int, list[RawRecipe], str]) -> tuple[int, int, int]:
    """Worker entry: export one chunk of recipes to out/shard_<idx>/*.csv. Uses the fork-inherited
    globals so the ~8k-food index is not re-sent per task. Returns (written, skipped, unresolved)."""
    idx, recipes, out_dir = task
    assert _INDEX is not None and _TRANSFORMS is not None and _UNITS is not None
    stats = _export_stream(recipes, _INDEX, _TRANSFORMS, _UNITS, Path(out_dir) / f"shard_{idx}")
    return stats.recipes_written, stats.recipes_skipped, stats.ingredients_unresolved


def _chunked(items: Iterator[RawRecipe], size: int) -> Iterator[list[RawRecipe]]:
    while chunk := list(islice(items, size)):
        yield chunk


def _concatenate_shards(out: Path, shard_dirs: list[Path]) -> None:
    """Merge each shard's per-kind CSV into one final CSV under `out` (header once, then data)."""
    for name in _FILES:
        with (out / f"{name}.csv").open("w", encoding="utf-8", newline="") as dest:
            dest.write(",".join(_FILES[name]) + "\r\n")
            for shard in shard_dirs:
                src = shard / f"{name}.csv"
                if not src.is_file():
                    continue
                with src.open("r", encoding="utf-8") as handle:
                    next(handle, None)                       # skip the shard header
                    for line in handle:
                        dest.write(line)


def run_bulk_export(
    corpus_path: str, fdc_dir: str, out_dir: str, workers: int | None = None
) -> ExportStats:
    """Stream `corpus_path` through in-memory resolution + cooking and write CSVs under `out_dir`.

    With `workers > 1` the corpus is chunked and processed across a fork pool (each worker writes a
    shard, then shards are concatenated), because resolve+cook is CPU-bound and embarrassingly
    parallel. `workers` defaults to NUTRISCRAPE_MAX_PARALLEL or the CPU count.
    """
    from nutriscrape.common.config import default_config_dir

    logger.info("bulk-export: building in-memory FDC index from %s", fdc_dir)
    index = FoodIndex.from_fdc_csv(fdc_dir)
    logger.info("bulk-export: indexed %d FDC foods", len(index))
    transforms = load_transforms(default_config_dir())
    units = _nutrient_units()
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    n_workers = workers if workers is not None else _default_workers()
    if n_workers <= 1:
        stats = _export_stream(RecipeNlgAdapter(corpus_path).recipes(), index, transforms, units,
                               out, log_every=100_000)
        logger.info("bulk-export: done (serial). %d written, %d skipped", stats.recipes_written,
                    stats.recipes_skipped)
        return stats

    global _INDEX, _TRANSFORMS, _UNITS
    _INDEX, _TRANSFORMS, _UNITS = index, transforms, units
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
                logger.info("bulk-export: %d shards done, %d recipes written",
                            shard_count, total.recipes_written)
    _concatenate_shards(out, [out / f"shard_{i}" for i in range(shard_count)])
    logger.info("bulk-export: done (%d workers). %d written, %d skipped; CSVs in %s",
                n_workers, total.recipes_written, total.recipes_skipped, out)
    return total


_CHUNK_SIZE = 2_000


def _default_workers() -> int:
    env = os.environ.get("NUTRISCRAPE_MAX_PARALLEL")
    if env:
        try:
            return max(1, int(env))
        except ValueError:
            pass
    return max(1, (os.cpu_count() or 2))
