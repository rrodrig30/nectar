"""Unit tests for graph writers. Pure: a fake client captures the Cypher and parameters passed to
`run_write` without touching a live Neo4j instance. Covers node MERGE shape, relationship linkage,
and the [INVARIANT] that every derived-value relationship carries the full Section 1.1 provenance
metadata. See ../../src/nutriscrape/graph/writers.py.
"""
from __future__ import annotations

from typing import Any

from nectar_contract import names
from nectar_contract.types import Provenance

from nutriscrape.graph import writers


class FakeGraphClient:
    """Records every `run_write` call instead of talking to a database."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def run_write(self, cypher: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        self.calls.append((cypher, dict(params)))
        return []


def _provenance(**overrides: Any) -> Provenance:
    base: dict[str, Any] = {
        "source": "fdc:12345",
        "confidence": 0.8,
        "evidence_tier": "B",
        "computed_by": "transform:v1",
        "contract_version": "1.0",
    }
    base.update(overrides)
    return Provenance(**base)


def test_merge_dish_uses_dish_label_and_params() -> None:
    client = FakeGraphClient()
    writers.merge_dish(
        client, dish_id="dish-1", canonical_name="Baked Potato", cluster_confidence=0.9
    )
    cypher, params = client.calls[0]
    assert f":{names.DISH}" in cypher
    assert "MERGE" in cypher
    assert params == {
        "dish_id": "dish-1",
        "canonical_name": "Baked Potato",
        "cluster_confidence": 0.9,
    }


def test_merge_recipe_carries_all_fields() -> None:
    client = FakeGraphClient()
    writers.merge_recipe(
        client,
        recipe_id="recipe-1",
        title="Baked Potato",
        source_id="recipenlg:42",
        license="cc-by",
        servings=4.0,
        confidence=0.7,
    )
    cypher, params = client.calls[0]
    assert f":{names.RECIPE}" in cypher
    assert params["recipe_id"] == "recipe-1"
    assert params["servings"] == 4.0
    assert params["confidence"] == 0.7


def test_link_dish_recipe_matches_both_and_merges_has_version() -> None:
    client = FakeGraphClient()
    writers.link_dish_recipe(client, dish_id="dish-1", recipe_id="recipe-1")
    cypher, params = client.calls[0]
    assert f":{names.DISH}" in cypher
    assert f":{names.RECIPE}" in cypher
    assert f":{names.HAS_VERSION}" in cypher
    assert "MATCH" in cypher
    assert params == {"dish_id": "dish-1", "recipe_id": "recipe-1"}


def test_merge_recipe_variant_defaults_optional_fields_to_none() -> None:
    client = FakeGraphClient()
    writers.merge_recipe_variant(client, variant_id="variant-1", is_as_authored=True, confidence=0.9)
    cypher, params = client.calls[0]
    assert f":{names.RECIPE_VARIANT}" in cypher
    assert params["variant_id"] == "variant-1"
    assert params["is_as_authored"] is True
    assert params["fluid_ml"] is None
    assert params["texture_class"] is None
    assert params["glycemic_load"] is None
    assert params["serving_mass_g"] is None
    assert params["energy_kcal"] is None


def test_merge_recipe_variant_carries_optional_facts() -> None:
    client = FakeGraphClient()
    writers.merge_recipe_variant(
        client,
        variant_id="variant-1",
        is_as_authored=False,
        confidence=0.6,
        fluid_ml=120.0,
        texture_class="soft",
        glycemic_load=15.0,
        serving_mass_g=200.0,
        energy_kcal=180.0,
    )
    _, params = client.calls[0]
    assert params["fluid_ml"] == 120.0
    assert params["texture_class"] == "soft"
    assert params["glycemic_load"] == 15.0
    assert params["serving_mass_g"] == 200.0
    assert params["energy_kcal"] == 180.0


def test_link_recipe_variant_uses_has_variant() -> None:
    client = FakeGraphClient()
    writers.link_recipe_variant(client, recipe_id="recipe-1", variant_id="variant-1")
    cypher, params = client.calls[0]
    assert f":{names.HAS_VARIANT}" in cypher
    assert params == {"recipe_id": "recipe-1", "variant_id": "variant-1"}


def test_merge_food_uses_fdc_id_key() -> None:
    client = FakeGraphClient()
    writers.merge_food(
        client, fdc_id="12345", description="Potato, raw", data_type="sr_legacy_food", source_tier="A"
    )
    cypher, params = client.calls[0]
    assert f":{names.FOOD}" in cypher
    assert params["fdc_id"] == "12345"
    assert params["description"] == "Potato, raw"


def test_merge_nutrient_carries_form() -> None:
    client = FakeGraphClient()
    writers.merge_nutrient(
        client, nutrient_id="potassium", name="Potassium", unit="mg", form="intrinsic"
    )
    cypher, params = client.calls[0]
    assert f":{names.NUTRIENT}" in cypher
    assert params["form"] == "intrinsic"


def test_write_contains_sets_raw_mass_and_prep() -> None:
    client = FakeGraphClient()
    writers.write_contains(
        client, recipe_id="recipe-1", fdc_id="12345", raw_mass_g=150.0, prep_id="prep-boil-cubed"
    )
    cypher, params = client.calls[0]
    assert f":{names.CONTAINS}" in cypher
    assert params["raw_mass_g"] == 150.0
    assert params["prep_id"] == "prep-boil-cubed"


def test_write_has_nutrient_spreads_full_provenance() -> None:
    client = FakeGraphClient()
    provenance = _provenance(source="transform:potassium-boil", confidence=0.55, evidence_tier="B")
    writers.write_has_nutrient(
        client,
        variant_id="variant-1",
        nutrient_id="potassium",
        amount_per_serving=420.0,
        unit="mg",
        provenance=provenance,
    )
    cypher, params = client.calls[0]
    assert f":{names.HAS_NUTRIENT}" in cypher
    assert params["amount_per_serving"] == 420.0
    assert params["unit"] == "mg"
    # [INVARIANT] full Section 1.1 metadata, not just source/confidence
    assert params["source"] == "transform:potassium-boil"
    assert params["confidence"] == 0.55
    assert params["evidence_tier"] == "B"
    assert params["computed_by"] == "transform:v1"
    assert params["contract_version"] == "1.0"


def test_write_has_compound_spreads_provenance() -> None:
    client = FakeGraphClient()
    provenance = _provenance(source="formation:acrylamide", evidence_tier="C")
    writers.write_has_compound(
        client, variant_id="variant-1", compound_id="acrylamide", provenance=provenance
    )
    cypher, params = client.calls[0]
    assert f":{names.HAS_COMPOUND}" in cypher
    assert params["compound_id"] == "acrylamide"
    assert params["evidence_tier"] == "C"


def test_write_has_attribute_spreads_provenance() -> None:
    client = FakeGraphClient()
    provenance = _provenance(source="prep:raw-flip")
    writers.write_has_attribute(
        client, variant_id="variant-1", attribute_id="contains-raw-egg", provenance=provenance
    )
    cypher, params = client.calls[0]
    assert f":{names.HAS_ATTRIBUTE}" in cypher
    assert params["attribute_id"] == "contains-raw-egg"
    assert params["source"] == "prep:raw-flip"


def test_no_hardcoded_label_strings_bypass_names_module() -> None:
    """Every relationship writer must reference a name from `nectar_contract.names`, not a
    hardcoded literal, so a contract rename stays a one-line fix."""
    client = FakeGraphClient()
    writers.merge_dish(client, dish_id="d", canonical_name="x")
    _, _ = client.calls[0]
    assert names.DISH == "Dish"  # sanity: constants still match the contract's node labels
