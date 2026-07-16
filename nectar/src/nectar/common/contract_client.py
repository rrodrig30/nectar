"""Read-only Neo4j accessors pinned to the contract version. All Cypher lives here, parameterized.

NECTAR holds a read role on Neo4j (see ../../../deploy/README.md); nothing in this module opens a
write transaction. The gated write-back path lives in `research/verify.py` and talks to a separate
service, not a Neo4j write session (DATA_CONTRACT.md Section 8; ../../docs/PDD.md Section 4).

Every accessor here issues one parameterized read query and returns either a shared program type
(`VariantFacts`, `Constraint`) reused from the engine, or a plain dict for reference lookups that
have no shared type. Node labels and relationship types come from `nectar_contract.names`, never
hardcoded, so a contract change is a one-line edit there rather than a hunt through query strings.
Only data values (dish ids, condition ids, embeddings, ...) are ever passed as query parameters;
labels and relationship types are fixed identifiers pinned by the contract, not runtime input.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from types import TracebackType
from typing import Any, Self

from neo4j import READ_ACCESS, Driver, GraphDatabase

from nectar_contract import CONTRACT_VERSION
from nectar_contract.names import (
    ACTS_ON,
    ADDRESSED_BY,
    COMPOUND,
    CONDITION,
    CONTAINS,
    DIETARY_RULE,
    DISH,
    EVIDENCED_BY,
    FOOD,
    FOOD_ATTRIBUTE,
    GUIDELINE,
    HAS_ATTRIBUTE,
    HAS_COMPOUND,
    HAS_NUTRIENT,
    HAS_VARIANT,
    HAS_VERSION,
    IMPLEMENTED_BY,
    IMPOSES,
    INTERVENTION_CLASS,
    NUTRIENT,
    PREPARATION,
    RECIPE,
    RECIPE_VARIANT,
    USES,
)

from nectar.engine.constraints import VariantFacts
from nectar.scoring.suitability import Constraint

# The guideline vector index name from DATA_CONTRACT.md Section 4. Index names are not part of
# nectar_contract.names (that module holds node/relationship names); this is the one place the
# fixed index identifier lives.
_GUIDELINE_VECTOR_INDEX = "guideline_embed"

# DietaryRule.direction values that are plan-level, not single-recipe (DATA_CONTRACT.md Section
# 6.3); NECTAR's meal planner evaluates these across the plan window, not per RecipeVariant.
_MAINTAIN_DIRECTION = "maintain"
_RESTRICT_DIRECTIONS = frozenset({"avoid", "limit"})
_TARGET_DIRECTIONS = frozenset({"target", "prefer"})
# Only an "absolute" severity produces a hard_limit: a hard-limit breach is a contraindication,
# never a graded low score (CLAUDE.md invariant; scoring/suitability.py).
_ABSOLUTE_SEVERITY = "absolute"

_VARIANTS_FOR_DISH = f"""
MATCH (:{DISH} {{dish_id: $dish_id}})-[:{HAS_VERSION}]->(:{RECIPE})-[:{HAS_VARIANT}]->(v:{RECIPE_VARIANT})
OPTIONAL MATCH (v)-[hn:{HAS_NUTRIENT}]->(n:{NUTRIENT})
OPTIONAL MATCH (v)-[:{HAS_ATTRIBUTE}]->(a:{FOOD_ATTRIBUTE})
OPTIONAL MATCH (v)-[:{HAS_COMPOUND}]->(c:{COMPOUND})
OPTIONAL MATCH (v)-[:{USES}]->(p:{PREPARATION})
RETURN v.variant_id AS variant_id,
       $dish_id AS dish_id,
       collect(DISTINCT CASE WHEN n IS NULL THEN NULL
                         ELSE {{nutrient_id: n.nutrient_id, amount: hn.amount_per_serving,
                                source: hn.source, confidence: hn.confidence}} END)
         AS nutrient_rows,
       collect(DISTINCT a.attribute_id) AS attribute_ids,
       collect(DISTINCT c.compound_id) AS compound_ids,
       head(collect(DISTINCT p.method)) AS method
