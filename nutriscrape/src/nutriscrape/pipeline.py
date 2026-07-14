"""Batch stage orchestration. Composes the real modules under `common/`, `graph/`, `extraction/`,
`resolution/`, `nutrition/`, `clustering/`, and `knowledge/` into the stages `__main__.py` dispatches.
This module adds no clinical logic, no Cypher, and no nutrient computation of its own: every
number and every write goes through the modules that already own it (nutrition/transform.py for
cooked nutrients, graph/writers.py for Cypher). See ../../docs/PDD.md Section 10 (phased plan) and
../../CLAUDE.md invariants.

All five stages are functional today given a configured Neo4j: `run_schema`, `run_knowledge`,
`run_ingest`, `run_cluster`, and `run_materialize` (over the bundled sample corpus). What remains is
data scale, not code: pointing acquisition at the full RecipeNLG export or a large URL list.

- `run_ingest` is wired end to end: acquisition (`_acquire` selects `acquisition/adapters/
  datasets.py` for a `.csv` dataset dump or `acquisition/adapters/structured.py` for a `.txt`/`.urls`
  list of schema.org recipe URLs) -> deterministic model-free parse (`acquisition/parse.py`) -> FDC
  resolution -> the FDC-number -> contract `nutrient_id` mapping (`resolution/nutrient_map.py`) ->
  the four-channel transform (`nutrition/compose.py`) -> cooked per-serving HAS_NUTRIENT vectors on
  the as-authored variant. It runs over the bundled sample by default (NUTRISCRAPE_CORPUS overrides).
  Food resolution and raw amounts use the live USDA FDC API (needs FDC_API_KEY); schema.org scraping
  needs recipe-scrapers and network. The only remaining data gap is obtaining the full RecipeNLG
  export (a multi-GB download, not code).
- `run_cluster` is wired: `graph/readers.py` reads already-ingested recipes back into clustering
  `RecipeInput`s (resolved FDC foods, masses, primary method, title), which fingerprint -> block ->
  score -> resolve, and `_cluster_and_persist` writes :Dish nodes and HAS_VERSION links. After
  `ingest` + `cluster`, the full Dish -> Recipe -> RecipeVariant -> HAS_NUTRIENT path NECTAR queries
  exists. Granularity favors the finer split (SDD Section 5).
- `run_materialize` is wired: `graph/readers.py` reads each ingested recipe with its persisted
  as-authored `:Preparation` and food `HAS_NUTRIENT_RAW` vectors, and `run_ingest` now persists both.
  For each recipe it generates a bounded, culinarily-valid set of alternative-method variants
  (config/method_coverage.yaml) and writes each variant's cooked per-serving HAS_NUTRIENT vector via
  the four-channel transform. So a baked-potato variant retains potassium a boiled-and-drained one
  leaches away, and NECTAR can rank versions within a dish accordingly. `run_materialize` then
  materializes per-dish nutrient distribution statistics on each `:Dish` across its versions
  (contract Section 5) via `graph/readers.read_dish_variant_nutrients` and
  `graph/writers.write_dish_nutrient_stats`.
- The only genuinely-remaining item is data scale: obtaining the full RecipeNLG export or a large
  curated URL list to run acquisition over, rather than the bundled 7-recipe sample.

None of these are stubbed with fake data. Each function below either does the real, complete work
it can do today, or returns after logging why there is nothing to do, per its docstring.
"""
from __future__ import annotations

import logging
import math
import os
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from nectar_contract import names

from nutriscrape.clustering.fingerprint import RecipeInput, fingerprint as make_fingerprint
from nutriscrape.clustering.resolve import Judge, cluster as cluster_fingerprints
from nutriscrape.acquisition.adapters.base import RawRecipe
from nutriscrape.acquisition.adapters.datasets import RecipeNlgAdapter
from nutriscrape.acquisition.adapters.structured import SchemaOrgAdapter
from nutriscrape.acquisition.parse import basic_preparation, parse_ingredient_basic
from nutriscrape.common import confidence
from nutriscrape.common.config import default_config_dir, load_config
from nutriscrape.common.provenance import make_provenance
from nutriscrape.common.units import UnitError
from nutriscrape.extraction.ingredients import ParsedIngredient
from nutriscrape.extraction.preparation import ParsedPreparation
from nutriscrape.graph.client import GraphClient
from nutriscrape.graph.readers import (
    MaterializeIngredient,
    MaterializeRecipe,
    has_foods,
    read_dish_variant_nutrients,
    read_raw_vector,
    read_recipe_inputs,
    read_recipes_for_materialize,
    search_foods,
)
from nutriscrape.graph.schema import apply_schema
from nutriscrape.graph.writers import (
    link_acts_on,
    link_dish_recipe,
    link_evidenced_by,
    link_imposes,
    link_recipe_variant,
    merge_condition,
    merge_dietary_rule,
    merge_dish,
    merge_food,
    merge_guideline,
    merge_medication,
    merge_nutrient,
    merge_preparation,
    merge_recipe,
    merge_recipe_variant,
    write_contains,
    write_dish_nutrient_stats,
    write_has_nutrient,
    write_has_nutrient_raw,
    write_interacts_with,
    write_transform,
)
from nutriscrape.knowledge.loaders import (
    DietaryRule,
    TransformCoeff as KnowledgeTransformCoeff,
    load_guidelines,
    load_interactions,
    load_rules,
    load_transforms,
)
from nutriscrape.nutrition.compose import IngredientFacts, compose_serving_vector
from nutriscrape.nutrition.distribution import distribution
from nutriscrape.nutrition.normalize import to_canonical
from nutriscrape.nutrition.transform import Preparation
from nutriscrape.resolution.fdc_bulk import iter_bulk_foods
from nutriscrape.resolution.fdc_client import FdcClient, FdcConfigError, FdcRequestError
from nutriscrape.resolution.matcher import best_match, resolve_food
from nutriscrape.resolution.nutrient_map import (
    classify_food,
    load_contract_units,
    load_fdc_nutrient_map,
    raw_vector_from_fdc,
)

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------------------- schema


