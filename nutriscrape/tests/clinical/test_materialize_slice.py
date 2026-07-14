"""End-to-end clinical golden: materialize generates alternative preparation variants. [INVARIANT].

Drives the materialize stage over a fake graph that serves one ingested boiled-and-drained potato
recipe (with its persisted as-authored prep and food raw vectors) and captures writes. It asserts
that alternative-method variants (baked, mashed, roasted) are written with is_as_authored=False and
their own cooked HAS_NUTRIENT vectors, and that a non-draining method (bake) RETAINS the potassium
that boiling-and-draining leaches away. Ranking those versions within a dish is NECTAR's job.
See PDD Section 6, SDD Section 8, DATA_CONTRACT Section 3.1.
"""
from typing import Any

from nutriscrape.pipeline import _run_materialize_with_client

_ROWS: list[dict[str, Any]] = [{
    "recipe_id": "boiled_potatoes", "servings": 4.0,
    "foods": [
        {"fdc_id": "170026", "description": "Potatoes, flesh and skin, raw", "mass_g": 900.0,
         "method": "boil", "cut_class": "cubed", "water_ratio": 4.0, "liquid_retained_frac": 0.0,
         "time_min": 15.0, "temp_c": 100.0,
         "raw": [{"nutrient_id": "potassium", "amount": 425.0},
                 {"nutrient_id": "sodium", "amount": 6.0}]},
        {"fdc_id": "173468", "description": "Salt, table", "mass_g": 5.0,
         "method": "boil", "cut_class": "whole", "water_ratio": None, "liquid_retained_frac": 1.0,
         "time_min": None, "temp_c": None,
         "raw": [{"nutrient_id": "sodium", "amount": 38758.0}]},
    ],
}]


class _FakeGraph:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows
        self.writes: list[tuple[str, dict[str, Any]]] = []

    def run(self, cypher: str, **params: Any) -> list[dict[str, Any]]:
        return self._rows

    def run_write(self, cypher: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        self.writes.append((cypher, params))
        return []


def _variants(client: _FakeGraph) -> dict[str, bool]:
    """variant_id -> is_as_authored, from the merge_recipe_variant writes."""
    return {p["variant_id"]: p["is_as_authored"]
            for c, p in client.writes if "is_as_authored" in p}


def _potassium(client: _FakeGraph, variant_id: str) -> float:
    for _c, p in client.writes:
        if (p.get("variant_id") == variant_id and p.get("nutrient_id") == "potassium"
                and "amount_per_serving" in p):
            return float(p["amount_per_serving"])
    raise AssertionError(f"no potassium written for {variant_id}")


def test_materialize_writes_alternative_variants():
    client = _FakeGraph(_ROWS)
    n = _run_materialize_with_client(client)
    assert n >= 1
    variants = _variants(client)
    # all materialized variants are alternatives, never the as-authored one (ingest owns that)
    assert variants and all(is_authored is False for is_authored in variants.values())
    # the bounded, culinarily-valid alternative set (config/method_coverage.yaml), minus boil
    assert "boiled_potatoes:variant:bake" in variants
    assert "boiled_potatoes:variant:boil" not in variants        # as-authored method excluded


def test_baking_retains_potassium_that_draining_leaches():
    client = _FakeGraph(_ROWS)
    _run_materialize_with_client(client)
    baked_k = _potassium(client, "boiled_potatoes:variant:bake")
    # bake has no leaching coefficient, so potassium passes through: 425 mg/100g * 900 g / 4 servings
    assert baked_k > 900.0                                        # retained, unlike boil-and-drain (~378)
