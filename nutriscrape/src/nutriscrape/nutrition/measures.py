"""Resolve a parsed ingredient quantity to canonical grams. Pure logic over cached config.

The four-channel transform and the per-serving math run on grams. A parsed ingredient carries a
quantity and, often, a messy unit: a mass ("8 oz"), a volume ("1 cup"), or a bare count with no
mass/volume unit at all ("2 eggs", "3 cloves garlic"). This module turns each into grams:

  mass unit    -> grams directly (nutriscrape.common.units)
  volume unit  -> milliliters, then grams via a food-class density
  count / none -> grams via a per-item portion weight

Densities and portion weights are ILLUSTRATIVE reference values in config/measures.yaml, pending
review against USDA FDC food_portion (the authoritative per-food gram_weight). Before this, ingest
defaulted a unitless count to grams, so "2 eggs" became 2 g and every downstream nutrient total was
wrong; this is the root-cause fix for the mass basis. See PDD Section 5, DATA_CONTRACT Section 1.2.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from nutriscrape.common import units
from nutriscrape.common.config import load_config


@dataclass(frozen=True)
class MeasureTable:
    """Substring-keyed density and portion tables with fallbacks."""

    density_g_per_ml: dict[str, float] = field(default_factory=dict)
    count_grams: dict[str, float] = field(default_factory=dict)
    default_density: float = 1.0
    default_count_g: float = 100.0


def _section(cfg: dict[str, object], key: str) -> dict[str, float]:
    raw = cfg.get(key, {})
    if not isinstance(raw, dict):
        return {}
    return {
        str(k).lower(): float(v)
        for k, v in raw.items()
        if k != "default" and isinstance(v, (int, float))
    }


def _default_value(cfg: dict[str, object], key: str, fallback: float) -> float:
    raw = cfg.get(key, {})
    if isinstance(raw, dict) and isinstance(raw.get("default"), (int, float)):
        return float(raw["default"])
    return fallback


def load_measure_table(config_dir: str | Path | None = None) -> MeasureTable:
    """Load config/measures.yaml into a `MeasureTable`."""
    cfg = load_config("measures", config_dir)
    return MeasureTable(
        density_g_per_ml=_section(cfg, "volume_density_g_per_ml"),
        count_grams=_section(cfg, "count_grams"),
        default_density=_default_value(cfg, "volume_density_g_per_ml", 1.0),
        default_count_g=_default_value(cfg, "count_grams", 100.0),
    )


def _match(description: str, table: dict[str, float], default: float) -> float:
    """Longest keyword found as a substring of `description` wins (more specific beats generic);
    the table's default applies when nothing matches."""
    lowered = description.lower()
    best_key: str | None = None
    for key in table:
        if key in lowered and (best_key is None or len(key) > len(best_key)):
            best_key = key
    return table[best_key] if best_key is not None else default


def resolve_mass_g(
    quantity: float | None, unit: str | None, description: str, table: MeasureTable
) -> float:
    """Grams for a parsed quantity/unit against a food description. Never raises: an unrecognized
    unit falls through to the portion-weight path rather than dropping the ingredient."""
    q = quantity if quantity is not None else 0.0
    if unit:
        u = unit.strip()
        if u and units.is_mass_unit(u):
            return units.to_grams(q, u)
        if u and units.is_volume_unit(u):
            ml = units.to_milliliters(q, u)
            return ml * _match(description, table.density_g_per_ml, table.default_density)
    # No unit, or a unit that is neither mass nor volume. The portion keyword can live in the unit
    # ("3 cloves", "2 slices") or the description ("2 eggs"), so match against both.
    haystack = f"{unit or ''} {description}"
    return q * _match(haystack, table.count_grams, table.default_count_g)


@lru_cache(maxsize=1)
def _default_table() -> MeasureTable:
    return load_measure_table()


def resolve_mass_g_default(quantity: float | None, unit: str | None, description: str) -> float:
    """Module-level resolver bound to the default config table (loaded once). Matches the
    `IngestDeps.mass_resolver` signature so ingest gets real gram resolution by default while tests
    can inject a fake."""
    return resolve_mass_g(quantity, unit, description, _default_table())