def run_schema() -> None:
    """Apply the contract DDL (contract/schema/schema.cypher) idempotently. Fully functional
    against a configured Neo4j (NEO4J_URI / NEO4J_USER / NEO4J_PASSWORD in the environment)."""
    logger.info("schema: connecting to Neo4j to apply the contract DDL")
    with GraphClient.from_env() as client:
        apply_schema(client)
    logger.info("schema: contract DDL applied (idempotent)")


# ------------------------------------------------------------------------------------- knowledge


def _persist_rule(client: GraphClient, rule: DietaryRule) -> None:
    """Persist one loaded `DietaryRule` and its factor/target/evidence links.

    The knowledge loaders (`knowledge/loaders.py`) do not carry a separate `disease_id` field on
    `DietaryRule`; `_rule_from_constraint` builds `rule_id` as `f"{disease_id}:{nutrient}:
    {direction}"`, so the leading segment before the first colon is the condition this rule
    belongs to. `acts_on` is the config's `nutrient` key (see `_rule_from_constraint`), so the
    ACTS_ON target is always linked as a `:Nutrient` here; a rule acting on a `:Food`,
    `:FoodAttribute`, or `:Compound` instead is outside what the curated condition-rule YAML
    shape (`config/conditions/*.yaml`) expresses today.
    """
    merge_dietary_rule(client, rule=rule)
    condition_id = rule.rule_id.split(":", 1)[0]
    merge_condition(client, condition_id=condition_id)
    link_imposes(
        client, factor_label=names.CONDITION, factor_id=condition_id, rule_id=rule.rule_id
    )
    link_acts_on(
        client, rule_id=rule.rule_id, target_id=rule.acts_on, target_label=names.NUTRIENT
    )
    if rule.guideline_id is not None:
        link_evidenced_by(client, rule_id=rule.rule_id, guideline_id=rule.guideline_id)


def _conditions_dir() -> Path | None:
    """Locate the disease-rule condition YAMLs (`ckd.yaml`, `htn.yaml`, ...). These are authored in
    `nectar/config/conditions` (the clinical KB the root map assigns to NECTAR); NutriScrape is the
    writer that persists them to the graph as `:Condition-[:IMPOSES]->:DietaryRule` so NECTAR reads
    them back via `constraints_for_condition`. Resolution order: the `NUTRISCRAPE_CONDITIONS` env
    var; then `conditions/` staged next to the nutriscrape config (the container image copies the
    shared condition rules there); then the monorepo sibling `nectar/config/conditions`. Returns
    None when none is found, so `run_knowledge` logs it and continues rather than failing the run."""
    override = os.environ.get("NUTRISCRAPE_CONDITIONS")
    if override:
        return Path(override)
    staged = default_config_dir() / "conditions"
    if staged.is_dir():
        return staged
    sibling = Path(__file__).resolve().parents[3] / "nectar" / "config" / "conditions"
    if sibling.is_dir():
        return sibling
    return None


