"""Unit tests for cooked-nutrition composition: the four-channel transform over FDC raw vectors."""
from nectar_contract.types import Provenance
from nutriscrape.knowledge.loaders import TransformCoeff as KBCoeff
from nutriscrape.nutrition.compose import IngredientFacts, compose_serving_vector
from nutriscrape.nutrition.transform import Preparation

_PROV = Provenance(source="retn06", confidence=0.5, evidence_tier="A",
                   computed_by="test", contract_version="1.0")
# potassium leaches from a boiled root vegetable into the cooking water
_K_LEACH = KBCoeff(food_class="root_vegetable", food_id=None, method="boil", target="potassium",
                   channel="leaching", D=None, L_base=0.30, formation_rate=None,
                   mechanism="leach", provenance=_PROV)

_POTATO_RAW = {"potassium": 425.0, "sodium": 6.0}      # per 100 g


def _potato(liquid_retained: float) -> IngredientFacts:
    prep = Preparation(method="boil", cut_class="cubed", liquid_retained_frac=liquid_retained,
                       water_ratio=4, time_min=15, temp_c=100)
    return IngredientFacts(fdc_id="170026", food_classes=("root_vegetable", "starch"),
                           mass_g=900.0, prep=prep, raw_per_100g=_POTATO_RAW)


def test_boiled_drained_potassium_leaches_below_soup():
    drained = compose_serving_vector([_potato(0.0)], [_K_LEACH], servings=4.0)
    soup = compose_serving_vector([_potato(1.0)], [_K_LEACH], servings=4.0)
    assert drained["potassium"].amount < soup["potassium"].amount      # draining discards potassium
    # soup retains essentially all of the raw potassium (425 mg/100g * 900 g / 4 servings)
    assert abs(soup["potassium"].amount - 425.0 * 9.0 / 4.0) < 1e-6


def test_nutrient_without_a_transform_passes_through():
    drained = compose_serving_vector([_potato(0.0)], [_K_LEACH], servings=4.0)
    soup = compose_serving_vector([_potato(1.0)], [_K_LEACH], servings=4.0)
    # sodium has no leaching coefficient, so it is identical whether drained or not
    assert drained["sodium"].amount == soup["sodium"].amount
    assert abs(drained["sodium"].amount - 6.0 * 9.0 / 4.0) < 1e-6


def test_cooked_confidence_reflects_the_transform_confidence():
    drained = compose_serving_vector([_potato(0.0)], [_K_LEACH], servings=4.0)
    assert drained["potassium"].confidence == 0.5          # from the leaching coefficient
    assert "retn06" in drained["potassium"].source
