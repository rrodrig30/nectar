"""Recipe fingerprint for clustering: core FDC foods, rough proportions, primary method. Pure.

Fingerprinting reduces a resolved recipe to the signals clustering compares on, so two million
recipes need not be compared pairwise. See SDD Section 5, PDD Section 7.
"""
from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class RecipeInput:
    recipe_id: str
    foods: dict[str, float]     # resolved fdc_id -> mass in grams
    primary_method: str = ""
    title: str = ""


@dataclass(frozen=True)
class Fingerprint:
    recipe_id: str
    core_foods: frozenset[str]
    proportions: dict[str, float]      # fdc_id -> fraction of total core mass
    primary_method: str


def fingerprint(recipe: RecipeInput, core_fraction: float = 0.9, min_core: int = 3) -> Fingerprint:
    """Core foods are the largest-mass ingredients that together make up core_fraction of the mass
    (at least min_core of them). Proportions are normalized over the total recipe mass."""
    total = sum(recipe.foods.values()) or 1.0
    ranked = sorted(recipe.foods.items(), key=lambda kv: kv[1], reverse=True)
    core: list[str] = []
    acc = 0.0
    for fdc_id, mass in ranked:
        core.append(fdc_id)
        acc += mass / total
        if len(core) >= min_core and acc >= core_fraction:
            break
    proportions = {fdc_id: recipe.foods[fdc_id] / total for fdc_id in core}
    return Fingerprint(recipe_id=recipe.recipe_id, core_foods=frozenset(core),
                       proportions=proportions, primary_method=recipe.primary_method)