def run_knowledge() -> None:
    """Load rules/interactions/transforms/guidelines from config/ into the typed models that
    mirror the contract's clinical knowledge base (DATA_CONTRACT.md Sections 2.2, 3.3, 3.4), and
    persist all of it to Neo4j via `graph/writers.py`'s clinical KB writers. Fully functional
    against a configured Neo4j (NEO4J_URI / NEO4J_USER / NEO4J_PASSWORD in the environment).

    Guidelines are written first so a rule's `EVIDENCED_BY` link has a `:Guideline` node to match;
    interactions merge their `:Medication` endpoint before writing `INTERACTS_WITH`; transforms
    merge their `:Method` endpoint internally (`write_transform`). Every writer here matches
    (never creates) any endpoint it does not itself merge, so a knowledge entry referencing a
    nutrient/food/attribute/compound that has not been written yet (for example, before
    `run_ingest` populates `:Nutrient`/`:Food`) no-ops that one link rather than failing the run;
    re-running this stage after those nodes exist completes the link (idempotent per SDD Section 9).
    """
    config_dir = default_config_dir()
    conditions_dir = _conditions_dir()
    logger.info(
        "knowledge: loading interactions/transforms/guidelines from %s; condition rules from %s",
        config_dir,
        conditions_dir if conditions_dir is not None else "(no conditions dir found)",
    )

    rules = load_rules(conditions_dir) if conditions_dir is not None else []
    interactions = load_interactions(config_dir)
    transforms = load_transforms(config_dir)
    guidelines = load_guidelines(config_dir)

    logger.info(
        "knowledge: loaded %d rule(s), %d interaction(s), %d transform coefficient(s), "
        "%d guideline(s)",
        len(rules),
        len(interactions),
        len(transforms),
        len(guidelines),
    )

    with GraphClient.from_env() as client:
        # Merge the canonical nutrient vocabulary first. A rule's ACTS_ON edge matches (never
        # creates) its target :Nutrient, so without this a `knowledge` run before `fdc-import` /
        # `ingest` (the order run-all uses) would silently drop every rule->nutrient link. Merging
        # the small config vocabulary here makes ACTS_ON complete in a single pass, regardless of
        # stage order, and is idempotent with the same merge in `fdc-import` / `ingest`.
        for nutrient_id, (name, unit) in _load_nutrient_vocab().items():
            merge_nutrient(client, nutrient_id=nutrient_id, name=name, unit=unit)
        for guideline in guidelines:
            merge_guideline(client, guideline=guideline)
        for rule in rules:
            _persist_rule(client, rule)
        for interaction in interactions:
            merge_medication(client, medication_id=interaction.medication)
            write_interacts_with(client, interaction=interaction)
        for coeff in transforms:
            write_transform(client, coeff=coeff)

    logger.info(
        "knowledge: persisted %d rule(s), %d interaction(s), %d transform coefficient(s), "
        "%d guideline(s) to Neo4j",
        len(rules),
        len(interactions),
        len(transforms),
        len(guidelines),
    )


# ---------------------------------------------------------------------------------------- ingest


# ------------------------------------------------------------------------------ fdc bulk import


def _import_fdc_bulk(csv_dir: str, client: GraphClient,
                     nutrient_vocab: dict[str, tuple[str, str]] | None = None) -> int:
    """Load the FDC CSV bulk export at `csv_dir` into the graph: one `:Food` per food plus its raw
    per-100g `HAS_NUTRIENT_RAW` vector, so resolution and cooked nutrition need no per-food FDC API
    call. Reuses the same writers `run_ingest` uses. Split out so it is testable with a fake client."""
    vocab = nutrient_vocab if nutrient_vocab is not None else _load_nutrient_vocab()
    # :Nutrient nodes must exist before HAS_NUTRIENT_RAW (which matches them); write the small
    # contract nutrient vocabulary once up front.
    for nutrient_id, (name, unit) in vocab.items():
        merge_nutrient(client, nutrient_id=nutrient_id, name=name, unit=unit)
    provenance = make_provenance(source="fdc:bulk", confidence=0.95,
                                 computed_by="resolution.fdc_bulk")
    written = 0
    for food in iter_bulk_foods(csv_dir):
        merge_food(client, fdc_id=food.fdc_id, description=food.description,
                   data_type=food.data_type, source_tier="fdc")
        for nutrient_id, amount_per_100g in food.raw_per_100g.items():
            write_has_nutrient_raw(client, fdc_id=food.fdc_id, nutrient_id=nutrient_id,
                                   amount_per_100g=amount_per_100g, provenance=provenance)
        written += 1
        if written % 5000 == 0:
            logger.info("fdc-import: %d foods written so far", written)
    logger.info("fdc-import: wrote %d food(s) with raw nutrient vectors from %s", written, csv_dir)
    return written


def run_fdc_import() -> None:
    """Import the USDA FDC CSV bulk export into the graph (`:Food` + `HAS_NUTRIENT_RAW`), so food
    resolution and raw amounts come from the local graph instead of the rate-limited FDC API. Set
    FDC_BULK_DIR to the extracted export directory (food.csv, nutrient.csv, food_nutrient.csv from
    https://fdc.nal.usda.gov/download-datasets). Fully functional against a configured Neo4j; no-ops
    with a log line when FDC_BULK_DIR is unset, so run-all is safe without a bulk export."""
    csv_dir = os.environ.get("FDC_BULK_DIR")
    if not csv_dir:
        logger.warning(
            "fdc-import: FDC_BULK_DIR is not set. Download the FDC CSV bulk export from "
            "https://fdc.nal.usda.gov/download-datasets, extract it, and set FDC_BULK_DIR to the "
            "directory holding food.csv / nutrient.csv / food_nutrient.csv. Nothing imported."
        )
        return
    with GraphClient.from_env() as client:
        _import_fdc_bulk(csv_dir, client)


