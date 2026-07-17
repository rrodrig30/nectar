"""Read already-ingested recipes back out of the graph for corpus-wide clustering.

The read-side counterpart to `writers.py`: parameterized read Cypher, all in this module, names from
`nectar_contract.names`. Clustering (SDD Section 5) recognizes independently-ingested recipes as
versions of one dish, which means re-reading what `run_ingest` wrote and rebuilding a clustering
`RecipeInput` (resolved FDC foods and masses, a primary method, the title) per recipe.
"""
from __future__ import annotations
import re
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass

from nectar_contract import names

from nutriscrape.clustering.fingerprint import RecipeInput
from nutriscrape.graph.client import GraphClient
from nutriscrape.nutrition.transform import Preparation
from nutriscrape.resolution.fdc_client import FdcCandidate

# One row per :Recipe, gathering its CONTAINS foods (fdc_id, raw_mass_g, and the per-food method the
# ingest wrote onto CONTAINS.prep_id). A recipe with no resolved food yields no row (INNER match).
_READ_RECIPE_INPUTS = f"""
MATCH (r:{names.RECIPE})-[c:{names.CONTAINS}]->(f:{names.FOOD})
OPTIONAL MATCH (p:{names.PREPARATION} {{prep_id: c.prep_id}})
WITH r, collect({{fdc_id: f.fdc_id, mass_g: c.raw_mass_g, method: p.method}}) AS foods
RETURN r.recipe_id AS recipe_id, r.title AS title, foods
"""


def read_recipe_inputs(client: GraphClient) -> list[RecipeInput]:
    """Rebuild a clustering `RecipeInput` for every ingested recipe that has at least one resolved
    food. The primary method is the most common CONTAINS method across the recipe's foods."""
    rows = client.run(_READ_RECIPE_INPUTS)
    inputs: list[RecipeInput] = []
    for row in rows:
        foods: dict[str, float] = {}
        methods: list[str] = []
        for entry in row["foods"]:
            fdc_id = entry.get("fdc_id")
            if fdc_id is None:
                continue
            mass = entry.get("mass_g")
            foods[str(fdc_id)] = float(mass) if mass is not None else 0.0
            method = entry.get("method")
            if method:
                methods.append(str(method))
        if not foods:
            continue
        primary_method = Counter(methods).most_common(1)[0][0] if methods else ""
        title = str(row["title"]) if row["title"] is not None else ""
        inputs.append(RecipeInput(recipe_id=str(row["recipe_id"]), foods=foods,
                                  primary_method=primary_method, title=title))
    return inputs


@dataclass(frozen=True)
class MaterializeIngredient:
    """One ingredient of an already-ingested recipe, with everything materialize needs to re-cook it
    under an alternative method offline: its resolved food, mass, as-authored prep, and raw vector."""
    fdc_id: str
    description: str
    mass_g: float
    prep: Preparation
    raw_per_100g: dict[str, float]


@dataclass(frozen=True)
class MaterializeRecipe:
    recipe_id: str
    servings: float
    ingredients: list[MaterializeIngredient]


# Reads each recipe's foods with the CONTAINS mass, the referenced :Preparation params, and the
# food's intrinsic HAS_NUTRIENT_RAW per-100g vector, so re-cooking needs no FDC round trip. The batch
# form restricts to a page of recipe_ids so a single transaction never holds the whole corpus (each
# food occurrence inlines its full raw vector, so the unbounded read blows the transaction memory
# ceiling at corpus scale, no matter the heap). `iter_recipes_for_materialize` pages by recipe_id.
_MATERIALIZE_BODY = f"""
OPTIONAL MATCH (p:{names.PREPARATION} {{prep_id: c.prep_id}})
OPTIONAL MATCH (f)-[hr:{names.HAS_NUTRIENT_RAW}]->(rn:{names.NUTRIENT})
WITH r, f, c, p, collect({{nutrient_id: rn.nutrient_id, amount: hr.amount_per_100g}}) AS raw
WITH r, collect({{
        fdc_id: f.fdc_id, description: f.description, mass_g: c.raw_mass_g,
        method: p.method, cut_class: p.cut_class, water_ratio: p.water_ratio,
        liquid_retained_frac: p.liquid_retained_frac, time_min: p.time_min, temp_c: p.temp_c,
        raw: raw
     }}) AS foods
RETURN r.recipe_id AS recipe_id, r.servings AS servings, foods
"""

