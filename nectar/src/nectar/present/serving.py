"""Standardized patient servings from the canonical per-serving basis. Pure, no I/O.

The graph stores facts on a per-serving basis (DATA_CONTRACT.md Section 1.2). NECTAR standardizes
the serving to the patient (for example, apportioning a daily target across meals) and scales the
per-serving nutrient vector by the same factor, so the displayed numbers stay internally consistent.
See ../../docs/PDD.md Section 8.
"""
from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class StandardizedServing:
    factor: float                       # canonical servings per standardized serving
    serving_mass_g: float
    nutrients: dict[str, float]


def serving_factor(canonical_serving_mass_g: float, target_serving_mass_g: float) -> float:
    """How many canonical servings make one standardized serving. Guards a zero canonical mass."""
    if canonical_serving_mass_g <= 0.0:
        raise ValueError("canonical serving mass must be positive")
    return target_serving_mass_g / canonical_serving_mass_g


def standardize(nutrients: dict[str, float], canonical_serving_mass_g: float,
                target_serving_mass_g: float) -> StandardizedServing:
    factor = serving_factor(canonical_serving_mass_g, target_serving_mass_g)
    scaled = {k: v * factor for k, v in nutrients.items()}
    return StandardizedServing(factor=factor, serving_mass_g=target_serving_mass_g, nutrients=scaled)
