"""Compose a cooked, as-eaten per-serving nutrient vector for a recipe. [INVARIANT] Pure, no I/O.

Every nutrient number here comes only from the four-channel transform (nutrition/transform.py)
applied to FDC-derived raw amounts, scaled by ingredient mass and divided across servings. No model
and no literal produces a value. A nutrient with a matching TRANSFORM coefficient for the food class
and method is cooked through that channel (potassium leaches out of a boiled-and-drained root
vegetable, is retained in soup); a nutrient with no matching coefficient passes through as the raw
scaled amount. Confidence never exceeds the least-confident input. See PDD Section 5, SDD Section 3.5.
"""
from __future__ import annotations
from dataclasses import dataclass
from collections.abc import Sequence

from nutriscrape.common.confidence import propagate
from nutriscrape.knowledge.loaders import TransformCoeff as KBCoeff
from nutriscrape.nutrition.transform import Preparation, TransformCoeff, cooked_amount


@dataclass(frozen=True)
class IngredientFacts:
    """One resolved ingredient: its FDC id, food-class tags (for TRANSFORM lookup), canonical mass,
    the preparation applied to it, and its raw per-100g nutrient vector (canonical units)."""
    fdc_id: str
    food_classes: tuple[str, ...]
    mass_g: float
    prep: Preparation
    raw_per_100g: dict[str, float]


@dataclass(frozen=True)
class CookedNutrient:
    nutrient_id: str
    amount: float          # per serving, canonical unit
    confidence: float
    source: str


def _to_channel_coeff(c: KBCoeff) -> TransformCoeff:
    """Convert a knowledge-base TransformCoeff (with provenance) to the channel-level coefficient the
    transform operator consumes."""
    return TransformCoeff(target=c.target, channel=c.channel, D=c.D, L_base=c.L_base,
                          formation_rate=c.formation_rate, mechanism=c.mechanism,
                          source=c.provenance.source, confidence=c.provenance.confidence,
                          evidence_tier=c.provenance.evidence_tier or "B")


def _coeffs_for(nutrient_id: str, ing: IngredientFacts,
                transforms: Sequence[KBCoeff]) -> list[TransformCoeff]:
    """The transform coefficients that apply to this nutrient for this ingredient's method and food
    class (or exact food id)."""
    return [
        _to_channel_coeff(c)
        for c in transforms
        if c.target == nutrient_id and c.method == ing.prep.method
        and (c.food_id == ing.fdc_id or c.food_class in ing.food_classes)
    ]


def compose_serving_vector(ingredients: Sequence[IngredientFacts],
                           transforms: Sequence[KBCoeff],
                           servings: float) -> dict[str, CookedNutrient]:
    """Cook each ingredient's raw nutrients through the four channels, sum across ingredients, and
    divide by servings. Returns the per-serving cooked vector keyed by contract nutrient_id."""
    servings = servings if servings > 0 else 1.0
    amounts: dict[str, float] = {}
    confidences: dict[str, list[float]] = {}
    sources: dict[str, set[str]] = {}

    for ing in ingredients:
        scale = ing.mass_g / 100.0
        for nutrient_id, per_100g in ing.raw_per_100g.items():
            cooked = cooked_amount(per_100g * scale, _coeffs_for(nutrient_id, ing, transforms), ing.prep)
            amounts[nutrient_id] = amounts.get(nutrient_id, 0.0) + cooked.value
            confidences.setdefault(nutrient_id, []).append(cooked.confidence)
            sources.setdefault(nutrient_id, set()).add(cooked.source)

    return {
        nutrient_id: CookedNutrient(
            nutrient_id=nutrient_id,
            amount=total / servings,
            confidence=propagate(confidences[nutrient_id]),
            source=";".join(sorted(sources[nutrient_id])),
        )
        for nutrient_id, total in amounts.items()
    }
