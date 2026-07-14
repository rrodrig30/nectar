"""Clinical golden test for the critical preparation-parse linkage. [INVARIANT] Must pass in CI.

The spec names this exact case: a "drain" step several steps after "boil" must still set
liquid_retained_frac = 0.0 for the ingredient it acts on, because that fraction flips potassium
between leached-and-lost and retained in the four-channel transform. This exercises the multi-step
`parse_preparation` linkage (later step wins), not just the single-step keyword helper.
See nutriscrape/docs/PDD.md Section 9, SDD Section 3.2.
"""
from nutriscrape.extraction.models import Confidence, ExtractionResult
from nutriscrape.extraction.preparation import parse_preparation, resolve_liquid_retained


class _FakePrepModel:
    """A stand-in ModelClient: returns structural fields from the step text, never a nutrient number.
    Matches ModelClient.extract(prompt, schema) -> ExtractionResult."""

    def extract(self, prompt: str, schema: dict[str, str]) -> ExtractionResult:
        low = prompt.lower()
        fields: dict[str, object] = {"applies_to": ["potato"]}
        if "boil" in low:
            fields.update(method="boil", cut_class="cubed", water_ratio=4, time_min=15, temp_c=100)
        elif "drain" in low:
            fields.update(method="drain")           # a bare drain step: no cut, no timing stated
        else:
            fields.update(method="season")
        return ExtractionResult(fields=fields, confidence=Confidence(overall=0.9, per_field={}),
                                escalated=False, source_tier=1)


def test_drain_three_steps_after_boil_zeroes_retained_liquid():
    steps = [
        "Boil the cubed potato in 4 cups water for 15 minutes",
        "Season the pot to taste",
        "Add a pat of butter",
        "Drain the potato well",                    # drain arrives three steps after boil
    ]
    preps = parse_preparation(steps, ingredient_refs=["potato"], client=_FakePrepModel())
    assert len(preps) == 1
    potato = preps[0]
    assert potato.liquid_retained_frac == 0.0       # [INVARIANT] draining discards leached potassium
    assert potato.cut_class == "cubed"              # earlier step's geometry is not erased by the drain
    assert potato.time_min == 15.0                  # nor its timing


def test_soup_retains_liquid_without_a_drain_step():
    steps = ["Boil the cubed potato in water", "Serve as a potato soup"]
    preps = parse_preparation(steps, ingredient_refs=["potato"], client=_FakePrepModel())
    assert preps[0].liquid_retained_frac == 1.0     # kept liquid returns potassium to the dish


def test_single_step_keyword_helper_still_holds():
    assert resolve_liquid_retained("drain and rinse") == 0.0
    assert resolve_liquid_retained("simmer into a stew") == 1.0
