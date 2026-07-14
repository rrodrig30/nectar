"""Adapters for RecipeNLG / Recipe1M+ / Food.com bulk dumps.

RecipeNLG is the platform's primary bulk corpus (config/sources.yaml): "non-commercial research
and educational use only". This module reads a RecipeNLG-shaped CSV and yields `RawRecipe`
records; it does not parse ingredient lines or preparation steps into structure (that is
`acquisition/parse.py` or `extraction/`), and it never computes or asserts a nutrient value.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Iterator

from nutriscrape.acquisition.adapters.base import RawRecipe

_SOURCE_ID = "recipenlg"
_LICENSE = "non-commercial research and educational use only"
_DEFAULT_SERVINGS = 4.0


def _coerce_string_list(raw: str) -> tuple[str, ...]:
    """Parse a JSON array of strings; tolerate a bare string or malformed cell.

    RecipeNLG-style dumps store `ingredients` and `directions` as JSON array literals inside a
    CSV cell (e.g. '["2 cups flour", "1 egg"]'). A row with a malformed or missing array yields
    an empty tuple rather than raising, so one bad row does not abort the whole adapter.
    """
    text = raw.strip()
    if not text:
        return ()
    try:
        parsed: Any = json.loads(text)
    except json.JSONDecodeError:
        return (text,)
    if isinstance(parsed, list):
        return tuple(str(item).strip() for item in parsed if str(item).strip())
    if isinstance(parsed, str):
        return (parsed,) if parsed.strip() else ()
    return ()


def _coerce_servings(raw: str | None) -> float:
    if raw is None:
        return _DEFAULT_SERVINGS
    text = raw.strip()
    if not text:
        return _DEFAULT_SERVINGS
    try:
        value = float(text)
    except ValueError:
        return _DEFAULT_SERVINGS
    return value if value > 0 else _DEFAULT_SERVINGS


class RecipeNlgAdapter:
    """Reads a RecipeNLG-format CSV and yields one `RawRecipe` per row.

    Expected columns: `title`, `ingredients` (JSON array of ingredient-line strings),
    `directions` (JSON array of step strings), `link`, `source`, and an optional `servings`
    column. Rows missing `title` are skipped; a row with unparsable `ingredients` or
    `directions` yields an empty tuple for that field rather than failing the whole read.
    """

    def __init__(self, csv_path: str | Path) -> None:
        self._csv_path = Path(csv_path)

    def recipes(self) -> Iterator[RawRecipe]:
        with self._csv_path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            for index, row in enumerate(reader):
                title = (row.get("title") or "").strip()
                if not title:
                    continue
                yield RawRecipe(
                    recipe_id=f"{_SOURCE_ID}:{index}",
                    title=title,
                    source_id=_SOURCE_ID,
                    license=_LICENSE,
                    servings=_coerce_servings(row.get("servings")),
                    ingredient_lines=_coerce_string_list(row.get("ingredients") or ""),
                    preparation_steps=_coerce_string_list(row.get("directions") or ""),
                )


__all__ = ["RecipeNlgAdapter"]
