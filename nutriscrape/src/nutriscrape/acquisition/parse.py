"""Deterministic, model-free parsers for well-formed ingredient lines and preparation steps.

The bundled sample corpus (config/samples/recipes_sample.csv) is well-formed enough that a
regex parser handles it without a running LLM, so `make ingest` can exercise the full pipeline
offline. The messy corpus tail still goes through `extraction/ingredients.py` and
`extraction/preparation.py` (the two-tier model parsers). This module never computes or asserts
a nutrient value, exactly like its model-driven counterparts: it emits the same `ParsedIngredient`
and `ParsedPreparation` structures, just via regex and keyword matching instead of a model call.

`basic_preparation` reuses `extraction.preparation.resolve_liquid_retained`, the single pure
mapping from step text to retained-liquid fraction, so the drain/no-drain golden behavior
(a later "drain" step overriding an earlier "boil") is exercised identically here and in the
model-driven parser.
"""
from __future__ import annotations

import re
from typing import Sequence

from nutriscrape.common.units import is_mass_unit, is_volume_unit
from nutriscrape.extraction.ingredients import ParsedIngredient
from nutriscrape.extraction.preparation import ParsedPreparation, resolve_liquid_retained

# Deliberately conservative: unresolved model touch would score higher confidence. A regex/keyword
# parse over well-formed lines is reliable but lower-fidelity than a trained model's judgment.
_BASIC_PARSE_CONFIDENCE = 0.6

_UNICODE_FRACTIONS: dict[str, float] = {
    "¼": 0.25, "½": 0.5, "¾": 0.75,
    "⅓": 1.0 / 3.0, "⅔": 2.0 / 3.0,
    "⅛": 0.125, "⅜": 0.375, "⅝": 0.625, "⅞": 0.875,
}
_UNICODE_FRACTION_CLASS = "".join(_UNICODE_FRACTIONS)

_MIXED_NUMBER_RE = re.compile(r"^(\d+)\s+(\d+)/(\d+)(?=\s|$)")
_SIMPLE_FRACTION_RE = re.compile(r"^(\d+)/(\d+)(?=\s|$)")
_DECIMAL_WITH_UNICODE_RE = re.compile(
    rf"^(\d+(?:\.\d+)?)([{_UNICODE_FRACTION_CLASS}])?(?=\s|$)"
)
_UNICODE_ALONE_RE = re.compile(rf"^([{_UNICODE_FRACTION_CLASS}])(?=\s|$)")

# Method vocabulary for the deterministic preparation parser: HEAT (cooking) methods only, because
# the four-channel transform's D/L coefficients are keyed to the cooking method. Liquid operations
# (drain, strain) are deliberately excluded here so they do not overwrite the cooking method; they
# set liquid_retained_frac via resolve_liquid_retained instead. Cut/texture verbs are handled by the
# cut vocabulary below. Order is the match priority when a step names more than one keyword.
_METHOD_KEYWORDS: tuple[str, ...] = (
    "boil", "bake", "roast", "fry", "saute", "steam", "simmer",
)
_CUT_KEYWORDS: tuple[str, ...] = ("cubed", "diced", "grated", "mashed", "halved")

_TIME_MIN_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:min|mins|minute|minutes)\b", re.IGNORECASE)


def _parse_quantity(text: str) -> tuple[float | None, str]:
    """Peel a leading quantity off `text`, returning it and the stripped remainder.

    Handles a mixed number ("1 1/2"), a simple fraction ("1/2"), an integer or decimal
    optionally glued to a unicode fraction ("1½"), or a unicode fraction alone ("½"). Returns
    `None` and the original text unchanged if it does not start with a recognized quantity.
    """
    stripped = text.strip()

    match = _MIXED_NUMBER_RE.match(stripped)
    if match:
        whole, num, den = match.groups()
        quantity = float(whole) + float(num) / float(den)
        return quantity, stripped[match.end():].strip()

    match = _SIMPLE_FRACTION_RE.match(stripped)
    if match:
        num, den = match.groups()
        return float(num) / float(den), stripped[match.end():].strip()

    match = _DECIMAL_WITH_UNICODE_RE.match(stripped)
    if match:
        quantity = float(match.group(1))
        if match.group(2):
            quantity += _UNICODE_FRACTIONS[match.group(2)]
        return quantity, stripped[match.end():].strip()

    match = _UNICODE_ALONE_RE.match(stripped)
    if match:
        return _UNICODE_FRACTIONS[match.group(1)], stripped[match.end():].strip()

    return None, stripped