_READ_MATERIALIZE = f"""
MATCH (r:{names.RECIPE})-[c:{names.CONTAINS}]->(f:{names.FOOD})
{_MATERIALIZE_BODY}
"""

_READ_MATERIALIZE_BATCH = f"""
MATCH (r:{names.RECIPE})-[c:{names.CONTAINS}]->(f:{names.FOOD})
WHERE r.recipe_id IN $ids
{_MATERIALIZE_BODY}
"""

# Keyset page over recipe_ids (backed by the recipe_id uniqueness index): efficient at any offset,
# constant memory, unlike SKIP which is O(offset) per page.
_PAGE_RECIPE_IDS = f"""
MATCH (r:{names.RECIPE})
WHERE r.recipe_id > $after
RETURN r.recipe_id AS recipe_id
ORDER BY r.recipe_id
LIMIT $limit
"""


def _materialize_recipe_from_row(row: dict[str, object]) -> MaterializeRecipe | None:
    """Rebuild one `MaterializeRecipe` from a materialize read row, or None if it has no re-cookable
    ingredient. Foods with no persisted raw vector are dropped (there is nothing to re-cook)."""
    ingredients: list[MaterializeIngredient] = []
    for entry in row["foods"]:  # type: ignore[attr-defined]
        fdc_id = entry.get("fdc_id")
        if fdc_id is None:
            continue
        raw_per_100g = {
            str(item["nutrient_id"]): float(item["amount"])
            for item in entry.get("raw", [])
            if item.get("nutrient_id") is not None and item.get("amount") is not None
        }
        if not raw_per_100g:
            continue
        mass = entry.get("mass_g")
        prep = Preparation(
            method=str(entry.get("method") or "raw"),
            cut_class=str(entry.get("cut_class") or "whole"),
            water_ratio=entry.get("water_ratio"),
            liquid_retained_frac=(
                float(entry["liquid_retained_frac"])
                if entry.get("liquid_retained_frac") is not None else 1.0
            ),
            time_min=entry.get("time_min"),
            temp_c=entry.get("temp_c"),
        )
        ingredients.append(MaterializeIngredient(
            fdc_id=str(fdc_id),
            description=str(entry.get("description") or ""),
            mass_g=float(mass) if mass is not None else 0.0,
            prep=prep,
            raw_per_100g=raw_per_100g,
        ))
    if not ingredients:
        return None
    servings = row.get("servings")
    return MaterializeRecipe(
        recipe_id=str(row["recipe_id"]),
        servings=float(servings) if servings else 1.0,  # type: ignore[arg-type]
        ingredients=ingredients,
    )


def read_recipes_for_materialize(client: GraphClient) -> list[MaterializeRecipe]:
    """Rebuild every ingested recipe with its as-authored preparations and food raw vectors in one
    read. Correct for small graphs (tests, integration); at corpus scale use
    `iter_recipes_for_materialize`, which pages so no single transaction holds the whole corpus."""
    recipes: list[MaterializeRecipe] = []
    for row in client.run(_READ_MATERIALIZE):
        recipe = _materialize_recipe_from_row(row)
        if recipe is not None:
            recipes.append(recipe)
    return recipes


def iter_recipes_for_materialize(
    client: GraphClient, batch_size: int = 2000
) -> Iterator[list[MaterializeRecipe]]:
    """Page ingested recipes for materialize by recipe_id, yielding one bounded batch of
    `MaterializeRecipe` at a time. Each batch reads only its page of recipe_ids (`WHERE r.recipe_id
    IN $ids`), so the transaction memory stays bounded regardless of corpus size. Recipes with no
    re-cookable ingredient are dropped, so a batch may yield fewer than `batch_size` recipes (or
    none), but paging always advances by the full page of ids."""
    after = ""
    while True:
        id_rows = client.run(_PAGE_RECIPE_IDS, after=after, limit=batch_size)
        ids = [str(r["recipe_id"]) for r in id_rows if r.get("recipe_id") is not None]
        if not ids:
            break
        after = ids[-1]
        rows = client.run(_READ_MATERIALIZE_BATCH, ids=ids)
        batch = [
            recipe for recipe in (_materialize_recipe_from_row(row) for row in rows)
            if recipe is not None
        ]
        if batch:
            yield batch
        if len(id_rows) < batch_size:
            break


