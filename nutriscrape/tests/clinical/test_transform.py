"""Clinical golden tests for the four-channel transform. [INVARIANT] Must always pass in CI.

Guards the potassium/potato behavior that a naive single retention factor gets wrong.
"""
from nutriscrape.nutrition.transform import TransformCoeff, Preparation, cooked_amount

# potassium leaches into water but does not degrade (it is an element)
POTASSIUM_BOIL = [TransformCoeff(target="potassium", channel="leaching", L_base=0.30,
                                 source="retn06", confidence=0.5, evidence_tier="A")]
RAW_K = 600.0  # mg in the raw portion


def test_boiled_and_drained_loses_potassium():
    prep = Preparation(method="boil", cut_class="cubed", liquid_retained_frac=0.0,
                       water_ratio=4, time_min=15, temp_c=100)
    out = cooked_amount(RAW_K, POTASSIUM_BOIL, prep)
    assert out.value < RAW_K, "draining must remove leached potassium"


def test_soup_retains_potassium():
    prep = Preparation(method="boil", cut_class="cubed", liquid_retained_frac=1.0,
                       water_ratio=4, time_min=15, temp_c=100)
    out = cooked_amount(RAW_K, POTASSIUM_BOIL, prep)
    assert abs(out.value - RAW_K) < 1e-6, "kept liquid returns potassium to the dish"


def test_cubed_leaches_more_than_whole():
    common = dict(method="boil", liquid_retained_frac=0.0, water_ratio=4, time_min=15, temp_c=100)
    whole = cooked_amount(RAW_K, POTASSIUM_BOIL, Preparation(cut_class="whole", **common))
    cubed = cooked_amount(RAW_K, POTASSIUM_BOIL, Preparation(cut_class="cubed", **common))
    assert cubed.value < whole.value, "more surface area leaches more potassium"


def test_formation_channel_adds_a_compound():
    coeffs = [TransformCoeff(target="acrylamide", channel="formation", formation_rate=1.0,
                             source="literature", confidence=0.4, evidence_tier="B")]
    prep = Preparation(method="high_heat_fry", cut_class="diced", liquid_retained_frac=1.0,
                       time_min=20, temp_c=180)
    out = cooked_amount(0.0, coeffs, prep)
    assert out.value > 0.0, "method creates a compound absent in the raw food"
