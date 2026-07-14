"""FDC nutrient-number -> contract nutrient_id mapping and unit conversion.

Turns a raw FDC food record (from ``fdc_client.food``) into a canonical raw per-100g nutrient
vector keyed by contract nutrient_id, ready for the four-channel transform
(``nutrition/transform.py``) to consume as its ``raw`` input. This module only reads and
unit-converts FDC's own published amounts; per ../../CLAUDE.md and ../../docs/SDD.md Section 3.2,
no nutrient value is ever fabricated or asserted, so an FDC entry whose number is not in the
map, or whose unit cannot be converted to the contract's canonical unit for that nutrient, is
skipped rather than guessed.

Also provides `classify_food`, a keyword match of an FDC description against `food_class.yaml`
food-class tags (root_vegetable, leafy_green, starch, ...) that the TRANSFORM knowledge base
(retention.yaml) keys its coefficients on.

Pure parsing and lookup, no network I/O; `fdc_client.py` owns the HTTP boundary this module's
callers sit downstream of.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Final

from nutriscrape.common.config import load_config

# Mass units convert through a common base (grams); energy has no cross-unit conversion because
# the contract's only energy nutrient (energy, kcal) has no other unit to reconcile against.
_MASS_TO_GRAMS: Final[dict[str, float]] = {
    "g": 1.0,
    "mg": 1e-3,
    "ug": 1e-6,
    "mcg": 1e-6,
}
_ENERGY_UNITS: Final[frozenset[str]] = frozenset({"kcal"})


def _convert_unit(amount: float, from_unit: str, to_unit: str) -> float | None:
    """Convert `amount` from `from_unit` to `to_unit`. Returns None if the pair is not
    reconcilable, so the caller skips the value instead of fabricating a converted number."""
    source = from_unit.strip().lower()
    target = to_unit.strip().lower()
    if source == target:
        return amount
    if source in _ENERGY_UNITS or target in _ENERGY_UNITS:
        return None
    if source in _MASS_TO_GRAMS and target in _MASS_TO_GRAMS:
        return amount * _MASS_TO_GRAMS[source] / _MASS_TO_GRAMS[target]
    return None


def _load_contract_units(config_dir: str | Path | None) -> dict[str, str]:
    """nutrient_id -> canonical unit, from nutrients.yaml (the contract's target vocabulary)."""
    cfg = load_config("nutrients", config_dir)
    entries = cfg.get("nutrients", [])
    units: dict[str, str] = {}
    if isinstance(entries, list):
        for entry in entries:
            if isinstance(entry, dict) and "id" in entry and "unit" in entry:
                units[str(entry["id"])] = str(entry["unit"])
    return units


def load_fdc_nutrient_map(config_dir: str | Path | None = None) -> dict[str, str]:
    """FDC nutrient number (string) -> contract nutrient_id, from fdc_nutrient_map.yaml.

    Several FDC numbers may map to the same contract nutrient_id (EPA 629 and DHA 621 both map
    to omega3_epa_dha); `raw_vector_from_fdc` sums those contributions.
    """
    cfg = load_config("fdc_nutrient_map", config_dir)
    mapping = cfg.get("nutrient_map", {})
    if not isinstance(mapping, dict):
        raise ValueError("fdc_nutrient_map.yaml: 'nutrient_map' must be a mapping")
    return {str(number): str(nutrient_id) for number, nutrient_id in mapping.items()}


def _entry_nutrient_dict(entry: dict[str, Any]) -> dict[str, Any]:
    nutrient = entry.get("nutrient")
    return nutrient if isinstance(nutrient, dict) else {}


def _extract_number(entry: dict[str, Any]) -> str | None:
    """Tolerates both `entry["nutrient"]["number"]` and the alternate
    `entry["nutrientNumber"]` / `entry["nutrient"]["nutrientNumber"]` FDC shapes."""
    nutrient = _entry_nutrient_dict(entry)
    number = nutrient.get("number", nutrient.get("nutrientNumber"))
    if number is None:
        number = entry.get("nutrientNumber")
    if number is None:
        return None
    return str(number)


def _extract_amount(entry: dict[str, Any]) -> float | None:
    """Tolerates both `entry["amount"]` and the alternate `entry["value"]` FDC shape."""
    amount = entry.get("amount", entry.get("value"))
    if amount is None:
        return None
    try:
        return float(amount)
    except (TypeError, ValueError):
        return None


def _extract_unit(entry: dict[str, Any]) -> str | None:
    nutrient = _entry_nutrient_dict(entry)
    unit = nutrient.get("unitName")
    if unit is None:
        unit = entry.get("unitName")
    if unit is None:
        return None
    return str(unit)


def raw_vector_from_fdc(
    food_json: dict[str, Any], config_dir: str | Path | None = None
) -> dict[str, float]:
    """Parse an FDC `food()` record into a raw per-100g nutrient vector keyed by contract
    nutrient_id, unit-converted to each nutrient's canonical unit (nutrients.yaml).

    FDC composition amounts under `foodNutrients` are already per 100 g, so no mass scaling is
    applied here; only the unit is converted. An entry whose number has no contract mapping, or
    whose FDC unit cannot be converted to the contract's canonical unit, is skipped rather than
    fabricated. EPA (629) and DHA (621) both map to omega3_epa_dha and are summed.
    """
    nutrient_map = load_fdc_nutrient_map(config_dir)
    contract_units = _load_contract_units(config_dir)

    entries = food_json.get("foodNutrients", [])
    totals: dict[str, float] = {}
    if not isinstance(entries, list):
        return totals

    for raw_entry in entries:
        if not isinstance(raw_entry, dict):
            continue
        number = _extract_number(raw_entry)
        amount = _extract_amount(raw_entry)
        unit = _extract_unit(raw_entry)
        if number is None or amount is None or unit is None:
            continue

        nutrient_id = nutrient_map.get(number)
        if nutrient_id is None:
            continue

        target_unit = contract_units.get(nutrient_id)
        if target_unit is None:
            continue

        converted = _convert_unit(amount, unit, target_unit)
        if converted is None:
            continue

        totals[nutrient_id] = totals.get(nutrient_id, 0.0) + converted

    return totals


def classify_food(description: str, config_dir: str | Path | None = None) -> list[str]:
    """Case-insensitive keyword match of `description` against food_class.yaml.

    Returns the union of food_class tags for every keyword found as a substring of
    `description`, in config-file order, deduplicated. May be empty if nothing matches.
    """
    cfg = load_config("food_class", config_dir)
    mapping = cfg.get("food_class", {})
    if not isinstance(mapping, dict):
        raise ValueError("food_class.yaml: 'food_class' must be a mapping")

    lowered = description.lower()
    tags: list[str] = []
    for keyword, classes in mapping.items():
        if str(keyword).lower() not in lowered:
            continue
        if not isinstance(classes, list):
            continue
        for tag in classes:
            tag_str = str(tag)
            if tag_str not in tags:
                tags.append(tag_str)
    return tags
