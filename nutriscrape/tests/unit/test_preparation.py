"""Unit tests for the preparation-step parser's pure helper. [CRITICAL PATH]

`resolve_liquid_retained` is the single, model-free mapping that flips a leached nutrient
(potassium, above all) between lost and retained in the four-channel transform. These are
the drain/no-drain golden cases: no model, no network, so this regression guard always runs.
"""
from nutriscrape.extraction.preparation import resolve_liquid_retained


def test_drain_discards_the_liquid():
    assert resolve_liquid_retained("Drain the potatoes.") == 0.0


def test_strain_discards_the_liquid():
    assert resolve_liquid_retained("Strain the pasta well.") == 0.0


def test_soup_retains_the_liquid():
    assert resolve_liquid_retained("Simmer into a soup and serve.") == 1.0


def test_stew_retains_the_liquid():
    assert resolve_liquid_retained("Cook low and slow as a stew.") == 1.0


def test_default_retains_the_liquid():
    # Boiling alone, with no later drain step, keeps the liquid in the dish by default.
    assert resolve_liquid_retained("Boil the potatoes for 15 minutes.") == 1.0


def test_case_insensitive_drain_match():
    assert resolve_liquid_retained("DRAIN and set aside.") == 0.0
