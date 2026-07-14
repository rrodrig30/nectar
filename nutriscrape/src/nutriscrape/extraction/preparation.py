"""Preparation-step parser -> ParsedPreparation. [CRITICAL PATH]

Links a later "drain" step back to the ingredient it acts on, because that linkage sets
`liquid_retained_frac`, which flips a leached nutrient (potassium, above all) between lost
and retained in the four-channel transform (../nutrition/transform.py). A boiled-and-drained
cubed potato and potato soup differ only in this fraction and the mass balance it implies.

[INVARIANT] Extraction only. The model turns preparation step text into structural fields
(method, cut_class, timings, temperature, which ingredients a step applies to). It never
computes or states a nutrient number. `resolve_liquid_retained` is a pure, model-free
mapping from step text to the retained-liquid fraction, kept separate and unit-testable so
the drain/no-drain behavior has a golden test with no model or network dependency.
"""
from __future__ import annotations

from typing import Any, Sequence

from pydantic import BaseModel, Field

from nutriscrape.extraction.models import ModelClient

# Schema handed to the model: field name -> instruction for what to extract into it.
# Deliberately excludes anything nutrient-shaped and excludes liquid_retained_frac itself,
# since that is resolved deterministically by `resolve_liquid_retained`, not by the model.
PREPARATION_SCHEMA: dict[str, str] = {
    "method": "the cooking or handling method named or implied by this step (boil, bake, fry, drain, chop, ...)",
    "cut_class": (
        "the cut geometry this step establishes, one of "
        "whole/halved/cubed/diced/grated/mashed, or null if this step states none"
    ),
    "water_ratio": "ratio of water/cooking liquid volume to food volume if stated, else null",
    "time_min": "duration of this step in minutes if stated, else null",
    "temp_c": "temperature in degrees Celsius if stated, else null",
    "applies_to": (
        "a JSON array of ingredient reference tokens, drawn from the provided known "
        "ingredient list, that this step acts on"
    ),
}

# Later step wins: draining or straining discards the cooking liquid, so any leached
# nutrient in it is lost. Everything else defaults to retained.
_DRAIN_KEYWORDS: tuple[str, ...] = ("drain", "strain")
_RETAIN_KEYWORDS: tuple[str, ...] = (
    "soup", "stew", "broth", "braise", "poach", "simmer in", "cooking liquid", "sauce",
)


class ParsedPreparation(BaseModel):
    """One ingredient's resolved preparation. No nutrient value is ever carried here."""

    method: str
    cut_class: str | None = None
    water_ratio: float | None = None
    liquid_retained_frac: float  # drain=0.0, soup=1.0 -- flips leaching. CRITICAL.
    time_min: float | None = None
    temp_c: float | None = None
    applies_to: list[str] = Field(default_factory=list)
    parse_confidence: float


def resolve_liquid_retained(step_text: str) -> float:
    """Map one preparation step's text to the fraction of cooking liquid retained.

    drain / strain    -> 0.0  liquid discarded; leached nutrients (potassium) are lost
    soup / stew / etc -> 1.0  liquid is consumed with the dish; leached nutrients return
    default           -> 1.0  liquid retained unless a step explicitly discards it

    Pure and model-free by design: this single mapping is what flips potassium (and any
    other leached nutrient) between "lost" and "retained" in the four-channel transform,
    so it must be exercised by a golden test with no model or network dependency.
    """
    text = step_text.lower()
    if any(keyword in text for keyword in _DRAIN_KEYWORDS):
        return 0.0
    if any(keyword in text for keyword in _RETAIN_KEYWORDS):
        return 1.0
    return 1.0


def _prompt(step_text: str, ingredient_refs: Sequence[str]) -> str:
    return (
        f"Known ingredient references for this recipe: {list(ingredient_refs)!r}.\n"
        f"Preparation step: {step_text!r}"
    )


def _coerce_applies_to(raw: Any, ingredient_refs: Sequence[str]) -> list[str]:
    """Match the model's applies_to answer back to the known ingredient references.

    Matching is tolerant (case-insensitive substring) because the model may echo the
    ingredient phrase rather than the exact reference token. If nothing matches and there
    is exactly one known ingredient, the step is assumed to act on it: single-ingredient
    steps ("drain.") frequently omit the food name entirely.
    """
    if raw is None:
        tokens: list[str] = []
    elif isinstance(raw, str):
        tokens = [raw]
    elif isinstance(raw, list):
        tokens = [str(item) for item in raw]
    else:
        tokens = []

    lowered_tokens = [t.strip().lower() for t in tokens if str(t).strip()]
    matched = [
        ref
        for ref in ingredient_refs
        if any(ref.lower() in token or token in ref.lower() for token in lowered_tokens)
    ]
    if not matched and len(ingredient_refs) == 1:
        matched = [ingredient_refs[0]]
    return matched


def _coerce_float(raw: Any) -> float | None:
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _coerce_str(raw: Any) -> str | None:
    if raw is None:
        return None
    text = str(raw).strip()
    return text or None


def parse_preparation(
    steps: Sequence[str],
    ingredient_refs: Sequence[str],
    client: ModelClient,
) -> list[ParsedPreparation]:
    """Parse ordered preparation steps into one `ParsedPreparation` per ingredient reference.

    [CRITICAL PATH] Steps are walked in order. Each step's structural fields (method,
    cut_class, timings, which ingredients it applies to) come from the model. Each step's
    `liquid_retained_frac` comes only from `resolve_liquid_retained`, a pure function of the
    step text, and a later step's value always overwrites an earlier one for the same
    ingredient: a "drain" step three steps after "boil" must still zero out the fraction for
    that ingredient. Fields the model leaves null for a later step (cut_class, timings) do
    not erase a value already established by an earlier step.
    """
    by_ingredient: dict[str, ParsedPreparation] = {}

    for step_text in steps:
        result = client.extract(_prompt(step_text, ingredient_refs), PREPARATION_SCHEMA)
        fields = result.fields
        applies_to = _coerce_applies_to(fields.get("applies_to"), ingredient_refs)
        if not applies_to:
            continue

        method = _coerce_str(fields.get("method"))
        cut_class = _coerce_str(fields.get("cut_class"))
        water_ratio = _coerce_float(fields.get("water_ratio"))
        time_min = _coerce_float(fields.get("time_min"))
        temp_c = _coerce_float(fields.get("temp_c"))
        liquid_retained_frac = resolve_liquid_retained(step_text)

        for ref in applies_to:
            existing = by_ingredient.get(ref)
            by_ingredient[ref] = ParsedPreparation(
                method=method or (existing.method if existing else "unknown"),
                cut_class=cut_class if cut_class is not None else (existing.cut_class if existing else None),
                water_ratio=(
                    water_ratio if water_ratio is not None else (existing.water_ratio if existing else None)
                ),
                liquid_retained_frac=liquid_retained_frac,  # later step always wins
                time_min=time_min if time_min is not None else (existing.time_min if existing else None),
                temp_c=temp_c if temp_c is not None else (existing.temp_c if existing else None),
                applies_to=[ref],
                parse_confidence=(
                    min(result.confidence.overall, existing.parse_confidence)
                    if existing
                    else result.confidence.overall
                ),
            )

    return list(by_ingredient.values())


__all__ = ["ParsedPreparation", "resolve_liquid_retained", "parse_preparation", "PREPARATION_SCHEMA"]
