"""Four-channel preparation transform. [INVARIANT]

This is the ONLY path to a cooked nutrient value. Preparation is an operator on a food's intrinsic
facts, not an annotation. Three reduction effects plus one addition:

    effective = raw * D * (1 - L * (1 - kept_liquid))   (+ formation, for created compounds)

  D           degradation survival fraction (heat/oxygen lability)    not recoverable
  L           fraction leached to the cooking medium                  recoverable if liquid kept
  kept_liquid fraction of cooking liquid retained in the dish         mass balance
  formation   compound created by the method (acrylamide, HCAs)

Leaching scales with cut geometry (surface-area-to-volume), water ratio, time, temperature.
Pure functions, no I/O. See ../../docs/PDD.md Section 5 and DATA_CONTRACT.md Section 3.2.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Literal, Sequence

Channel = Literal["concentration", "leaching", "degradation", "formation"]


@dataclass(frozen=True)
class TransformCoeff:
    target: str                 # nutrient_id or compound_id
    channel: Channel
    D: float | None = None
    L_base: float | None = None
    formation_rate: float | None = None
    mechanism: str = ""
    source: str = "estimated"
    confidence: float = 0.5
    evidence_tier: Literal["A", "B", "C"] = "B"


@dataclass(frozen=True)
class Preparation:
    method: str
    cut_class: str = "whole"
    water_ratio: float | None = None
    liquid_retained_frac: float = 1.0   # drain=0.0, soup=1.0. Flips leaching. CRITICAL.
    time_min: float | None = None
    temp_c: float | None = None


@dataclass(frozen=True)
class CookedValue:
    value: float
    confidence: float
    source: str


# cut geometry multiplier on leaching; seeded from config/retention.yaml at load time
SA_V_MULT: dict[str, float] = {
    "whole": 1.0, "halved": 1.3, "cubed": 2.7, "diced": 4.0, "grated": 6.0, "mashed": 7.0,
}
L_MAX = 0.95


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _medium_factor(water_ratio: float | None, time_min: float | None, temp_c: float | None) -> float:
    """Scale leaching by contact conditions. Placeholder monotonic form; calibrate against data."""
    w = 1.0 if water_ratio is None else _clamp(water_ratio / 4.0, 0.3, 1.0)
    t = 1.0 if time_min is None else _clamp(time_min / 20.0, 0.3, 1.0)
    h = 1.0 if temp_c is None else _clamp(temp_c / 100.0, 0.3, 1.0)
    return w * t * h


def leach_fraction(coeffs: Sequence[TransformCoeff], prep: Preparation) -> float:
    base = next((c.L_base for c in coeffs if c.channel == "leaching" and c.L_base is not None), 0.0)
    geo = SA_V_MULT.get(prep.cut_class, 1.0)
    return _clamp(base * geo * _medium_factor(prep.water_ratio, prep.time_min, prep.temp_c), 0.0, L_MAX)


def cooked_amount(raw: float, coeffs: Sequence[TransformCoeff], prep: Preparation) -> CookedValue:
    """Apply the four channels. `coeffs` are the coefficients for one target under one method."""
    d_values = [c.D for c in coeffs if c.channel == "degradation" and c.D is not None]
    D = 1.0
    for d in d_values:
        D *= d
    L = leach_fraction(coeffs, prep)
    kept = prep.liquid_retained_frac
    reduced = raw * D * (1.0 - L * (1.0 - kept))
    formed = sum(
        (c.formation_rate or 0.0) * _medium_factor(prep.water_ratio, prep.time_min, prep.temp_c)
        for c in coeffs
        if c.channel == "formation"
    )
    confidence = min((c.confidence for c in coeffs), default=0.5)
    source = "transform:" + ",".join(sorted({c.source for c in coeffs})) if coeffs else "transform:none"
    return CookedValue(value=max(0.0, reduced + formed), confidence=confidence, source=source)
