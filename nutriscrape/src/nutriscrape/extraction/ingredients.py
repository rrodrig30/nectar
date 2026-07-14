"""Ingredient-line parser -> ParsedIngredient.

[INVARIANT] Extraction only. The model turns one messy natural-language ingredient line
into structured fields (quantity, unit, food, a preparation-step link, qualifiers) and a
per-field confidence. It never computes, estimates, or states a nutrient number; nutrient
values come only from the four-channel transform reading the graph (see
../nutrition/transform.py and DATA_CONTRACT.md Section 3.2).
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from nutriscrape.extraction.models import ModelClient

# Schema handed to the model: field name -> instruction for what to extract into it.
# Deliberately excludes anything nutrient-shaped.
INGREDIENT_SCHEMA: dict[str, str] = {
    "quantity": "the numeric quantity as written (e.g. 2, 0.5), or null if none is stated",
    "unit": "the unit of measure as written (cup, g, clove, ...), or null if unitless",
    "food": "the canonical food name/phrase, stripped of quantity, unit, and qualifiers",
    "prep_ref": (
        "a short reference token for a preparation step this ingredient links to "
        "(e.g. 'drain the potatoes' -> 'potatoes'), or null if this line names no step"
    ),
    "qualifiers": (
        "a JSON array of descriptive qualifiers on the food "
        "(fresh, chopped, optional, low-sodium, ...), or an empty array"
    ),
}


class ParsedIngredient(BaseModel):
    """One ingredient line, parsed into structure. No nutrient value is ever carried here."""

    quantity: float | None = None
    unit: str | None = None
    food: str
    prep_ref: str | None = None
    qualifiers: list[str] = Field(default_factory=list)
    parse_confidence: float


def _prompt(line: str) -> str:
    return f"Ingredient line: {line!r}"


def _coerce_qualifiers(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        return [raw] if raw.strip() else []
    if isinstance(raw, list):
        return [str(item) for item in raw if str(item).strip()]
    return []


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


def parse_ingredient_line(line: str, client: ModelClient) -> ParsedIngredient:
    """Parse one ingredient line via the two-tier model client.

    The model hands back structural fields only; this function coerces them into
    `ParsedIngredient` and carries the client's overall confidence as `parse_confidence`.
    """
    result = client.extract(_prompt(line), INGREDIENT_SCHEMA)
    fields = result.fields

    food = _coerce_str(fields.get("food")) or line.strip()

    return ParsedIngredient(
        quantity=_coerce_float(fields.get("quantity")),
        unit=_coerce_str(fields.get("unit")),
        food=food,
        prep_ref=_coerce_str(fields.get("prep_ref")),
        qualifiers=_coerce_qualifiers(fields.get("qualifiers")),
        parse_confidence=result.confidence.overall,
    )
