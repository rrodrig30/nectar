"""schema.org structured-data extraction via recipe-scrapers, for permitted sites.

Yields the same `RawRecipe` as every other adapter, so the rest of ingest is source-agnostic. The
recipe-scrapers library reads the schema.org JSON-LD / Microdata / RDFa / OpenGraph a site already
publishes; it does not bypass bot protection, and callers must respect each site's robots.txt and
terms (config/sources.yaml). The recipe-scrapers import is lazy so this module loads without the
optional dependency, and a test injects a fake scraper. [INVARIANT] No nutrient value is produced
here: an adapter carries only the raw ingredient lines and preparation steps.
"""
from __future__ import annotations

import logging
import re
from collections.abc import Callable, Iterator, Sequence
from typing import Protocol, TypeVar
from urllib.parse import urlparse

from nutriscrape.acquisition.adapters.base import RawRecipe

logger = logging.getLogger(__name__)

_T = TypeVar("_T")
_SERVINGS_RE = re.compile(r"(\d+(?:\.\d+)?)")
_DEFAULT_SERVINGS = 4.0
_NO_INGREDIENTS: list[str] = []   # typed empty default for _safe(scraped.ingredients, ...)
# Recipe content licenses vary per site; recipe-scrapers (MIT) only reads published structured data.
_LICENSE = "per-site terms; extracted from published schema.org structured data"


class ScrapedRecipe(Protocol):
    """The subset of the recipe-scrapers scraper API this adapter reads."""

    def title(self) -> str:
        ...

    def ingredients(self) -> list[str]:
        ...

    def instructions(self) -> str:
        ...

    def yields(self) -> str:
        ...


Scraper = Callable[[str], ScrapedRecipe]


def _default_scraper(url: str) -> ScrapedRecipe:
    """Scrape one URL with recipe-scrapers. Lazy import so this module loads without the dependency."""
    try:
        from recipe_scrapers import scrape_me
    except ImportError as exc:
        raise RuntimeError(
            "recipe-scrapers is not installed; add it (pip install recipe-scrapers) to scrape "
            "schema.org sites, or point the corpus at a dataset CSV instead."
        ) from exc
    return scrape_me(url)  # type: ignore[no-any-return]


def _safe(getter: Callable[[], _T], default: _T) -> _T:
    """Call a scraper accessor, returning `default` when the site omits that field. recipe-scrapers
    raises for a missing schema.org field rather than returning None."""
    try:
        return getter()
    except Exception:
        return default


def _parse_servings(text: str) -> float:
    match = _SERVINGS_RE.search(text or "")
    return float(match.group(1)) if match else _DEFAULT_SERVINGS


def _to_raw_recipe(url: str, scraped: ScrapedRecipe) -> RawRecipe:
    title = _safe(scraped.title, "") or url
    ingredients = [line for line in _safe(scraped.ingredients, _NO_INGREDIENTS) if line and line.strip()]
    steps = [step.strip() for step in _safe(scraped.instructions, "").split("\n") if step.strip()]
    host = urlparse(url).netloc or "unknown"
    return RawRecipe(
        recipe_id=f"schemaorg:{url}",
        title=title,
        source_id=host,
        license=_LICENSE,
        servings=_parse_servings(_safe(scraped.yields, "")),
        ingredient_lines=tuple(ingredients),
        preparation_steps=tuple(steps),
    )


class SchemaOrgAdapter:
    """A SourceAdapter over a list of recipe URLs, extracting each site's schema.org data via
    recipe-scrapers. A URL that fails to scrape (network error, no structured data, unsupported
    site) or that carries no ingredients is logged and skipped, so one bad URL never aborts the
    batch. See DATA_CONTRACT.md Section 1.1, nutriscrape SDD Section 3.1."""

    def __init__(self, urls: Sequence[str], *, scraper: Scraper | None = None) -> None:
        self._urls = list(urls)
        self._scraper = scraper if scraper is not None else _default_scraper

    def recipes(self) -> Iterator[RawRecipe]:
        for url in self._urls:
            try:
                scraped = self._scraper(url)
            except Exception:
                logger.warning("acquisition: failed to scrape %s; skipping", url)
                continue
            recipe = _to_raw_recipe(url, scraped)
            if not recipe.ingredient_lines:
                logger.warning("acquisition: %s carried no ingredients; skipping", url)
                continue
            yield recipe


__all__ = ["SchemaOrgAdapter", "ScrapedRecipe", "Scraper"]