"""

_SEARCH_DISHES = f"""
MATCH (d:{DISH})
WHERE toLower(d.canonical_name) CONTAINS toLower($q)
RETURN d.dish_id AS dish_id, d.canonical_name AS canonical_name
LIMIT $limit
"""

_LIST_CONDITIONS = f"""
MATCH (c:{CONDITION})
RETURN c.condition_id AS condition_id, c.name AS name
ORDER BY c.condition_id
"""

_LIST_NUTRIENTS = f"""
MATCH (n:{NUTRIENT})
RETURN n.nutrient_id AS nutrient_id, n.name AS name, n.unit AS unit
ORDER BY n.nutrient_id
"""

# The primary recipe for a dish (highest confidence), with its ingredient list and the parsed
# preparation (method + cut) for each ingredient. Preparation is joined by the prep_id string that
# CONTAINS carries (Preparation nodes are keyed by prep_id, not linked by an edge).
_RECIPE_FOR_DISH = f"""
MATCH (d:{DISH} {{dish_id: $dish_id}})-[:{HAS_VERSION}]->(r:{RECIPE})
WITH r ORDER BY coalesce(r.confidence, 0.0) DESC LIMIT 1
OPTIONAL MATCH (r)-[c:{CONTAINS}]->(f:{FOOD})
OPTIONAL MATCH (p:{PREPARATION} {{prep_id: c.prep_id}})
WITH r, c, f, p ORDER BY coalesce(c.raw_mass_g, 0.0) DESC
RETURN r.recipe_id AS recipe_id, r.title AS title, r.servings AS servings,
       r.source_id AS source_id, r.license AS license,
       collect(CASE WHEN f IS NULL THEN NULL ELSE
         {{food: f.description, amount: c.raw_mass_g, method: p.method, cut_class: p.cut_class}}
       END) AS ingredients
"""

_CONSTRAINTS_FOR_CONDITION = f"""
MATCH (:{CONDITION} {{condition_id: $condition_id}})-[:{IMPOSES}]->(r:{DIETARY_RULE})
      -[:{ACTS_ON}]->(n:{NUTRIENT})
OPTIONAL MATCH (r)-[:{EVIDENCED_BY}]->(g:{GUIDELINE})
RETURN r.rule_id AS rule_id,
       n.nutrient_id AS nutrient_id,
       r.direction AS direction,
       r.severity AS severity,
       r.threshold AS threshold,
       r.unit AS unit,
       r.safety_critical AS safety_critical,
       head(collect(g.guideline_id)) AS guideline_id
"""

_GUIDELINE_PASSAGES = f"""
MATCH (g:{GUIDELINE})
WHERE g.guideline_id IN $ids
RETURN g.guideline_id AS guideline_id, g.org AS org, g.title AS title, g.year AS year,
       g.chunk AS chunk
"""

_SEARCH_GUIDELINES = """
CALL db.index.vector.queryNodes($index_name, $k, $embedding)
YIELD node, score
RETURN node.guideline_id AS guideline_id, node.org AS org, node.title AS title,
       node.year AS year, node.chunk AS chunk, score
ORDER BY score DESC
"""

_INTERVENTIONS_FOR_TARGET = f"""
MATCH (t)-[:{ADDRESSED_BY}]->(ic:{INTERVENTION_CLASS})
WHERE t.nutrient_id = $target_id OR t.compound_id = $target_id
OPTIONAL MATCH (ic)-[:{IMPLEMENTED_BY}]->(impl)
RETURN ic.class_id AS class_id,
       ic.name AS name,
       ic.mechanism AS mechanism,
       collect(DISTINCT CASE WHEN impl IS NULL THEN NULL
                        ELSE {{id: coalesce(impl.method_id, impl.hyp_id), labels: labels(impl)}}
                        END) AS implementations
"""

# Dish-level nutrient distribution statistics (DATA_CONTRACT.md Section 5). NutriScrape materializes
# these on the :Dish node as parallel primitive arrays indexed by stat_nutrient_ids, since a Neo4j
# node property cannot hold a nested map; this reads them back to reassemble the per-nutrient view.
_DISH_NUTRIENT_STATS = f"""
MATCH (d:{DISH} {{dish_id: $dish_id}})
OPTIONAL MATCH (n:{NUTRIENT}) WHERE n.nutrient_id IN d.stat_nutrient_ids
WITH d, collect({{id: n.nutrient_id, unit: n.unit}}) AS units
RETURN d.stat_nutrient_ids AS nutrient_ids,
       d.stat_count AS count,
       d.stat_min AS minimum,
       d.stat_max AS maximum,
       d.stat_mean AS mean,
       d.stat_median AS median,
       d.stat_stdev AS stdev,
       units AS units
