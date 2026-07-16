"""Golden tests for per-serving variant facts (serving_mass_g, energy_kcal, fluid_ml).

A drained cooking liquid must not count toward the serving mass; a retained one (soup) must.
energy_kcal is the cooked energy already on the per-serving vector.
"""
from nutriscrape.nutrition.compose import (
    CookedNutrient,
    IngredientFacts,
    is_cooking_liquid,
    serving_facts,
)
from nutriscrape.nutrition.transform import Preparation


def _prep(kept: float) -> Preparation:
    return Preparation(method="boil", cut_class="cubed", liquid_retained_frac=kept,
                       water_ratio=4, time_min=15, temp_c=100)


def _ing(fdc: str, mass: float, kept: float, is_liquid: bool) -> IngredientFacts:
    return IngredientFacts(fdc_id=fdc, food_classes=(), mass_g=mass, prep=_prep(kept),
                           raw_per_100g={}, is_liquid=is_liquid)


def test_is_cooking_liquid_word_level():
    assert is_cooking_liquid("Chicken broth")
    assert is_cooking_liquid("Water, tap")
    assert is_cooking_liquid("Beef stock, home-prepared")
    assert not is_cooking_liquid("Watermelon, raw")   # not water
    assert not is_cooking_liquid("Potatoes, raw, skin")


def test_drained_water_excluded_from_serving_mass():
    # 900 g potato (solid) + 900 g water drained away, 4 servings -> ~225 g/serving, no water.
    ings = [_ing("1", 900.0, 0.0, is_liquid=False), _ing("2", 900.0, 0.0, is_liquid=True)]
    facts = serving_facts(ings, {}, servings=4.0)
    assert abs(facts.serving_mass_g - 225.0) < 1e-6
    assert facts.fluid_ml is None   # nothing retained


def test_soup_retains_broth_in_serving_mass_and_fluid():
    # 900 g potato + 900 g broth kept, 6 servings -> 300 g/serving, 150 mL fluid/serving.
    ings = [_ing("1", 900.0, 1.0, is_liquid=False), _ing("2", 900.0, 1.0, is_liquid=True)]
    facts = serving_facts(ings, {}, servings=6.0)
    assert abs(facts.serving_mass_g - 300.0) < 1e-6
    assert facts.fluid_ml is not None and abs(facts.fluid_ml - 150.0) < 1e-6


def test_energy_kcal_taken_from_cooked_vector():
    cooked = {"energy": CookedNutrient(nutrient_id="energy", amount=286.0, confidence=0.6,
                                       source="fdc")}
    facts = serving_facts([_ing("1", 400.0, 1.0, is_liquid=False)], cooked, servings=1.0)
    assert facts.energy_kcal == 286.0


def test_zero_servings_does_not_divide_by_zero():
    facts = serving_facts([_ing("1", 100.0, 1.0, is_liquid=False)], {}, servings=0.0)
    assert facts.serving_mass_g == 100.0  # treated as 1 serving
