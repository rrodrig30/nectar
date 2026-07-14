"""Unit tests for the schema.org acquisition adapter and the ingest source selection."""
from nutriscrape.acquisition.adapters.structured import SchemaOrgAdapter
from nutriscrape.common.config import default_config_dir
from nutriscrape.pipeline import _acquire


class _FakeScraped:
    """Stands in for a recipe-scrapers scraper object (the ScrapedRecipe protocol)."""

    def __init__(self, title: str, ingredients: list[str], instructions: str, yields: str) -> None:
        self._title = title
        self._ingredients = ingredients
        self._instructions = instructions
        self._yields = yields

    def title(self) -> str:
        return self._title

    def ingredients(self) -> list[str]:
        return self._ingredients

    def instructions(self) -> str:
        return self._instructions

    def yields(self) -> str:
        return self._yields


def test_schemaorg_adapter_extracts_raw_recipes():
    scraped = {
        "https://example.com/potato-soup": _FakeScraped(
            "Potato Soup",
            ["2 pounds potatoes, cubed", "4 cups broth"],
            "Boil the potatoes.\nSimmer into a soup.",
            "4 servings",
        )
    }
    adapter = SchemaOrgAdapter(list(scraped), scraper=lambda url: scraped[url])
    recipes = list(adapter.recipes())
    assert len(recipes) == 1
    recipe = recipes[0]
    assert recipe.title == "Potato Soup"
    assert recipe.ingredient_lines == ("2 pounds potatoes, cubed", "4 cups broth")
    assert recipe.preparation_steps == ("Boil the potatoes.", "Simmer into a soup.")
    assert recipe.servings == 4.0
    assert recipe.source_id == "example.com"
    assert recipe.recipe_id == "schemaorg:https://example.com/potato-soup"


def test_schemaorg_adapter_skips_unscrapeable_and_empty():
    def scraper(url: str) -> _FakeScraped:
        if "bad" in url:
            raise ValueError("no structured data on this page")
        return _FakeScraped("Empty", [], "", "")

    adapter = SchemaOrgAdapter(["https://x.com/bad", "https://x.com/empty"], scraper=scraper)
    assert list(adapter.recipes()) == []   # one URL raises, one carries no ingredients


def test_servings_defaults_when_yield_has_no_number():
    scraped = _FakeScraped("R", ["1 egg"], "Cook it.", "some servings")
    adapter = SchemaOrgAdapter(["https://x.com/r"], scraper=lambda url: scraped)
    assert list(adapter.recipes())[0].servings == 4.0


def test_acquire_reads_a_csv_dataset():
    recipes = _acquire(str(default_config_dir() / "samples" / "recipes_sample.csv"))
    assert len(recipes) >= 6
    assert any("Potato Soup" in recipe.title for recipe in recipes)


def test_acquire_routes_a_url_file_to_schemaorg(tmp_path):
    corpus = tmp_path / "corpus.txt"
    corpus.write_text("# a comment line\n\n", encoding="utf-8")   # comments/blanks only, no URLs
    assert _acquire(str(corpus)) == []                           # routed to SchemaOrgAdapter, no scrape