"""


@dataclass(frozen=True)
class DishNutrientStat:
    """One nutrient's distribution across a dish's versions (DATA_CONTRACT.md Section 5). NECTAR reads
    this to show a dish's version spread (for example, potassium 378 to 964 mg across four versions)
    without re-reading every RecipeVariant. `unit` is the nutrient's canonical unit (from `:Nutrient`)
    so the presentation layer can label the values."""

    nutrient: str
    count: int
    minimum: float
    maximum: float
    mean: float
    median: float
    stdev: float
    unit: str = ""


def _dish_stats_from_row(row: dict[str, Any]) -> dict[str, DishNutrientStat]:
    """Reassemble the per-nutrient distribution map from the :Dish node's parallel stat arrays.

    Returns an empty map when the dish has no materialized statistics (the arrays are null, for a
    dish that clustered before `run_materialize`), or when the arrays are inconsistent in length, so
    a partially-written node fails closed rather than raising on a mismatched index.
    """
    ids = row.get("nutrient_ids")
    if not ids:
        return {}
    count = row.get("count") or []
    minimum = row.get("minimum") or []
    maximum = row.get("maximum") or []
    mean = row.get("mean") or []
    median = row.get("median") or []
    stdev = row.get("stdev") or []
    length = len(ids)
    if any(len(arr) != length for arr in (count, minimum, maximum, mean, median, stdev)):
        return {}
    unit_by_id = {
        str(entry["id"]): str(entry.get("unit") or "")
        for entry in (row.get("units") or [])
        if entry.get("id") is not None
    }
    return {
        str(nutrient_id): DishNutrientStat(
            nutrient=str(nutrient_id),
            count=int(count[index]),
            minimum=float(minimum[index]),
            maximum=float(maximum[index]),
            mean=float(mean[index]),
            median=float(median[index]),
            stdev=float(stdev[index]),
            unit=unit_by_id.get(str(nutrient_id), ""),
        )
        for index, nutrient_id in enumerate(ids)
    }


def _rule_row_to_constraint(row: dict[str, Any]) -> Constraint | None:
    """Map one Condition-IMPOSES->DietaryRule-ACTS_ON->Nutrient row to a scoring `Constraint`.

    Returns None for `maintain`-direction rules (plan-level, not per-variant; Section 6.3) and for
    any direction outside the known vocabulary, so an unrecognized future direction fails closed
    rather than silently entering the engine as an unconstrained pass.
    """
    direction = row["direction"]
    if direction in _RESTRICT_DIRECTIONS:
        is_absolute = row["severity"] == _ABSOLUTE_SEVERITY
        threshold = row["threshold"]
        return Constraint(
            nutrient=row["nutrient_id"],
            type="restrict",
            unit=row["unit"] or "",
            max_per_serving=None if is_absolute else threshold,
            hard_limit=threshold if is_absolute else None,
            safety_critical=bool(row["safety_critical"]),
            guideline_id=row["guideline_id"] or "",
        )
    if direction in _TARGET_DIRECTIONS:
        return Constraint(
            nutrient=row["nutrient_id"],
            type="target",
            unit=row["unit"] or "",
            goal=row["threshold"],
            safety_critical=bool(row["safety_critical"]),
            guideline_id=row["guideline_id"] or "",
        )
    return None


class ContractClient:
    """Read-only accessor over the shared graph, pinned to `contract_version`.

    NECTAR never writes through this client; see module docstring. Construct with `from_env()` in
    application code, or with an explicit `Driver` in tests.
    """

    contract_version: str = CONTRACT_VERSION

    def __init__(self, driver: Driver, *, database: str | None = None) -> None:
        self._driver = driver
        self._database = database

    @classmethod
    def from_env(cls) -> ContractClient:
        """Build a client from `NEO4J_URI` / `NEO4J_USER` / `NEO4J_PASSWORD` (the read role's
        credentials; see ../../../deploy/README.md). `NEO4J_DATABASE` is optional."""
        uri = os.environ["NEO4J_URI"]
        user = os.environ["NEO4J_USER"]
        password = os.environ["NEO4J_PASSWORD"]
        database = os.environ.get("NEO4J_DATABASE")
        driver = GraphDatabase.driver(uri, auth=(user, password))
        return cls(driver, database=database)

    def close(self) -> None:
        self._driver.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def _read(self, query: str, **parameters: Any) -> list[dict[str, Any]]:
        """Run one parameterized query in a read-only session and return the raw rows."""
        session_kwargs: dict[str, Any] = {"default_access_mode": READ_ACCESS}
        if self._database is not None:
            session_kwargs["database"] = self._database
        with self._driver.session(**session_kwargs) as session:
            result = session.run(query, parameters)
            return result.data()

    def variants_for_dish(self, dish_id: str) -> list[VariantFacts]:
        """All RecipeVariant facts for one Dish (contract Section 3.1), as `VariantFacts`.

        `attributes` merges FoodAttribute and Compound ids present on the variant, matching
        `VariantFacts`' contract: it is the set Stage 1 hard filters check against.
        """
        rows = self._read(_VARIANTS_FOR_DISH, dish_id=dish_id)
        facts: list[VariantFacts] = []
        for row in rows:
            valid_nutrient_rows = [
                nutrient_row for nutrient_row in row["nutrient_rows"]
                if nutrient_row is not None and nutrient_row["nutrient_id"] is not None
            ]
            nutrients = {r["nutrient_id"]: r["amount"] for r in valid_nutrient_rows}
            # Carry each value's source/confidence so the disclaimer is specific, not generic.
            nutrient_provenance = {
                r["nutrient_id"]: (
                    str(r.get("source") or "calculated"),
                    float(r["confidence"]) if r.get("confidence") is not None else 0.5,
                )
                for r in valid_nutrient_rows
            }
            attributes = frozenset(
                {attr for attr in row["attribute_ids"] if attr is not None}
                | {comp for comp in row["compound_ids"] if comp is not None}
            )
            facts.append(
                VariantFacts(
                    variant_id=row["variant_id"],
                    dish_id=row["dish_id"],
                    nutrients=nutrients,
                    attributes=attributes,
                    method=row["method"] or "",
                    nutrient_provenance=nutrient_provenance,
                )
            )
        return facts

    def search_dishes(self, query: str, limit: int = 20) -> list[dict[str, Any]]:
        """Dishes whose canonical_name contains `query` (case-insensitive), for the clinician's
        dish-picker. Read-only, bounded by `limit`; `LIMIT` lets the scan terminate early rather
        than sorting the whole corpus. Returns `{dish_id, canonical_name}` rows."""
        return self._read(_SEARCH_DISHES, q=query, limit=limit)

    def list_conditions(self) -> list[dict[str, Any]]:
        """All `:Condition` nodes in the knowledge base (`{condition_id, name}`), so the UI can
        offer a real condition selector rather than free-text ids."""
        return self._read(_LIST_CONDITIONS)

    def list_nutrients(self) -> list[dict[str, Any]]:
        """The speciated nutrient vocabulary (`{nutrient_id, name, unit}`), so the UI can label
        nutrient values with a human name and their canonical unit."""
        return self._read(_LIST_NUTRIENTS)

    def recipe_for_dish(self, dish_id: str) -> dict[str, Any] | None:
        """The primary recipe for a dish: title, servings, source/license, and the ingredient list
        with each ingredient's parsed preparation (method, cut). Returns None when the dish has no
        recipe. Ingredient entries whose food did not resolve are dropped."""
        rows = self._read(_RECIPE_FOR_DISH, dish_id=dish_id)
        if not rows:
            return None
        row = rows[0]
        row["ingredients"] = [ing for ing in row.get("ingredients", []) if ing is not None]
        return row

    def dish_nutrient_stats(self, dish_id: str) -> dict[str, DishNutrientStat]:
        """Per-nutrient distribution statistics across a Dish's versions (contract Section 5), keyed
        by nutrient_id. Empty when the dish has no materialized statistics (see
        `_dish_stats_from_row`); the caller need not special-case an unstatistified dish."""
        rows = self._read(_DISH_NUTRIENT_STATS, dish_id=dish_id)
        if not rows:
            return {}
        return _dish_stats_from_row(rows[0])

    def constraints_for_condition(self, condition_id: str) -> list[Constraint]:
        """Nutrient-targeted DietaryRules a Condition imposes (contract Section 3.3), as scoring
        `Constraint` objects. See `_rule_row_to_constraint` for the direction/severity mapping."""
        rows = self._read(_CONSTRAINTS_FOR_CONDITION, condition_id=condition_id)
        constraints: list[Constraint] = []
        for row in rows:
            constraint = _rule_row_to_constraint(row)
            if constraint is not None:
                constraints.append(constraint)
        return constraints

    def guideline_passages(self, ids: list[str]) -> list[dict[str, Any]]:
        """Guideline passages by id, for citation in `interact/explain.py`."""
        return self._read(_GUIDELINE_PASSAGES, ids=list(ids))

    def search_guidelines(self, embedding: list[float], k: int) -> list[dict[str, Any]]:
        """Nearest guideline passages to `embedding` via the `guideline_embed` vector index
        (DATA_CONTRACT.md Section 4). The caller supplies `embedding`; this module never computes
        one (embeddings are not a NECTAR contract-layer concern, and no nutrient or clinical
        number is ever produced by a model here)."""
        return self._read(
            _SEARCH_GUIDELINES, index_name=_GUIDELINE_VECTOR_INDEX, k=k, embedding=embedding
        )

    def interventions_for_target(self, target_id: str) -> list[dict[str, Any]]:
        """InterventionClasses addressing a failing Nutrient or Compound target, with their
        Method/HypothesisTransform implementations (contract Section 3.4). Callers on the patient
        recommendation path (`engine/remediate.py`) must themselves exclude HypothesisTransform
        implementations: Tier C is research-only and must not surface as a remediation
        (DATA_CONTRACT.md Section 1.3); this accessor returns the raw graph facts undistinguished
        by tier so the research channel can still retrieve Tier C hypotheses through it."""
        return self._read(_INTERVENTIONS_FOR_TARGET, target_id=target_id)