# ---------------------------------------------------------------------------------------- ingest


@dataclass(frozen=True)
class ResolvedFood:
    """The identity of a resolved FDC food (resolution/matcher over resolution/fdc_client)."""

    fdc_id: str
    description: str
    data_type: str


@dataclass
class IngestDeps:
    """Injected collaborators for `_ingest_recipe`, so the extraction -> resolution -> nutrition
    chain is unit-testable offline with fakes. `resolve` maps a food string to a resolved FDC food;
    `raw_vector_for` maps an fdc_id to its raw per-100g nutrient vector. Both have an FDC-API
    implementation (`_api_ingest_deps`) and a local-graph implementation that reads what the
    `fdc-import` stage wrote (`_local_ingest_deps`). No collaborator produces a nutrient number
    outside FDC's own measured amounts and the four-channel transform inside compose."""

    resolve: Callable[[str], ResolvedFood | None]
    raw_vector_for: Callable[[str], dict[str, float]]
    transforms: Sequence[KnowledgeTransformCoeff]
    nutrient_vocab: dict[str, tuple[str, str]]
    parse_ingredient: Callable[[str], ParsedIngredient] = parse_ingredient_basic
    build_preparations: Callable[
        [Sequence[str], Sequence[str]], list[ParsedPreparation]
    ] = basic_preparation
    classify: Callable[[str], list[str]] = classify_food
    # Persist HAS_NUTRIENT_RAW during ingest (the API path). False on the local path, where the bulk
    # import already wrote the food's raw vector, so ingest does not rewrite it per recipe.
    persist_raw: bool = True


def _sample_corpus_path() -> str:
    """The bundled sample corpus, overridable via NUTRISCRAPE_CORPUS for a real RecipeNLG export."""
    return os.environ.get("NUTRISCRAPE_CORPUS") or str(
        default_config_dir() / "samples" / "recipes_sample.csv"
    )


def _acquire(corpus_path: str) -> list[RawRecipe]:
    """Acquire raw recipes from the corpus path, choosing the adapter by extension: a `.csv` is a
    RecipeNLG-style dataset dump (`RecipeNlgAdapter`); a `.txt`/`.urls` file is a newline list of
    recipe URLs scraped from their published schema.org data (`SchemaOrgAdapter`, needs
    recipe-scrapers and network). Lines starting with `#` in a URL file are treated as comments."""
    if corpus_path.endswith((".txt", ".urls")):
        lines = Path(corpus_path).read_text(encoding="utf-8").splitlines()
        urls = [
            stripped
            for line in lines
            for stripped in (line.strip(),)
            if stripped and not stripped.startswith("#")
        ]
        return list(SchemaOrgAdapter(urls).recipes())
    return list(RecipeNlgAdapter(corpus_path).recipes())


def _load_nutrient_vocab() -> dict[str, tuple[str, str]]:
    """contract nutrient_id -> (display name, canonical unit), from config/nutrients.yaml."""
    data = load_config("nutrients")
    vocab: dict[str, tuple[str, str]] = {}
    for entry in data.get("nutrients", []) or []:
        vocab[str(entry["id"])] = (str(entry.get("name", "")), str(entry.get("unit", "")))
    return vocab


def _to_transform_prep(prep: ParsedPreparation | None) -> Preparation:
    """The as-eaten Preparation the four-channel transform consumes. An unprepared ingredient is a
    raw passthrough (no leaching, full retention)."""
    if prep is None:
        return Preparation(method="raw", liquid_retained_frac=1.0)
    return Preparation(
        method=prep.method,
        cut_class=prep.cut_class or "whole",
        water_ratio=prep.water_ratio,
        liquid_retained_frac=prep.liquid_retained_frac,
        time_min=prep.time_min,
        temp_c=prep.temp_c,
    )


