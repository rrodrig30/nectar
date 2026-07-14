"""SourceAdapter protocol yielding a uniform RawRecipe.

Every acquisition adapter (bulk dataset dump, schema.org site scrape, or the bundled sample
corpus) normalizes to this one shape so the rest of the ingest pipeline (extraction, resolution,
nutrition) never needs to know which source a recipe came from. License and provenance travel
with each record per DATA_CONTRACT.md Section 1.1; no nutrient value is ever carried here, only
the raw ingredient lines and preparation steps that the parsers (model-driven or deterministic)
turn into structure.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator, Protocol, runtime_checkable


@dataclass(frozen=True)
class RawRecipe:
    """One recipe as acquired from a source, before any extraction or parsing.

    `ingredient_lines` and `preparation_steps` are raw natural-language strings. Nothing here is
    a nutrient value; composition is resolved downstream from `food` via FDC, never asserted by
    an adapter.
    """

    recipe_id: str
    title: str
    source_id: str
    license: str
    servings: float
    ingredient_lines: tuple[str, ...]
    preparation_steps: tuple[str, ...]


@runtime_checkable
class SourceAdapter(Protocol):
    """A source of raw recipes. Implementations own their own I/O (file, HTTP, scraper)."""

    def recipes(self) -> Iterator[RawRecipe]:
        """Yield one `RawRecipe` per recipe found in this source, in source order."""
        ...


__all__ = ["RawRecipe", "SourceAdapter"]
