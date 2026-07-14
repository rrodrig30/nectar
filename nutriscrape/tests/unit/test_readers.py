"""Unit tests for the recipe graph reader that feeds clustering."""
from typing import Any

from nutriscrape.graph.readers import (
    read_dish_variant_nutrients,
    read_recipe_inputs,
    read_recipes_for_materialize,
)


class _FakeReadClient:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def run(self, cypher: str, **params: Any) -> list[dict[str, Any]]:
        return self._rows


def test_read_recipe_inputs_builds_recipe_inputs():
    rows = [
        {"recipe_id": "r1", "title": "Boiled Potatoes",
         "foods": [{"fdc_id": "170026", "mass_g": 900.0, "method": "boil"},
                   {"fdc_id": "173468", "mass_g": 5.0, "method": "boil"}]},
        {"recipe_id": "r2", "title": None,
         "foods": [{"fdc_id": "169756", "mass_g": 200.0, "method": None}]},
    ]
    inputs = read_recipe_inputs(_FakeReadClient(rows))
    by_id = {i.recipe_id: i for i in inputs}
    assert by_id["r1"].foods == {"170026": 900.0, "173468": 5.0}
    assert by_id["r1"].primary_method == "boil"           # most common CONTAINS method
    assert by_id["r1"].title == "Boiled Potatoes"
    assert by_id["r2"].primary_method == "" and by_id["r2"].title == ""


def test_read_recipe_inputs_skips_recipes_without_resolved_foods():
    rows = [{"recipe_id": "empty", "title": "x",
             "foods": [{"fdc_id": None, "mass_g": None, "method": None}]}]
    assert read_recipe_inputs(_FakeReadClient(rows)) == []


def test_read_recipes_for_materialize_reconstructs_prep_and_raw_vector():
    rows = [{
        "recipe_id": "r1", "servings": 4.0,
        "foods": [{
            "fdc_id": "170026", "description": "Potatoes, raw", "mass_g": 900.0,
            "method": "boil", "cut_class": "cubed", "water_ratio": 4.0,
            "liquid_retained_frac": 0.0, "time_min": 15.0, "temp_c": 100.0,
            "raw": [{"nutrient_id": "potassium", "amount": 425.0},
                    {"nutrient_id": "sodium", "amount": 6.0}],
        }],
    }]
    recipes = read_recipes_for_materialize(_FakeReadClient(rows))
    assert len(recipes) == 1
    recipe = recipes[0]
    assert recipe.servings == 4.0 and len(recipe.ingredients) == 1
    ing = recipe.ingredients[0]
    assert ing.prep.method == "boil" and ing.prep.cut_class == "cubed"
    assert ing.prep.liquid_retained_frac == 0.0          # the as-authored drain is preserved
    assert ing.raw_per_100g == {"potassium": 425.0, "sodium": 6.0}


def test_read_recipes_for_materialize_drops_foods_without_a_raw_vector():
    rows = [{"recipe_id": "r1", "servings": 4.0,
             "foods": [{"fdc_id": "1", "description": "x", "mass_g": 10.0, "method": "boil",
                        "cut_class": None, "water_ratio": None, "liquid_retained_frac": None,
                        "time_min": None, "temp_c": None,
                        "raw": [{"nutrient_id": None, "amount": None}]}]}]
    assert read_recipes_for_materialize(_FakeReadClient(rows)) == []


def test_read_dish_variant_nutrients_groups_by_dish_and_nutrient():
    rows = [
        {"dish_id": "dish:pot", "nutrient_id": "potassium", "amounts": [378.0, 964.0]},
        {"dish_id": "dish:pot", "nutrient_id": "sodium", "amounts": [491.0, 491.0]},
        {"dish_id": "dish:rice", "nutrient_id": "potassium", "amounts": [55.0]},
    ]
    out = read_dish_variant_nutrients(_FakeReadClient(rows))
    assert out["dish:pot"]["potassium"] == [378.0, 964.0]
    assert out["dish:pot"]["sodium"] == [491.0, 491.0]
    assert out["dish:rice"]["potassium"] == [55.0]
