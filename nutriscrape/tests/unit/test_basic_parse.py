"""Unit tests for the deterministic, model-free ingredient and preparation parsers.

`basic_preparation` owns the same drain/no-drain golden behavior as the model-driven parser
(tests/unit/test_preparation.py), exercised here with no model and no network.
"""
from nutriscrape.acquisition.parse import basic_preparation, parse_ingredient_basic
from nutriscrape.common.units import is_mass_unit


def test_parse_ingredient_basic_quantity_unit_and_food():
    result = parse_ingredient_basic("2 pounds potatoes, peeled and cubed")
    assert result.quantity == 2.0
    assert result.unit is not None
    assert is_mass_unit(result.unit)
    assert "potato" in result.food.lower()
    assert result.qualifiers == ["peeled", "cubed"]
    assert result.parse_confidence < 0.9  # lower fidelity than an LLM parse


def test_parse_ingredient_basic_unitless_food():
    result = parse_ingredient_basic("3 eggs")
    assert result.quantity == 3.0
    assert "egg" in result.food.lower()


def test_parse_ingredient_basic_simple_fraction():
    result = parse_ingredient_basic("1/2 teaspoon salt")
    assert result.quantity == 0.5
    assert result.food.lower() == "salt"


def test_basic_preparation_drain_after_boil_zeroes_retained_fraction():
    steps = ["Boil the cubed potatoes 15 min", "Season", "Drain the potatoes"]
    result = basic_preparation(steps, ["potatoes"])
    assert len(result) == 1
    prep = result[0]
    assert prep.liquid_retained_frac == 0.0
    assert prep.cut_class == "cubed"


def test_basic_preparation_soup_retains_liquid():
    steps = ["Boil the cubed potatoes in broth", "Stir into a soup"]
    result = basic_preparation(steps, ["potatoes"])
    assert len(result) == 1
    assert result[0].liquid_retained_frac == 1.0


def test_basic_preparation_applies_to_multiple_ingredients():
    steps = ["Bake the chicken and carrots together for 25 min"]
    result = basic_preparation(steps, ["chicken", "carrots"])
    refs = {prep.applies_to[0] for prep in result}
    assert refs == {"chicken", "carrots"}
    for prep in result:
        assert prep.method == "bake"