def _split_qualifiers(qualifier_text: str) -> list[str]:
    """Split trailing comma-clauses into individual qualifiers, further splitting on "and"."""
    qualifiers: list[str] = []
    for clause in qualifier_text.split(","):
        for part in clause.split(" and "):
            cleaned = part.strip()
            if cleaned:
                qualifiers.append(cleaned)
    return qualifiers


def parse_ingredient_basic(line: str) -> ParsedIngredient:
    """Regex-parse one well-formed ingredient line: "<qty> <unit> <food>, <qualifiers>".

    Model-free counterpart to `extraction.ingredients.parse_ingredient_line`. Never computes or
    states a nutrient value; it only structures the line the same way the model parser would,
    at a lower `parse_confidence` since no model judgment backs the split.
    """
    head, _, qualifier_text = line.partition(",")
    qualifiers = _split_qualifiers(qualifier_text)

    quantity, remainder = _parse_quantity(head)

    unit: str | None = None
    if remainder:
        first_token, _, rest = remainder.partition(" ")
        candidate = first_token.strip(".,").lower()
        if is_mass_unit(candidate) or is_volume_unit(candidate):
            unit = candidate
            remainder = rest.strip()

    food = remainder.strip()
    if food.lower().startswith("of "):
        food = food[3:].strip()
    if not food:
        food = head.strip()

    return ParsedIngredient(
        quantity=quantity,
        unit=unit,
        food=food,
        prep_ref=None,
        qualifiers=qualifiers,
        parse_confidence=_BASIC_PARSE_CONFIDENCE,
    )


def _detect_method(step_text: str) -> str | None:
    lowered = step_text.lower()
    for keyword in _METHOD_KEYWORDS:
        if keyword in lowered:
            return keyword
    return None


def _detect_cut_class(step_text: str) -> str | None:
    lowered = step_text.lower()
    for keyword in _CUT_KEYWORDS:
        if keyword in lowered:
            return keyword
    return None


def _detect_time_min(step_text: str) -> float | None:
    match = _TIME_MIN_RE.search(step_text)
    return float(match.group(1)) if match else None


def _match_applies_to(step_text: str, ingredient_refs: Sequence[str]) -> list[str]:
    """Case-insensitive substring match of known ingredient refs against a step's text.

    If nothing matches and there is exactly one known ingredient, the step is assumed to act on
    it, since single-ingredient steps ("Drain.") frequently omit the food name.
    """
    lowered = step_text.lower()
    matched = [ref for ref in ingredient_refs if ref.lower() in lowered]
    if not matched and len(ingredient_refs) == 1:
        matched = [ingredient_refs[0]]
    return matched


def basic_preparation(
    steps: Sequence[str], ingredient_refs: Sequence[str]
) -> list[ParsedPreparation]:
    """Keyword-parse ordered preparation steps into one `ParsedPreparation` per ingredient.

    [CRITICAL PATH, model-free] `liquid_retained_frac` comes only from
    `resolve_liquid_retained`, exactly as in `extraction.preparation.parse_preparation`, and a
    later step's value always overwrites an earlier one for the same ingredient: a "drain" step
    after a "boil" step must still zero out the fraction. Fields a later step leaves undetected
    (method, cut_class, time_min) do not erase a value already established by an earlier step.
    """
    by_ingredient: dict[str, ParsedPreparation] = {}

    for step_text in steps:
        applies_to = _match_applies_to(step_text, ingredient_refs)
        if not applies_to:
            continue

        method = _detect_method(step_text)
        cut_class = _detect_cut_class(step_text)
        time_min = _detect_time_min(step_text)
        liquid_retained_frac = resolve_liquid_retained(step_text)

        for ref in applies_to:
            existing = by_ingredient.get(ref)
            by_ingredient[ref] = ParsedPreparation(
                method=method or (existing.method if existing else "unknown"),
                cut_class=cut_class if cut_class is not None else (
                    existing.cut_class if existing else None
                ),
                water_ratio=existing.water_ratio if existing else None,
                liquid_retained_frac=liquid_retained_frac,  # later step always wins
                time_min=time_min if time_min is not None else (
                    existing.time_min if existing else None
                ),
                temp_c=existing.temp_c if existing else None,
                applies_to=[ref],
                parse_confidence=_BASIC_PARSE_CONFIDENCE,
            )

    return list(by_ingredient.values())


__all__ = ["parse_ingredient_basic", "basic_preparation"]
