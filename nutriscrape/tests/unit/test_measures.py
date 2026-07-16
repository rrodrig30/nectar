"""Unit tests for ingredient quantity -> gram resolution (the Phase 2 mass-basis fix)."""
import math

from nutriscrape.nutrition.measures import MeasureTable, resolve_mass_g

# A small explicit table so the tests do not depend on the illustrative config values.
_TABLE = MeasureTable(
    density_g_per_ml={"oil": 0.92, "flour": 0.53, "milk": 1.03},
    count_grams={"egg": 50.0, "clove": 3.0, "onion": 110.0},
    default_density=1.0,
    default_count_g=100.0,
)


def _close(a: float, b: float, tol: float = 0.5) -> bool:
    return math.isclose(a, b, abs_tol=tol)


def test_mass_unit_converts_directly():
    assert _close(resolve_mass_g(8, "oz", "Butter, salted", _TABLE), 226.8)
    assert resolve_mass_g(250, "g", "anything", _TABLE) == 250.0


def test_volume_unit_uses_food_density():
    # 1 cup = 236.588 mL; oil density 0.92 -> ~217.7 g
    assert _close(resolve_mass_g(1, "cup", "Oil, olive", _TABLE), 236.588 * 0.92)
    # 2 tbsp flour = 29.5735 mL * 0.53 -> ~15.67 g
    assert _close(resolve_mass_g(2, "tbsp", "Flour, wheat", _TABLE), 29.5735 * 0.53)


def test_volume_without_known_density_uses_default():
    # water-like default 1.0 g/mL
    assert _close(resolve_mass_g(1, "cup", "Water, tap", _TABLE), 236.588)


def test_count_uses_portion_weight_not_grams():
    # The bug this fixes: "2 eggs" must be ~100 g, not 2 g.
    assert resolve_mass_g(2, None, "Egg, whole, raw", _TABLE) == 100.0
    assert resolve_mass_g(3, None, "Garlic, raw", _TABLE) == 300.0  # no 'garlic' key -> default 100
    assert resolve_mass_g(3, "clove", "Garlic, raw", _TABLE) == 9.0  # 'clove' unit -> count path


def test_unitless_unknown_food_uses_default_portion():
    assert resolve_mass_g(2, None, "Mystery ingredient", _TABLE) == 200.0


def test_longest_keyword_wins():
    table = MeasureTable(count_grams={"onion": 110.0, "green onion": 15.0}, default_count_g=100.0)
    # substring match is literal, so the description must contain the phrase "green onion"
    assert resolve_mass_g(1, None, "Green onions, raw", table) == 15.0


def test_none_quantity_is_zero_mass():
    # "salt to taste" (no quantity) contributes zero mass rather than a spurious default.
    assert resolve_mass_g(None, None, "Salt, table", _TABLE) == 0.0


def test_unrecognized_unit_falls_through_to_count():
    # A weird unit does not drop the ingredient; it uses the portion path.
    assert resolve_mass_g(2, "pinch", "Egg, whole", _TABLE) == 100.0
