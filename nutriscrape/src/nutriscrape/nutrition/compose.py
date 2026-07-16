"""Compose a cooked, as-eaten per-serving nutrient vector for a recipe. [INVARIANT] Pure, no I/O.

Every nutrient number here comes only from the four-channel transform (nutrition/transform.py)
applied to FDC-derived raw amounts, scaled by ingredient mass and divided across servings. No model
and no literal produces a value. A nutrient with a matching TRANSFORM coefficient for the food class
and method is cooked through that channel (potassium leaches out of a boiled-and-drained root
vegetable, is retained in soup); a nutrient with no matching coefficient passes through as the raw
scaled amount. Confidence never exceeds the least-confident input. See PDD Section 5, SDD Section 3.5.
"""
from __future__ import annotations
import re
from dataclasses import dataclass
from collections.abc import Sequence

from nutriscrape.common.confidence import propagate
from nutriscrape.knowledge.loaders import TransformCoeff as KBCoeff
from nutriscrape.nutrition.transform import Preparation, TransformCoeff, cooked_amount

# A cooking liquid whose drained portion leaves the as-eaten dish (so only the retained fraction
# counts toward serving mass and fluid). Matched at word level so "Watermelon" is not "water".
_LIQUID_TOKENS = frozenset({"water", "broth", "stock", "bouillon", "consomme"})
_WORD_RE = re.compile(r"[a-z]+")


def is_cooking_liquid(description: str) -> bool:
    return bool(set(_WORD_RE.findall(description.lower())) & _LIQUID_TOKENS)


@dataclass(frozen=True)
class IngredientFacts:
    """One resolved ingredient: its FDC id, food-class tags (for TRANSFORM lookup), canonical mass,
    the preparation applied to it, and its raw per-100g nutrient vector (canonical units).

    `is_liquid` marks a cooking liquid (water, broth, stock): only the fraction retained
    (`prep.liquid_retained_frac`) stays in the as-eaten dish, so a drained liquid does not count
    toward the serving mass. A solid ingredient keeps its full mass regardless.
    """
    fdc_id: str
    food_classes: tuple[str, ...]
    mass_g: float
    prep: Preparation
    raw_per_100g: dict[str, float]
    is_liquid: bool = False


@dataclass(frozen=True)
class ServingFacts:
    """Per-serving variant facts derived from the composition (DATA_CONTRACT.md Section 3.1)."""
    serving_mass_g: float
    energy_kcal: float | None
    fluid_ml: float | None


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


def serving_facts(
    ingredients: Sequence[IngredientFacts],
    cooked: dict[str, CookedNutrient],
    servings: float,
) -> ServingFacts:
    """Per-serving mass, energy, and fluid for the variant, from the same composition.

    `serving_mass_g` sums each ingredient's as-eaten mass (a cooking liquid contributes only the
    fraction retained, so drained water leaves the dish) and divides by servings. `energy_kcal` is
    the cooked energy value already on the per-serving vector. `fluid_ml` is the retained cooking-
    liquid mass per serving (density approx 1 g/mL); None when the dish carries no fluid.
    """
    servings = servings if servings > 0 else 1.0
    total_mass = 0.0
    fluid = 0.0
    for ing in ingredients:
        retained = ing.prep.liquid_retained_frac if ing.is_liquid else 1.0
        contribution = ing.mass_g * retained
        total_mass += contribution
        if ing.is_liquid:
            fluid += contribution
    energy = cooked.get("energy")
    return ServingFacts(
        serving_mass_g=total_mass / servings,
        energy_kcal=(energy.amount if energy is not None else None),
        fluid_ml=(fluid / servings) if fluid > 0.0 else None,
    )
