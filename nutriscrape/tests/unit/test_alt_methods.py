"""Unit tests for the shared alternative-method selector (nutrition/variants.alternative_methods),
the single source of truth both the transactional and bulk materialize paths use."""
from nutriscrape.nutrition.variants import MAX_EAGER_ALT_METHODS, alternative_methods


def _coverage() -> dict[str, list[str]]:
    return {
        "tuber": ["boil", "bake", "roast", "mash", "fry", "steam"],
        "leafy": ["steam", "saute", "boil"],
    }


def test_excludes_authored_and_caps_sorted():
    methods = alternative_methods({"tuber"}, {"boil"}, _coverage())
    assert "boil" not in methods                       # the as-authored method is excluded
    assert methods == sorted(methods)                  # deterministic order
    assert len(methods) <= MAX_EAGER_ALT_METHODS       # bounded eager set
    assert methods == ["bake", "fry", "mash"]          # sorted(candidates - authored)[:3]


def test_unions_across_food_classes():
    methods = alternative_methods({"tuber", "leafy"}, {"boil"}, _coverage(), cap=99)
    assert "saute" in methods and "bake" in methods    # union of both classes' coverage
    assert "boil" not in methods


def test_empty_when_no_coverage():
    assert alternative_methods({"unknown"}, {"boil"}, _coverage()) == []
