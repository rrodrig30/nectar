"""Canonical units and conversions. Pure, no I/O.

The graph stores one canonical unit per quantity: mass in grams, volume in milliliters, temperature
in degrees Celsius, energy in kcal (DATA_CONTRACT.md Section 1.2). Extraction yields messy source
units; this module converts them to canonical before the nutrition math runs. This is the internal
truth and is distinct from NECTAR's user-facing unit toggle.
"""
from __future__ import annotations

MASS_TO_G: dict[str, float] = {
    "g": 1.0, "gram": 1.0, "kg": 1000.0, "mg": 0.001, "mcg": 1e-6, "ug": 1e-6,
    "oz": 28.349523125, "ounce": 28.349523125, "lb": 453.59237, "pound": 453.59237,
}
VOLUME_TO_ML: dict[str, float] = {
    "ml": 1.0, "milliliter": 1.0, "l": 1000.0, "liter": 1000.0, "litre": 1000.0,
    "tsp": 4.92892159375, "teaspoon": 4.92892159375,
    "tbsp": 14.78676478125, "tablespoon": 14.78676478125,
    "cup": 236.5882365, "fl_oz": 29.5735295625, "floz": 29.5735295625,
    "pint": 473.176473, "quart": 946.352946, "gallon": 3785.411784,
}


class UnitError(ValueError):
    """Raised when a unit string is not a recognized mass, volume, or temperature unit."""


def _canon(unit: str) -> str:
    return unit.strip().lower().replace(".", "").replace(" ", "_")


def _lookup(unit: str, table: dict[str, float]) -> float | None:
    u = _canon(unit)
    if u in table:
        return table[u]
    if u.endswith("s") and u[:-1] in table:   # tolerate simple plurals (cups, ounces)
        return table[u[:-1]]
    return None


def is_mass_unit(unit: str) -> bool:
    return _lookup(unit, MASS_TO_G) is not None


def is_volume_unit(unit: str) -> bool:
    return _lookup(unit, VOLUME_TO_ML) is not None


def to_grams(quantity: float, unit: str) -> float:
    factor = _lookup(unit, MASS_TO_G)
    if factor is None:
        raise UnitError(f"not a mass unit: {unit!r}")
    return quantity * factor


def to_milliliters(quantity: float, unit: str) -> float:
    factor = _lookup(unit, VOLUME_TO_ML)
    if factor is None:
        raise UnitError(f"not a volume unit: {unit!r}")
    return quantity * factor


def to_celsius(temp: float, scale: str) -> float:
    s = scale.strip().upper()
    if s in ("C", "CELSIUS"):
        return temp
    if s in ("F", "FAHRENHEIT"):
        return (temp - 32.0) * 5.0 / 9.0
    raise UnitError(f"not a temperature scale: {scale!r}")
