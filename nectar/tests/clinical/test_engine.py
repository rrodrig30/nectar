"""Clinical golden tests for the two-stage engine, remediation safety, and the confirmed gate.
[INVARIANT] Must always pass in CI. See nectar/docs/PDD.md Section 12.
"""
import pytest

from nectar.abstraction.derive import DerivedConstraint
from nectar.engine.constraints import (
    UnconfirmedConstraintError,
    VariantFacts,
    assemble,
    require_confirmed,
)
from nectar.engine.evaluate import evaluate, evaluate_variant
from nectar.engine.rank import gaps, rank_across_dishes
from nectar.engine.recommend import recommend
from nectar.engine.remediate import InterventionProposal, remediate_dish
from nectar.scoring.suitability import Constraint

K = Constraint(nutrient="potassium", type="restrict", max_per_serving=700, hard_limit=1000,
               safety_critical=True, guideline_id="kdoqi-potassium")
NA = Constraint(nutrient="sodium", type="restrict", max_per_serving=600, hard_limit=800,
                guideline_id="kdoqi-sodium")


def test_no_unconfirmed_constraint_reaches_engine():
    derived = [DerivedConstraint(source_signal="serum K 5.4", direction="limit",
                                 target="potassium", severity="strong", confirmed=False)]
    with pytest.raises(UnconfirmedConstraintError):
        require_confirmed(derived)
    with pytest.raises(UnconfirmedConstraintError):
        recommend(derived, [], assemble([K]))


def test_stage1_excludes_allergen_before_scoring():
    rc = assemble([K], hard_excludes={"peanut"})
    v = VariantFacts(variant_id="v1", dish_id="d1", nutrients={"potassium": 300},
                     attributes=frozenset({"peanut"}))
    ev = evaluate_variant(v, rc)
    assert not ev.admissible and any("peanut" in r for r in ev.reasons)


def test_hard_limit_breach_excludes_dish_from_ranking():
    rc = assemble([K])
    bad = VariantFacts("v1", "d1", {"potassium": 1200})     # over the hard limit
    good = VariantFacts("v2", "d2", {"potassium": 500})
    rankings = rank_across_dishes(evaluate([bad, good], rc))
    assert rankings[0].dish_id == "d2" and rankings[0].best is not None
    assert "d1" in gaps(rankings)                           # no admissible version


def test_remediation_that_fixes_potassium_but_breaks_sodium_is_flagged():
    rc = assemble([K, NA])
    base = VariantFacts("v1", "d1", {"potassium": 1200, "sodium": 500})
    assert not evaluate_variant(base, rc).admissible        # contraindicated on potassium

    def leach_but_salt(v: VariantFacts) -> VariantFacts:
        n = dict(v.nutrients)
        n["potassium"] = 600      # boil-and-drain leaches potassium under the ceiling
        n["sodium"] = 900         # ... but a salty broth pushes sodium over its hard limit
        return VariantFacts(v.variant_id, v.dish_id, n, v.attributes, v.method)

    props = [InterventionProposal("leaching", "potassium", leach_but_salt, "boil and drain")]
    r = remediate_dish(base, props, rc)[0]
    assert not r.admissible, "fixing potassium while breaching sodium must not be admissible"
    assert "sodium" in r.broke                              # [INVARIANT] the break is surfaced


def test_remediation_that_fixes_the_target_cleanly_is_admissible():
    rc = assemble([K, NA])
    base = VariantFacts("v1", "d1", {"potassium": 1200, "sodium": 500})

    def leach_clean(v: VariantFacts) -> VariantFacts:
        n = dict(v.nutrients)
        n["potassium"] = 600
        return VariantFacts(v.variant_id, v.dish_id, n, v.attributes, v.method)

    props = [InterventionProposal("leaching", "potassium", leach_clean, "boil and drain")]
    r = remediate_dish(base, props, rc)[0]
    assert r.admissible and not r.broke
