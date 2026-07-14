"""Clinical golden tests for conflict resolution and suitability. [INVARIANT] Must pass in CI."""
from nectar.scoring.suitability import Constraint, sub_score, condition_score, CONTRAINDICATED
from nectar.scoring.conflicts import resolve


def test_potassium_conflict_ckd_htn_resolves_to_restriction():
    ckd_k = Constraint(nutrient="potassium", type="restrict", max_per_serving=700,
                       hard_limit=1000, safety_critical=True, guideline_id="kdoqi-potassium")
    htn_k = Constraint(nutrient="potassium", type="target", goal=1500,
                       guideline_id="dash-potassium")
    resolved, conflicts = resolve([ckd_k, htn_k])
    assert resolved["potassium"].type == "restrict", "restriction must win over target"
    assert len(conflicts) == 1 and conflicts[0].kind == "direction"
    assert "safety" in conflicts[0].winning_rule.lower()


def test_never_averages_opposing_constraints():
    a = Constraint(nutrient="potassium", type="restrict", max_per_serving=700, safety_critical=True)
    b = Constraint(nutrient="potassium", type="target", goal=1500)
    resolved, _ = resolve([a, b])
    # resolved value is the restriction ceiling, not a midpoint
    assert resolved["potassium"].max_per_serving == 700


def test_hard_limit_breach_is_contraindication_not_low_score():
    c = Constraint(nutrient="potassium", type="restrict", max_per_serving=700, hard_limit=1000)
    assert sub_score(1200, c) == CONTRAINDICATED
    res = condition_score({"potassium": 1200}, [c])
    assert res.contraindicated and res.score == 0.0


def test_agreeing_restrictions_take_the_tighter():
    ckd_na = Constraint(nutrient="sodium", type="restrict", max_per_serving=600)
    htn_na = Constraint(nutrient="sodium", type="restrict", max_per_serving=500)
    resolved, conflicts = resolve([ckd_na, htn_na])
    assert resolved["sodium"].max_per_serving == 500
    assert not conflicts  # agreement, no direction conflict