# Every cooked HAS_NUTRIENT amount across every variant of every recipe in a dish, grouped by dish
# and nutrient, so the distribution across the dish's versions can be summarized (contract Section 5).
# The batch form restricts to a page of dish_ids; the unbounded read collects every variant amount
# across all ~1M dishes into one transaction, which blows the memory ceiling at corpus scale.
_DISH_NUTRIENTS_BODY = f"""
MATCH (d)-[:{names.HAS_VERSION}]->(:{names.RECIPE})
      -[:{names.HAS_VARIANT}]->(:{names.RECIPE_VARIANT})-[h:{names.HAS_NUTRIENT}]->(n:{names.NUTRIENT})
RETURN d.dish_id AS dish_id, n.nutrient_id AS nutrient_id,
       collect(h.amount_per_serving) AS amounts
"""

_READ_DISH_NUTRIENTS = f"""
MATCH (d:{names.DISH})
{_DISH_NUTRIENTS_BODY}
"""

_READ_DISH_NUTRIENTS_BATCH = f"""
MATCH (d:{names.DISH})
WHERE d.dish_id IN $ids
{_DISH_NUTRIENTS_BODY}
"""

# Keyset page over dish_ids (backed by the dish_id uniqueness index).
_PAGE_DISH_IDS = f"""
MATCH (d:{names.DISH})
WHERE d.dish_id > $after
RETURN d.dish_id AS dish_id
ORDER BY d.dish_id
LIMIT $limit
"""


def _dish_nutrients_from_rows(
    rows: list[dict[str, object]]
) -> dict[str, dict[str, list[float]]]:
    """Group dish-nutrient read rows into dish_id -> nutrient_id -> per-serving amounts."""
    out: dict[str, dict[str, list[float]]] = {}
    for row in rows:
        amounts = [float(a) for a in row["amounts"] if a is not None]  # type: ignore[attr-defined]
        if not amounts:
            continue
        out.setdefault(str(row["dish_id"]), {})[str(row["nutrient_id"])] = amounts
    return out


def read_dish_variant_nutrients(client: GraphClient) -> dict[str, dict[str, list[float]]]:
    """dish_id -> nutrient_id -> the per-serving amounts across all of the dish's variants, in one
    read. Correct for small graphs (tests, integration); at corpus scale use
    `iter_dish_variant_nutrients`, which pages by dish_id so the transaction stays bounded."""
    return _dish_nutrients_from_rows(client.run(_READ_DISH_NUTRIENTS))


def iter_dish_variant_nutrients(
    client: GraphClient, batch_size: int = 5000
) -> Iterator[dict[str, dict[str, list[float]]]]:
    """Page clustered dishes by dish_id, yielding one bounded batch of dish_id -> nutrient_id ->
    amounts at a time. Each batch reads only its page of dish_ids, so the transaction memory stays
    bounded regardless of how many dishes the corpus produced."""
    after = ""
    while True:
        id_rows = client.run(_PAGE_DISH_IDS, after=after, limit=batch_size)
        ids = [str(r["dish_id"]) for r in id_rows if r.get("dish_id") is not None]
        if not ids:
            break
        after = ids[-1]
        batch = _dish_nutrients_from_rows(client.run(_READ_DISH_NUTRIENTS_BATCH, ids=ids))
        if batch:
            yield batch
        if len(id_rows) < batch_size:
            break


# ----------------------------------------------------------------------- local food resolution
# Reads for resolving recipe ingredients against the locally-imported :Food graph (fdc-import),
# so ingest needs no per-food FDC API call. `food_fulltext` is the full-text index on
# :Food(description) declared in contract/schema/schema.cypher.

_FOOD_FULLTEXT_INDEX = "food_fulltext"
_LUCENE_STRIP = re.compile(r"[^A-Za-z0-9 ]+")


