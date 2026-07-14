"""Unit tests for RecipeNlgAdapter against the bundled sample corpus.

No network, no LLM: the bundled CSV lets `make ingest` exercise acquisition end to end offline.
These tests assert the two clinically load-bearing recipes (boiled-and-drained vs. soup, which
differ only in whether the cooking liquid is drained) are present with the expected shape.
"""
import csv
import json
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


def test_parses_real_recipenlg_full_dataset_format(tmp_path):
    """The real RecipeNLG `full_dataset.csv` (the ~2M-recipe export) has a leading unnamed index
    column and a trailing NER column and no `servings`: header `,title,ingredients,directions,link,
    source,NER`, with ingredients/directions as JSON arrays. The adapter keys by column name, so the
    extra index/NER columns are ignored and servings defaults to 4.0. This is the exact shape the
    full-corpus run at NUTRISCRAPE_CORPUS ingests."""
    path = tmp_path / "recipes_full.csv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["", "title", "ingredients", "directions", "link", "source", "NER"])
        writer.writerow([
            "0", "No-Bake Nut Cookies",
            json.dumps(["1 c. firmly packed brown sugar", "1/2 c. evaporated milk", "1 c. nuts"]),
            json.dumps(["In a heavy saucepan, mix brown sugar and milk.", "Fold in the nuts."]),
            "www.cookbooks.com/Recipe-Details.aspx?id=44874", "Gathered",
            json.dumps(["brown sugar", "milk", "nuts"]),
        ])
        writer.writerow([
            "1", "Boiled and Drained Potatoes",
            json.dumps(["2 pounds potatoes, cubed", "1 teaspoon salt"]),
            json.dumps(["Boil the potatoes for 15 minutes.", "Drain well."]),
            "www.example.invalid/boiled", "Recipes1M",
            json.dumps(["potatoes", "salt"]),
        ])

    recipes = list(RecipeNlgAdapter(path).recipes())
    assert len(recipes) == 2

    cookies = _by_title(recipes, "No-Bake Nut Cookies")
    assert cookies.recipe_id == "recipenlg:0"
    assert cookies.source_id == "recipenlg"
    assert cookies.ingredient_lines[0] == "1 c. firmly packed brown sugar"
    assert len(cookies.ingredient_lines) == 3
    assert len(cookies.preparation_steps) == 2
    assert cookies.servings == 4.0  # no servings column in the real export

    potatoes = _by_title(recipes, "Boiled and Drained Potatoes")
    assert any("drain" in step.lower() for step in potatoes.preparation_steps)
