"""Convert parsed quantities to canonical units (grams, milliliters). Pure, no I/O.

The four-channel transform runs on canonical amounts. Mass units convert to grams. Volume units
convert to milliliters; when a food density is known, volume is further resolved to grams (the
mass basis the transform needs). See PDD Section 5, DATA_CONTRACT Section 1.2.
"""
from __future__ import annotations
from dataclasses import dataclass

from nutriscrape.common import units


@dataclass(frozen=True)
class CanonicalQuantity:
    value: float
    unit: str          # "g" or "ml"


def to_canonical(quantity: float, unit: str,
                 density_g_per_ml: float | None = None) -> CanonicalQuantity:
    """Mass -> grams. Volume -> grams when density is given, otherwise milliliters."""
    if units.is_mass_unit(unit):
        return CanonicalQuantity(units.to_grams(quantity, unit), "g")
    if units.is_volume_unit(unit):
        ml = units.to_milliliters(quantity, unit)
        if density_g_per_ml is not None:
            return CanonicalQuantity(ml * density_g_per_ml, "g")
        return CanonicalQuantity(ml, "ml")
    raise units.UnitError(f"unrecognized unit: {unit!r}")