def _ingest_recipe(raw: RawRecipe, deps: IngestDeps, client: GraphClient) -> None:
    """Extraction -> resolution -> canonical normalization -> four-channel cooked nutrition for one
    recipe. Writes :Recipe, the resolved :Food nodes and CONTAINS masses, the as-authored
    :RecipeVariant, and its cooked per-serving HAS_NUTRIENT vector (nutrition/compose.py over FDC raw
    amounts). Every nutrient value carries the contract Section 1.1 provenance; nothing here is a
    literal or a model output."""
    ingredients = [deps.parse_ingredient(line) for line in raw.ingredient_lines]
    ingredient_refs = [ingredient.food for ingredient in ingredients]
    preparations = deps.build_preparations(raw.preparation_steps, ingredient_refs)
    prep_by_ref = {prep.applies_to[0]: prep for prep in preparations if prep.applies_to}

    recipe_confidence = confidence.propagate(
        ingredient.parse_confidence for ingredient in ingredients
    )
    merge_recipe(
        client,
        recipe_id=raw.recipe_id,
        title=raw.title,
        source_id=raw.source_id,
        license=raw.license,
        servings=raw.servings,
        confidence=recipe_confidence,
    )

    facts: list[IngredientFacts] = []
    for ingredient in ingredients:
        resolved = deps.resolve(ingredient.food)
        if resolved is None:
            logger.warning(
                "ingest: recipe %s: no confident FDC match for %r; skipping this ingredient",
                raw.recipe_id,
                ingredient.food,
            )
            continue
        merge_food(
            client,
            fdc_id=resolved.fdc_id,
            description=resolved.description,
            data_type=resolved.data_type,
            source_tier="fdc",
        )
        try:
            canonical = to_canonical(ingredient.quantity or 0.0, ingredient.unit or "g")
        except UnitError:
            logger.warning(
                "ingest: recipe %s: unrecognized unit %r for %r; skipping this ingredient",
                raw.recipe_id,
                ingredient.unit,
                ingredient.food,
            )
            continue
        prep = _to_transform_prep(prep_by_ref.get(ingredient.food))
        prep_id = f"{raw.recipe_id}:{resolved.fdc_id}"
        merge_preparation(
            client,
            prep_id=prep_id,
            method=prep.method,
            cut_class=prep.cut_class,
            water_ratio=prep.water_ratio,
            liquid_retained_frac=prep.liquid_retained_frac,
            time_min=prep.time_min,
            temp_c=prep.temp_c,
        )
        write_contains(
            client,
            recipe_id=raw.recipe_id,
            fdc_id=resolved.fdc_id,
            raw_mass_g=canonical.value,
            prep_id=prep_id,
        )
        try:
            raw_per_100g = deps.raw_vector_for(resolved.fdc_id)
        except FdcRequestError:
            logger.warning(
                "ingest: recipe %s: FDC lookup failed for %s; no nutrient vector this food",
                raw.recipe_id,
                resolved.fdc_id,
            )
            continue
        if not raw_per_100g:
            continue
        if deps.persist_raw:
            # Persist the food's intrinsic raw per-100g vector (HAS_NUTRIENT_RAW) so run_materialize
            # can re-cook it with no FDC round trip. Skipped on the local path (fdc-import wrote it).
            raw_provenance = make_provenance(
                source=f"fdc:{resolved.fdc_id}", confidence=0.9,
                computed_by="resolution.nutrient_map",
            )
            for nutrient_id, amount_per_100g in raw_per_100g.items():
                name, unit = deps.nutrient_vocab.get(nutrient_id, (nutrient_id, ""))
                merge_nutrient(client, nutrient_id=nutrient_id, name=name, unit=unit)
                write_has_nutrient_raw(
                    client,
                    fdc_id=resolved.fdc_id,
                    nutrient_id=nutrient_id,
                    amount_per_100g=amount_per_100g,
                    provenance=raw_provenance,
                )
        facts.append(
            IngredientFacts(
                fdc_id=resolved.fdc_id,
                food_classes=tuple(deps.classify(resolved.description)),
                mass_g=canonical.value,
                prep=prep,
                raw_per_100g=raw_per_100g,
            )
        )

    if not facts:
        logger.warning(
            "ingest: recipe %s: no resolved ingredient carried a nutrient vector; wrote composition "
            "only",
            raw.recipe_id,
        )
        return

    cooked = compose_serving_vector(facts, deps.transforms, raw.servings)
    variant_id = f"{raw.recipe_id}:variant:0:as_authored"
    variant_confidence = confidence.propagate(nutrient.confidence for nutrient in cooked.values())
    merge_recipe_variant(
        client, variant_id=variant_id, is_as_authored=True, confidence=variant_confidence
    )
    link_recipe_variant(client, recipe_id=raw.recipe_id, variant_id=variant_id)
    for nutrient_id, nutrient in cooked.items():
        name, unit = deps.nutrient_vocab.get(nutrient_id, (nutrient_id, ""))
        merge_nutrient(client, nutrient_id=nutrient_id, name=name, unit=unit)
        write_has_nutrient(
            client,
            variant_id=variant_id,
            nutrient_id=nutrient_id,
            amount_per_serving=nutrient.amount,
            unit=unit,
            provenance=make_provenance(
                source=nutrient.source,
                confidence=nutrient.confidence,
                computed_by="nutrition.compose",
            ),
        )

    logger.info(
        "ingest: wrote recipe %s: %d ingredient(s) resolved, %d cooked nutrient(s) on %s",
        raw.recipe_id,
        len(facts),
        len(cooked),
        variant_id,
    )


def _real_resolver(fdc_client: FdcClient) -> Callable[[str], ResolvedFood | None]:
    def resolve(food_str: str) -> ResolvedFood | None:
        try:
            match = resolve_food(food_str, fdc_client)
        except FdcRequestError:
            return None
        if match is None:
            return None
        candidate = match.candidate
        return ResolvedFood(
            fdc_id=str(candidate.fdc_id),
            description=candidate.description,
            data_type=candidate.data_type,
        )

    return resolve


