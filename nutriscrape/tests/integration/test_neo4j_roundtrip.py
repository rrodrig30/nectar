"""Integration test against a real Neo4j via testcontainers.

Validates the shared-contract Cypher end to end on a live database: NutriScrape's schema DDL and
writers, NutriScrape's readers, and NECTAR's ContractClient reads all run against real Neo4j, which
catches label / property / syntax mismatches that the in-memory fakes in the other test modules
cannot. This is the one place the two programs' Cypher is exercised where it actually runs.

Skipped automatically when testcontainers or a Docker runtime is unavailable, so `make check`
(unit + clinical) is unaffected; `make test-int` runs it when the infrastructure is present.
"""
from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("testcontainers.neo4j")

from neo4j import GraphDatabase  # noqa: E402
from testcontainers.neo4j import Neo4jContainer  # noqa: E402

from nectar_contract.types import Provenance  # noqa: E402
from nutriscrape import pipeline  # noqa: E402
from nutriscrape.acquisition.adapters.base import RawRecipe  # noqa: E402
from nutriscrape.graph import readers, writers  # noqa: E402
from nutriscrape.graph.client import GraphClient  # noqa: E402
from nutriscrape.graph.schema import apply_schema  # noqa: E402
from nutriscrape.nutrition.distribution import distribution  # noqa: E402

_FDC_FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "fdc"

_IMAGE = "neo4j:5.20"
_PASSWORD = "testpassword"
_PROV = Provenance(source="transform:retn06", confidence=0.5, evidence_tier="A",
                   computed_by="nutrition.compose", contract_version="1.0")


def _seed(client: GraphClient) -> None:
    """Apply the real contract DDL, then write one dish -> recipe -> two variants (378 and 964 mg
    potassium) and the dish nutrient distribution, entirely through NutriScrape's writers."""
    apply_schema(client)
    writers.merge_dish(client, dish_id="dish:pot", canonical_name="Boiled Potatoes",
                       cluster_confidence=0.9)
    writers.merge_recipe(client, recipe_id="r1", title="Boiled Potatoes", source_id="test",
                         license="test", servings=4.0, confidence=0.6)
    writers.link_dish_recipe(client, dish_id="dish:pot", recipe_id="r1")
    writers.merge_nutrient(client, nutrient_id="potassium", name="Potassium", unit="mg")
    for variant_id, potassium, authored in (("r1:v0", 378.0, True), ("r1:v1", 964.0, False)):
        writers.merge_recipe_variant(client, variant_id=variant_id, is_as_authored=authored,
                                     confidence=0.5)
        writers.link_recipe_variant(client, recipe_id="r1", variant_id=variant_id)
        writers.write_has_nutrient(client, variant_id=variant_id, nutrient_id="potassium",
                                   amount_per_serving=potassium, unit="mg", provenance=_PROV)
    writers.write_dish_nutrient_stats(client, dish_id="dish:pot",
                                      stats={"potassium": distribution([378.0, 964.0])})


@pytest.fixture(scope="module")
def graph_driver():
    try:
        container = Neo4jContainer(_IMAGE, password=_PASSWORD)
        container.start()
    except Exception as exc:   # Docker not running, image unpullable, startup timeout, etc.
        pytest.skip(f"Neo4j testcontainer unavailable ({type(exc).__name__}: {exc})")
    driver = None
    try:
        driver = GraphDatabase.driver(container.get_connection_url(), auth=("neo4j", _PASSWORD))
        driver.verify_connectivity()
        _seed(GraphClient(driver))
        yield driver
    finally:
        if driver is not None:
            driver.close()
        container.stop()


def test_nutriscrape_reads_back_what_it_wrote(graph_driver):
    by_dish = readers.read_dish_variant_nutrients(GraphClient(graph_driver))
    assert sorted(by_dish["dish:pot"]["potassium"]) == [378.0, 964.0]


def test_nectar_contract_client_reads_the_written_graph(graph_driver):
    contract = pytest.importorskip("nectar.common.contract_client")
    client = contract.ContractClient(graph_driver)

    variants = client.variants_for_dish("dish:pot")
    by_id = {v.variant_id: v for v in variants}
    assert set(by_id) == {"r1:v0", "r1:v1"}
    assert by_id["r1:v0"].nutrients["potassium"] == 378.0
    assert by_id["r1:v1"].nutrients["potassium"] == 964.0
    # per-nutrient provenance threaded through so the calculated-not-measured disclaimer is specific
    source, confidence = by_id["r1:v0"].nutrient_provenance["potassium"]
    assert source.startswith("transform") and confidence == 0.5

    stats = client.dish_nutrient_stats("dish:pot")
    assert "potassium" in stats
    assert stats["potassium"].minimum == 378.0 and stats["potassium"].maximum == 964.0
    assert stats["potassium"].count == 2 and stats["potassium"].unit == "mg"


def test_bulk_import_then_local_resolution_and_ingest(graph_driver):
    """The scale path end to end on real Neo4j: import the FDC CSV bulk fixture into :Food +
    HAS_NUTRIENT_RAW, then ingest a recipe resolving foods against the local full-text index (no FDC
    API), and read the cooked potassium back."""
    client = GraphClient(graph_driver)

    imported = pipeline._import_fdc_bulk(str(_FDC_FIXTURE), client)
    assert imported == 2
    client.run("CALL db.awaitIndexes(60)")   # let the food full-text index finish populating

    assert readers.has_foods(client)
    candidates = readers.search_foods(client, "potatoes")
    assert any(candidate.description.startswith("Potatoes") for candidate in candidates)
    assert readers.read_raw_vector(client, "170026")["potassium"] == 425.0

    recipe = RawRecipe(
        recipe_id="rt_potato", title="Boiled and Drained Potatoes", source_id="test", license="test",
        servings=4.0, ingredient_lines=("2 pounds potatoes, peeled and cubed",),
        preparation_steps=("Boil the cubed potatoes for 15 minutes.", "Drain the potatoes well."))
    pipeline._ingest_recipe(recipe, pipeline._local_ingest_deps(client), client)

    rows = client.run(
        "MATCH (:Recipe {recipe_id: $recipe_id})-[:HAS_VARIANT]->(:RecipeVariant)"
        "-[h:HAS_NUTRIENT]->(:Nutrient {nutrient_id: 'potassium'}) "
        "RETURN h.amount_per_serving AS potassium",
        recipe_id="rt_potato",
    )
    assert rows and rows[0]["potassium"] > 0.0   # cooked from the locally-imported raw vector
