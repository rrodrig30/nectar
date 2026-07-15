"""Load stage of the bulk path: `LOAD CSV ... IN TRANSACTIONS` the exported CSVs into Neo4j.

Why this beats the transactional ingest at scale: it runs server-side in a SINGLE implicit
transaction stream (batched commits), so there are no client round trips and, crucially, no
concurrent writers -- the shared :Nutrient / :Food nodes never see two transactions at once, so the
relationship-group deadlocks that collapsed the parallel ingest cannot occur. :Food and :Nutrient
are matched (fdc-import and the knowledge load created them); only :Recipe / :RecipeVariant /
:Preparation and their edges are created here.

The CSVs must sit in Neo4j's import directory; `file:///recipes.csv` resolves there. Statements run
in dependency order: recipes -> preparations -> variants -> contains -> has_nutrient.
"""
from __future__ import annotations

import logging
import os

from nutriscrape.graph.client import GraphClient

logger = logging.getLogger(__name__)

_BATCH = 5000

# Each statement streams one CSV in batched auto-commit transactions. `CALL { WITH row ... } IN
# TRANSACTIONS` must run as an implicit transaction (GraphClient.run / session.run), never inside an
# explicit execute_write. Empty CSV cells become "", and toFloat("") is null, so optional numeric
# properties (water_ratio, time_min, temp_c) are left unset rather than zeroed.
_LOAD_RECIPES = f"""
LOAD CSV WITH HEADERS FROM 'file:///recipes.csv' AS row
CALL {{ WITH row
  MERGE (r:Recipe {{recipe_id: row.recipe_id}})
  SET r.title = row.title, r.source_id = row.source_id, r.license = row.license,
      r.servings = toFloat(row.servings), r.confidence = toFloat(row.confidence)
}} IN TRANSACTIONS OF {_BATCH} ROWS
"""

_LOAD_PREPARATIONS = f"""
LOAD CSV WITH HEADERS FROM 'file:///preparations.csv' AS row
CALL {{ WITH row
  MERGE (p:Preparation {{prep_id: row.prep_id}})
  SET p.method = row.method, p.cut_class = row.cut_class,
      p.water_ratio = toFloat(row.water_ratio),
      p.liquid_retained_frac = toFloat(row.liquid_retained_frac),
      p.time_min = toFloat(row.time_min), p.temp_c = toFloat(row.temp_c)
}} IN TRANSACTIONS OF {_BATCH} ROWS
"""

_LOAD_VARIANTS = f"""
LOAD CSV WITH HEADERS FROM 'file:///variants.csv' AS row
CALL {{ WITH row
  MATCH (r:Recipe {{recipe_id: row.recipe_id}})
  MERGE (v:RecipeVariant {{variant_id: row.variant_id}})
  SET v.is_as_authored = true, v.confidence = toFloat(row.confidence)
  MERGE (r)-[:HAS_VARIANT]->(v)
}} IN TRANSACTIONS OF {_BATCH} ROWS
"""

_LOAD_CONTAINS = f"""
LOAD CSV WITH HEADERS FROM 'file:///contains.csv' AS row
CALL {{ WITH row
  MATCH (r:Recipe {{recipe_id: row.recipe_id}})
  MATCH (f:Food {{fdc_id: row.fdc_id}})
  MERGE (r)-[c:CONTAINS {{prep_id: row.prep_id}}]->(f)
  SET c.raw_mass_g = toFloat(row.raw_mass_g)
}} IN TRANSACTIONS OF {_BATCH} ROWS
"""

_LOAD_HAS_NUTRIENT = f"""
LOAD CSV WITH HEADERS FROM 'file:///has_nutrient.csv' AS row
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
    ("recipes", _LOAD_RECIPES),
    ("preparations", _LOAD_PREPARATIONS),
    ("variants", _LOAD_VARIANTS),
    ("contains", _LOAD_CONTAINS),
    ("has_nutrient", _LOAD_HAS_NUTRIENT),
]


def run_bulk_load(client: GraphClient) -> None:
    """Run the five LOAD CSV statements in dependency order against `client`'s database.

    Idempotent: every statement MERGEs, so a re-run over the same CSVs updates in place. Assumes the
    CSVs are in Neo4j's import directory and that fdc-import + the knowledge load have already
    created the :Food and :Nutrient nodes the relationship loads MATCH.
    """
    contract_version = os.environ.get("CONTRACT_VERSION", "1.0")
    for name, statement in _STEPS:
        logger.info("bulk-load: loading %s.csv ...", name)
        client.run(statement, contract_version=contract_version)
        logger.info("bulk-load: %s.csv loaded", name)
    logger.info("bulk-load: all CSVs loaded")