def _api_ingest_deps(fdc_client: FdcClient) -> IngestDeps:
    """Deps that resolve foods and read raw vectors from the live USDA FDC API (needs FDC_API_KEY).
    The nutrient/unit maps are loaded once and reused for every food."""
    nutrient_map = load_fdc_nutrient_map()
    contract_units = load_contract_units()

    def raw_vector_for(fdc_id: str) -> dict[str, float]:
        return raw_vector_from_fdc(fdc_client.food(int(fdc_id)),
                                   nutrient_map=nutrient_map, contract_units=contract_units)

    return IngestDeps(
        resolve=_real_resolver(fdc_client),
        raw_vector_for=raw_vector_for,
        transforms=load_transforms(default_config_dir()),
        nutrient_vocab=_load_nutrient_vocab(),
        persist_raw=True,
    )


def _local_resolver(client: GraphClient) -> Callable[[str], ResolvedFood | None]:
    """Resolve a food string against the local :Food graph (bulk-imported) via the full-text index,
    ranked by the same matcher the API path uses. No FDC API call."""
    def resolve(food_str: str) -> ResolvedFood | None:
        best = best_match(food_str, search_foods(client, food_str))
        if best is None:
            return None
        candidate = best.candidate
        return ResolvedFood(fdc_id=str(candidate.fdc_id), description=candidate.description,
                            data_type=candidate.data_type)

    return resolve


def _local_ingest_deps(client: GraphClient) -> IngestDeps:
    """Deps that resolve foods and read raw vectors from the local graph (populated by fdc-import),
    so ingest needs no FDC API call or key."""
    return IngestDeps(
        resolve=_local_resolver(client),
        raw_vector_for=lambda fdc_id: read_raw_vector(client, fdc_id),
        transforms=load_transforms(default_config_dir()),
        nutrient_vocab=_load_nutrient_vocab(),
        persist_raw=False,
    )


def run_ingest() -> None:
    """Acquisition -> extraction -> resolution -> four-channel cooked nutrition over the recipe
    corpus. `_acquire` selects the adapter by corpus extension (a `.csv` RecipeNLG dataset dump, or a
    `.txt`/`.urls` list of schema.org recipe URLs). Runs over the bundled sample CSV by default
    (NUTRISCRAPE_CORPUS overrides) with the deterministic parsers, so it works offline without a
    running LLM.

    Food resolution auto-selects its source: if the graph already holds `:Food` nodes (from the
    fdc-import stage), it resolves against the local graph with no FDC API call; otherwise it uses
    the live USDA FDC API (needs FDC_API_KEY). Schema.org scraping additionally needs recipe-scrapers
    and network.
    """
    corpus = _sample_corpus_path()
    logger.info("ingest: reading recipe corpus from %s", corpus)
    raw_recipes = _acquire(corpus)
    if not raw_recipes:
        logger.warning("ingest: no recipes found in %s; nothing to ingest", corpus)
        return

    with GraphClient.from_env() as client:
        if has_foods(client):
            logger.info("ingest: resolving foods against the local :Food graph (from fdc-import)")
            deps = _local_ingest_deps(client)
        else:
            try:
                fdc_client = FdcClient()
            except FdcConfigError:
                logger.warning(
                    "ingest: no local :Food graph (run fdc-import) and FDC_API_KEY is not set, so "
                    "foods cannot be resolved. Import the FDC bulk export (make fdc-import with "
                    "FDC_BULK_DIR set) or set FDC_API_KEY. Read %d recipe(s), wrote nothing.",
                    len(raw_recipes),
                )
                return
            logger.info("ingest: resolving foods against the live USDA FDC API")
            deps = _api_ingest_deps(fdc_client)

        for raw in raw_recipes:
            _ingest_recipe(raw, deps, client)
    logger.info("ingest: processed %d recipe(s) from %s", len(raw_recipes), corpus)


# ------------------------------------------------------- parallel ingest building blocks (orchestration)
# These let an orchestrator (orchestration/flows.py, Prefect) fan ingest out over batches of recipes
# in parallel. `run_ingest` above is the single-process path (`make ingest`); the pieces here are the
# same work, split so independent recipes can be ingested concurrently against a shared Neo4j.


def acquire_recipes() -> list[RawRecipe]:
    """Read the configured corpus (NUTRISCRAPE_CORPUS or the bundled sample) into RawRecipes."""
    return _acquire(_sample_corpus_path())


def local_resolution_available() -> bool:
    """Whether the graph already holds :Food nodes (from fdc-import), so ingest can resolve locally
    with no FDC API call. Opens a short-lived read connection."""
    with GraphClient.from_env() as client:
        return has_foods(client)


def split_into_batches(items: Sequence[RawRecipe], batch_count: int) -> list[list[RawRecipe]]:
    """Split `items` into at most `batch_count` roughly-equal batches (the unit of parallelism)."""
    count = max(1, batch_count)
    if not items:
        return []
    size = math.ceil(len(items) / count)
    return [list(items[start:start + size]) for start in range(0, len(items), size)]


