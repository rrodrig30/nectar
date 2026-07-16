"""Clinical golden tests for condition/medication food-avoidance rules (Phase 1). [INVARIANT] CI.

Covers the transplant scenario end to end: an immunosuppression condition and a CYP3A4-substrate
medication produce absolute `avoid` constraints, and those exclude a variant carrying the matching
FoodAttribute at Stage 1 (a contraindication, never a low score). Oxalate stones exclude
high-oxalate foods. Derivation reads the real config/conditions and config/interactions files.
"""
from nectar.abstraction.derive import rules_for_conditions, rules_for_medications
from nectar.engine.constraints import VariantFacts, assemble
from nectar.engine.evaluate import evaluate_variant


def _avoid_targets(constraints):
    return {c.target for c in constraints if c.direction == "avoid"}


def test_transplant_excludes_raw_animal_protein():
    cons = rules_for_conditions(["transplant"])
    avoid = _avoid_targets(cons)
    assert {"raw_animal_protein", "unpasteurized_dairy", "raw_sprouts"} <= avoid
    # Each food-safety exclusion is absolute (Stage 1), not a graded score.
    raw = [c for c in cons if c.target == "raw_animal_protein"][0]
    assert raw.direction == "avoid" and raw.severity == "absolute"


def test_transplant_still_carries_nutrient_limits():
    cons = rules_for_conditions(["transplant"])
    potassium = [c for c in cons if c.target == "potassium"]
    assert potassium and potassium[0].direction == "limit"
    # potassium is safety_critical in the config -> absolute severity
    assert potassium[0].severity == "absolute"


def test_tacrolimus_avoids_grapefruit_furanocoumarin():
    cons = rules_for_medications(["tacrolimus"])
    fc = [c for c in cons if c.target == "furanocoumarin"]
    assert fc, "tacrolimus should impose a furanocoumarin avoidance"
    assert fc[0].direction == "avoid" and fc[0].severity == "absolute"
    assert "CYP3A4" in fc[0].formula
    assert fc[0].guideline_id == "ast-cyp3a4"


def test_oxalate_stones_excludes_high_oxalate_and_limits_sodium():
    cons = rules_for_conditions(["oxalate_stones"])
    assert "high_oxalate" in _avoid_targets(cons)
    sodium = [c for c in cons if c.target == "sodium"]
    assert sodium and sodium[0].direction == "limit"


def test_raw_variant_contraindicated_but_cooked_admissible():
    # Derivation -> engine: the transplant exclusions become Stage 1 hard excludes.
    avoid = _avoid_targets(rules_for_conditions(["transplant"]))
    rc = assemble(nutrient_constraints=[], hard_excludes=avoid)

    raw = VariantFacts("v_raw", "d1", nutrients={}, attributes=frozenset({"raw_animal_protein"}))
    cooked = VariantFacts("v_cooked", "d1", nutrients={}, attributes=frozenset())

    raw_eval = evaluate_variant(raw, rc)
    assert raw_eval.contraindicated is True and raw_eval.admissible is False
    assert any("raw_animal_protein" in r for r in raw_eval.reasons)
    assert evaluate_variant(cooked, rc).admissible is True


def test_combined_transplant_meds_and_stones_exclude_grapefruit_dish():
    # A transplant patient on tacrolimus with oxalate stones: the union of exclusions filters a
    # dish that is raw, or contains grapefruit, or is high-oxalate.
    excludes = _avoid_targets(rules_for_conditions(["transplant"]))
    excludes |= _avoid_targets(rules_for_conditions(["oxalate_stones"]))
    excludes |= _avoid_targets(rules_for_medications(["tacrolimus"]))
    rc = assemble(nutrient_constraints=[], hard_excludes=excludes)

    grapefruit_dish = VariantFacts("v_gf", "d2", nutrients={}, attributes=frozenset({"furanocoumarin"}))
    spinach_dish = VariantFacts("v_sp", "d3", nutrients={}, attributes=frozenset({"high_oxalate"}))
    plain_dish = VariantFacts("v_ok", "d4", nutrients={}, attributes=frozenset())

    assert evaluate_variant(grapefruit_dish, rc).contraindicated is True
    assert evaluate_variant(spinach_dish, rc).contraindicated is True
    assert evaluate_variant(plain_dish, rc).admissible is True
