"""Canonical -> US/metric and C/F, applied at display time. [INVARIANT] Pure, no I/O.

The graph stores one canonical unit per quantity (grams, milliliters, kcal, degrees Celsius,
per serving). The user-facing unit system and temperature scale are a presentation concern and never
change what is stored: one stored truth, a display transform, never two stored copies.
See ../../docs/PDD.md Section 8, DATA_CONTRACT.md Section 1.2.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Literal

UnitSystem = Literal["us", "metric"]
TempScale = Literal["F", "C"]

_G_PER_OZ = 28.349523125
_ML_PER_FLOZ = 29.5735295625
_ML_PER_CUP = 236.5882365


@dataclass(frozen=True)
class DisplayValue:
    value: float
    unit: str


def _round(x: float, places: int = 2) -> float:
    return round(x, places)


def mass_g(grams: float, system: UnitSystem) -> DisplayValue:
    """Canonical grams -> display. US uses ounces (pounds above 16 oz); metric uses g (kg above 1000)."""
    if system == "us":
        oz = grams / _G_PER_OZ
        if oz >= 16.0:
            return DisplayValue(_round(oz / 16.0), "lb")
        return DisplayValue(_round(oz), "oz")
    if grams >= 1000.0:
        return DisplayValue(_round(grams / 1000.0), "kg")
    return DisplayValue(_round(grams), "g")


def volume_ml(ml: float, system: UnitSystem) -> DisplayValue:
    """Canonical milliliters -> display. US uses cups (fl oz below one cup); metric uses mL (L above 1000)."""
    if system == "us":
        if ml >= _ML_PER_CUP:
            return DisplayValue(_round(ml / _ML_PER_CUP), "cup")
        return DisplayValue(_round(ml / _ML_PER_FLOZ), "fl oz")
    if ml >= 1000.0:
        return DisplayValue(_round(ml / 1000.0), "L")
    return DisplayValue(_round(ml), "mL")


def temperature_c(celsius: float, scale: TempScale) -> DisplayValue:
    if scale == "F":
        return DisplayValue(_round(celsius * 9.0 / 5.0 + 32.0, 1), "F")
    return DisplayValue(_round(celsius, 1), "C")


def convert(value: float, canonical_unit: str, system: UnitSystem, temp_scale: TempScale) -> DisplayValue:
    """Dispatch by the canonical unit string. Nutrient masses in mg/mcg pass through unchanged
    (nutrition labels are unit-system independent); only bulk mass, volume, and temperature convert."""
    if canonical_unit == "g":
        return mass_g(value, system)
    if canonical_unit == "ml":
        return volume_ml(value, system)
    if canonical_unit == "c":
        return temperature_c(value, temp_scale)
    return DisplayValue(_round(value), canonical_unit)


def nutrient_amount(value: float, unit: str) -> DisplayValue:
    """Present one nutrient amount (a per-serving value or a distribution statistic) in its label
    unit. [INVARIANT] Nutrient amounts are unit-system independent: a nutrition label reads 600 mg
    sodium and 20 g protein in both US and metric. So a nutrient amount is NOT run through `convert`
    (which sends bulk grams to ounces for US); it is only rounded and labeled. This is where a future
    label-level policy (for example, energy in kJ for metric) would live, if one were ever adopted."""
    return DisplayValue(_round(value), unit.strip())