def ingest_batch(recipes: Sequence[RawRecipe], use_local: bool) -> int:
    """Ingest one batch of recipes against a freshly-opened GraphClient (one per batch, so parallel
    batches do not share a session). `use_local` selects local-graph vs FDC-API resolution. The
    writers' MERGEs are idempotent, so re-running a failed batch is safe. Returns the recipe count."""
    with GraphClient.from_env() as client:
        deps = _local_ingest_deps(client) if use_local else _api_ingest_deps(FdcClient())
        for raw in recipes:
            _ingest_recipe(raw, deps, client)
    return len(recipes)


# --------------------------------------------------------------------------------------- cluster


def _cluster_and_persist(
    recipe_inputs: Sequence[RecipeInput], client: GraphClient, judge: Judge | None = None
) -> int:
    """Fingerprint -> block -> score -> cluster the given recipes and persist dish membership.

    Uses `clustering.resolve.cluster` (union-find over within-block scores, an LLM `judge` used
    only at the near-threshold boundary per SDD Section 5) and the existing `merge_dish` /
    `link_dish_recipe` writers. Dish-level nutrient-distribution statistics (contract Section 5)
    are not written here: TODO(PDD Phase 3 / 5, contract Section 5) -- `merge_dish` only accepts
    `canonical_name` and `cluster_confidence`; there is no writer yet for the per-dish nutrient
    distribution the contract requires materialized on `:Dish`.
    """
    fingerprints = [make_fingerprint(recipe) for recipe in recipe_inputs]
    title_by_id = {recipe.recipe_id: recipe.title for recipe in recipe_inputs}
    clusters = cluster_fingerprints(fingerprints, judge=judge)

    for one_cluster in clusters:
        canonical_name = title_by_id.get(one_cluster.members[0], one_cluster.members[0])
        cluster_confidence = min(one_cluster.membership_confidence.values(), default=1.0)
        merge_dish(
            client,
            dish_id=one_cluster.dish_id,
            canonical_name=canonical_name,
            cluster_confidence=cluster_confidence,
        )
        for recipe_id in one_cluster.members:
            link_dish_recipe(client, dish_id=one_cluster.dish_id, recipe_id=recipe_id)

    return len(clusters)


def _run_cluster_with_client(client: GraphClient, judge: Judge | None = None) -> int:
    """Read already-ingested recipes, cluster them, and persist dish membership. Split from
    `run_cluster` so the read -> fingerprint -> block -> score -> resolve -> persist path is testable
    with a fake GraphClient (no live Neo4j)."""
    recipe_inputs = read_recipe_inputs(client)
    if not recipe_inputs:
        logger.warning(
            "cluster: no ingested recipes with resolved foods found; run `ingest` first. "
            "Nothing to cluster this run."
        )
        return 0
    n_clusters = _cluster_and_persist(recipe_inputs, client, judge=judge)
    logger.info(
        "cluster: wrote %d dish cluster(s) from %d recipe(s)", n_clusters, len(recipe_inputs)
    )
    return n_clusters


def run_cluster() -> None:
    """Dish clustering over already-ingested recipes: read them back from the graph, fingerprint,
    block, score, resolve (an LLM judge is used only at the near-threshold boundary per SDD
    Section 5), and persist :Dish membership via HAS_VERSION. Functional against a graph that
    `run_ingest` has populated. Granularity favors the finer split, so a clinically distinct version
    stays its own dish rather than being averaged into a parent."""
    logger.info("cluster: reading ingested recipes to fingerprint")
    with GraphClient.from_env() as client:
        _run_cluster_with_client(client)


# ----------------------------------------------------------------------------------- materialize


MAX_ALT_VARIANTS = 3  # bounded, culinarily-sane eager set per recipe (PDD Section 6)


def _load_method_coverage() -> dict[str, list[str]]:
    """food_class -> culinarily-valid cooking methods, from config/method_coverage.yaml."""
    data = load_config("method_coverage").get("method_coverage", {}) or {}
    return {str(key): [str(method) for method in (value or [])] for key, value in data.items()}


def _alternative_methods(recipe: MaterializeRecipe, coverage: dict[str, list[str]]) -> list[str]:
    """The bounded set of alternative cooking methods for a recipe: the union of its food classes'
    covered methods, minus the methods the as-authored preparation already uses."""
    classes: set[str] = set()
    authored: set[str] = set()
    for ingredient in recipe.ingredients:
        classes.update(classify_food(ingredient.description))
        authored.add(ingredient.prep.method)
    candidates = {method for food_class in classes for method in coverage.get(food_class, [])}
    return sorted(candidates - authored)[:MAX_ALT_VARIANTS]