def _lucene_query(raw: str) -> str:
    """Build a Lucene query from a free-text food string that cannot break the query parser.

    Stripping metacharacters is not enough: bare reserved *words* (`AND`, `OR`, `NOT`, `TO`) are
    Lucene operators, so a real ingredient like "butter or margarine" raises a ParseException. We
    strip to alphanumerics and spaces, then wrap each remaining term in double quotes, so every
    token is parsed as a term and none can be read as an operator or syntax. Space-joined quoted
    terms match on any term (the parser's default OR), which is what candidate generation wants.
    """
    terms = _LUCENE_STRIP.sub(" ", raw).split()
    return " ".join(f'"{term}"' for term in terms)

_SEARCH_FOODS = """
CALL db.index.fulltext.queryNodes($index, $query, {limit: $limit})
YIELD node, score
RETURN node.fdc_id AS fdc_id, node.description AS description, node.data_type AS data_type,
       score AS score
"""

_READ_RAW_VECTOR = f"""
MATCH (f:{names.FOOD} {{fdc_id: $fdc_id}})-[h:{names.HAS_NUTRIENT_RAW}]->(n:{names.NUTRIENT})
RETURN n.nutrient_id AS nutrient_id, h.amount_per_100g AS amount
"""

_READ_ALL_RAW_VECTORS = f"""
MATCH (f:{names.FOOD})-[h:{names.HAS_NUTRIENT_RAW}]->(n:{names.NUTRIENT})
RETURN f.fdc_id AS fdc_id,
       collect({{nutrient_id: n.nutrient_id, amount: h.amount_per_100g}}) AS vector
"""

_HAS_FOODS = f"MATCH (f:{names.FOOD}) RETURN f LIMIT 1"


def search_foods(client: GraphClient, query: str, limit: int = 25) -> list[FdcCandidate]:
    """Full-text search of the local :Food graph for `query`, as `FdcCandidate`s the matcher ranks.
    `query` is a free-text food string; `_lucene_query` makes it parser-safe (quotes each term so a
    reserved word like OR/AND/NOT cannot break the Lucene query)."""
    sanitized = _lucene_query(query)
    if not sanitized:
        return []
    rows = client.run(_SEARCH_FOODS, index=_FOOD_FULLTEXT_INDEX, query=sanitized, limit=limit)
    candidates: list[FdcCandidate] = []
    for row in rows:
        if row.get("fdc_id") is None:
            continue
        candidates.append(FdcCandidate(
            fdc_id=int(row["fdc_id"]),
            description=str(row.get("description") or ""),
            data_type=str(row.get("data_type") or ""),
            score=float(row.get("score") or 0.0),
        ))
    return candidates


def read_raw_vector(client: GraphClient, fdc_id: str) -> dict[str, float]:
    """The food's raw per-100g nutrient vector from HAS_NUTRIENT_RAW (bulk-imported)."""
    rows = client.run(_READ_RAW_VECTOR, fdc_id=fdc_id)
    return {
        str(row["nutrient_id"]): float(row["amount"])
        for row in rows
        if row.get("nutrient_id") is not None and row.get("amount") is not None
    }


def read_all_raw_vectors(client: GraphClient) -> dict[str, dict[str, float]]:
    """Every food's raw per-100g vector, keyed by fdc_id, in one query. At corpus scale ingest
    resolves the same foods across millions of recipes, so loading the whole (small) bulk-imported
    HAS_NUTRIENT_RAW table once and serving vectors from memory replaces one Neo4j round trip per
    ingredient per recipe. The table is ~thousands of foods, so it fits in memory comfortably."""
    rows = client.run(_READ_ALL_RAW_VECTORS)
    out: dict[str, dict[str, float]] = {}
    for row in rows:
        fdc_id = row.get("fdc_id")
        if fdc_id is None:
            continue
        vector = {
            str(pair["nutrient_id"]): float(pair["amount"])
            for pair in row.get("vector") or []
            if pair.get("nutrient_id") is not None and pair.get("amount") is not None
        }
        out[str(fdc_id)] = vector
    return out


def has_foods(client: GraphClient) -> bool:
    """Whether the graph holds any :Food node (that is, whether fdc-import has populated it)."""
    return bool(client.run(_HAS_FOODS))


__all__ = ["read_recipe_inputs", "read_recipes_for_materialize", "read_dish_variant_nutrients",
           "iter_recipes_for_materialize", "iter_dish_variant_nutrients",
           "search_foods", "read_raw_vector", "read_all_raw_vectors", "has_foods",
           "MaterializeRecipe", "MaterializeIngredient"]
