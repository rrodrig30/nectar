"""Unit tests for RecipeNlgAdapter against the bundled sample corpus.

No network, no LLM: the bundled CSV lets `make ingest` exercise acquisition end to end offline.
These tests assert the two clinically load-bearing recipes (boiled-and-drained vs. soup, which
differ only in whether the cooking liquid is drained) are present with the expected shape.
"""
from pathlib import Path

from nutriscrape.acquisition.adapters.datasets import RecipeNlgAdapter

SAMPLE_CSV = Path(__file__).parents[2] / "config" / "samples" / "recipes_sample.csv"


def _by_title(recipes, title):
    matches = [r for r in recipes if r.title == title]
    assert len(matches) == 1, f"expected exactly one recipe titled {title!r}, found {len(matches)}"
    return matches[0]


def test_sample_csv_exists():
    assert SAMPLE_CSV.is_file()


def test_adapter_yields_all_sample_recipes():
    recipes = list(RecipeNlgAdapter(SAMPLE_CSV).recipes())
    assert 6 <= len(recipes) <= 8
    for recipe in recipes:
        assert recipe.source_id == "recipenlg"
        assert recipe.license == "non-commercial research and educational use only"
        assert recipe.recipe_id.startswith("recipenlg:")


def test_boiled_and_drained_potatoes_present():
    recipes = list(RecipeNlgAdapter(SAMPLE_CSV).recipes())
    recipe = _by_title(recipes, "Boiled and Drained Potatoes")
    assert len(recipe.ingredient_lines) == 3
    assert len(recipe.preparation_steps) == 3
    assert any("drain" in step.lower() for step in recipe.preparation_steps)
    assert recipe.servings == 4.0


def test_potato_soup_present_with_no_drain_step():
    recipes = list(RecipeNlgAdapter(SAMPLE_CSV).recipes())
    recipe = _by_title(recipes, "Potato Soup")
    assert len(recipe.ingredient_lines) == 4
    assert len(recipe.preparation_steps) == 3
    assert not any("drain" in step.lower() for step in recipe.preparation_steps)
    assert any("soup" in step.lower() for step in recipe.preparation_steps)
    assert recipe.servings == 6.0


def test_missing_servings_column_defaults_to_four():
    recipes = list(RecipeNlgAdapter(SAMPLE_CSV).recipes())
    recipe = _by_title(recipes, "Plain Rice")
    assert recipe.servings == 4.0