def _facts_under_method(ingredient: MaterializeIngredient, method: str) -> IngredientFacts:
    """Re-cook one ingredient under an alternative method, keeping its cut and liquid handling."""
    prep = Preparation(
        method=method,
        cut_class=ingredient.prep.cut_class,
        water_ratio=ingredient.prep.water_ratio,
        liquid_retained_frac=ingredient.prep.liquid_retained_frac,
        time_min=ingredient.prep.time_min,
        temp_c=ingredient.prep.temp_c,
    )
    return IngredientFacts(
        fdc_id=ingredient.fdc_id,
        food_classes=tuple(classify_food(ingredient.description)),
        mass_g=ingredient.mass_g,
        prep=prep,
        raw_per_100g=ingredient.raw_per_100g,
    )


def _materialize_variants_for_recipe(
    recipe: MaterializeRecipe,
    transforms: Sequence[KnowledgeTransformCoeff],
    coverage: dict[str, list[str]],
    nutrient_vocab: dict[str, tuple[str, str]],
    client: GraphClient,
) -> int:
    """Generate the bounded alternative-preparation variants for one already-ingested recipe, each
    with its cooked per-serving HAS_NUTRIENT vector (nutrition/compose.py over the persisted raw
    vectors). The as-authored variant is written by `run_ingest`; these are the alternatives
    (is_as_authored=False)."""
    written = 0
    for method in _alternative_methods(recipe, coverage):
        facts = [_facts_under_method(ingredient, method) for ingredient in recipe.ingredients]
        cooked = compose_serving_vector(facts, transforms, recipe.servings)
        if not cooked:
            continue
        variant_id = f"{recipe.recipe_id}:variant:{method}"
        variant_confidence = confidence.propagate(
            nutrient.confidence for nutrient in cooked.values()
        )
        merge_recipe_variant(
            client, variant_id=variant_id, is_as_authored=False, confidence=variant_confidence
        )
        link_recipe_variant(client, recipe_id=recipe.recipe_id, variant_id=variant_id)
        for nutrient_id, nutrient in cooked.items():
            name, unit = nutrient_vocab.get(nutrient_id, (nutrient_id, ""))
            merge_nutrient(client, nutrient_id=nutrient_id, name=name, unit=unit)
            write_has_nutrient(
                client,
                variant_id=variant_id,
                nutrient_id=nutrient_id,
                amount_per_serving=nutrient.amount,
                unit=unit,
                provenance=make_provenance(
                    source=nutrient.source,
                    confidence=nutrient.confidence,
                    computed_by="nutrition.compose",
                ),
            )
        written += 1
    return written


def _run_materialize_with_client(client: GraphClient) -> int:
    """Read ingested recipes and write their alternative-preparation variants. Split from
    `run_materialize` so the read -> generate -> compose -> persist path is testable with a fake
    GraphClient (no live Neo4j)."""
    recipes = read_recipes_for_materialize(client)
    if not recipes:
        logger.warning(
            "materialize: no ingested recipes with raw nutrient vectors found; run `ingest` first. "
            "Nothing to materialize this run."
        )
        return 0
    transforms = load_transforms(default_config_dir())
    coverage = _load_method_coverage()
    nutrient_vocab = _load_nutrient_vocab()
    total = sum(
        _materialize_variants_for_recipe(recipe, transforms, coverage, nutrient_vocab, client)
        for recipe in recipes
    )
    logger.info(
        "materialize: wrote %d alternative variant(s) across %d recipe(s)", total, len(recipes)
    )
    return total


def _run_dish_stats_with_client(client: GraphClient) -> int:
    """Materialize per-dish nutrient distribution statistics (contract Section 5): for each clustered
    dish, summarize every nutrient across all of its variants and persist the distribution on the
    `:Dish`. Needs `cluster` (dishes) and `ingest`/`materialize` (variants) to have run. Split out so
    the read -> summarize -> persist path is testable with a fake GraphClient."""
    by_dish = read_dish_variant_nutrients(client)
    if not by_dish:
        logger.warning(
            "materialize: no dish variants with cooked nutrients found; run `cluster` (and "
            "`ingest`) first. No dish statistics written this run."
        )
        return 0
    for dish_id, nutrients in by_dish.items():
        stats = {nutrient_id: distribution(values) for nutrient_id, values in nutrients.items()}
        write_dish_nutrient_stats(client, dish_id=dish_id, stats=stats)
    logger.info("materialize: wrote nutrient distribution statistics on %d dish(es)", len(by_dish))
    return len(by_dish)


def run_materialize() -> None:
    """Selective alternative-preparation variant materialization plus dish-level statistics. For each
    already-ingested recipe, generate a bounded set of culinarily-valid alternative-method variants
    and write each variant's cooked per-serving HAS_NUTRIENT vector (four-channel transform over the
    persisted raw vectors). Then materialize per-dish nutrient distributions on each `:Dish` across
    its versions (contract Section 5). Functional against a graph that `run_ingest` and `run_cluster`
    populated."""
    logger.info("materialize: reading ingested recipes for alternative-variant expansion")
    with GraphClient.from_env() as client:
        _run_materialize_with_client(client)
        _run_dish_stats_with_client(client)
