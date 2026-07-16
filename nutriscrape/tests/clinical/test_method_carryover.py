"""Golden tests: a bare cooking-method step carries to the in-pot ingredients, and the expanded
mineral-leaching coefficients cook the tracked renal minerals. Without method carryover no
transform fires (the method lives in a step that does not repeat the food name)."""
from nutriscrape.acquisition.parse import basic_preparation


def _prep_for(preps, ref):
    for p in preps:
        if ref in p.applies_to:
            return p
    raise AssertionError(f"no preparation for {ref!r}")


def test_boil_step_carries_to_potato_named_earlier():
    steps = [
        "Place the cubed potatoes in a pot with 4 cups salted water.",
        "Boil for 15 minutes until fork tender.",
        "Drain the potatoes well.",
    ]
    preps = basic_preparation(steps, ["potatoes"])
    potato = _prep_for(preps, "potatoes")
    assert potato.method == "boil", "the bare 'Boil' step must reach the potato added earlier"
    assert potato.liquid_retained_frac == 0.0, "drain still zeroes the retained fraction"


def test_soup_carries_boil_but_keeps_liquid():
    steps = [
        "Place the cubed potatoes in a pot with the broth.",
        "Boil for 20 minutes until tender.",
        "Stir in the milk and season with salt.",
    ]
    preps = basic_preparation(steps, ["potatoes"])
    potato = _prep_for(preps, "potatoes")
    assert potato.method == "boil"
    assert potato.liquid_retained_frac == 1.0, "no drain: soup keeps the leached minerals"


def test_carryover_does_not_override_a_known_method():
    # Two ingredients, so the single-ingredient fallback does not fire and carryover is exercised.
    steps = [
        "Saute the onions and carrots until soft.",
        "Boil for 10 minutes.",  # bare method; must not overwrite the established saute
    ]
    preps = basic_preparation(steps, ["onions", "carrots"])
    assert _prep_for(preps, "onions").method == "saute"
    assert _prep_for(preps, "carrots").method == "saute"


def test_bare_method_with_no_prior_ingredient_is_ignored():
    # Nothing in the pot yet (and >1 ingredient, so no single-ingredient fallback): a leading bare
    # "Boil" has nothing to attach to.
    preps = basic_preparation(["Boil some water."], ["potatoes", "salt"])
    assert all("potatoes" not in p.applies_to for p in preps)
