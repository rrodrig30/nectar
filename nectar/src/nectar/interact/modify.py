"""Taste and equipment limits become added exclusions, then the engine reruns. Pure, no I/O.

A method the patient cannot perform (no grill, no convection oven, no stand mixer) is another Stage 1
filter, and a taste dislike is handled the same way. This grows the exclusion set and reruns the same
evaluation; it never touches the scoring middle. See ../../docs/PDD.md Section 9, SDD Section 7.
"""
from __future__ import annotations
from dataclasses import dataclass

from nectar.engine.constraints import ResolvedConstraints

# an equipment phrase maps to the method attribute a variant would carry
EQUIPMENT_METHOD: dict[str, str] = {
    "no grill": "grill", "no convection oven": "convection", "no oven": "bake",
    "no stand mixer": "stand_mixer", "no microwave": "microwave", "no deep fryer": "deep_fry",
    "no blender": "blend", "no food processor": "process",
}


@dataclass(frozen=True)
class Modifications:
    exclude_methods: frozenset[str] = frozenset()
    exclude_attributes: frozenset[str] = frozenset()   # taste or ingredient dislikes


def parse_equipment(limits: list[str]) -> frozenset[str]:
    return frozenset(EQUIPMENT_METHOD[k] for k in (lim.strip().lower() for lim in limits)
                     if k in EQUIPMENT_METHOD)


def apply(base: ResolvedConstraints, mods: Modifications) -> ResolvedConstraints:
    """Fold the added exclusions into the Stage 1 hard set. Nutrient constraints and conflict
    resolution are unchanged; only the exclusion set grows, so a rerun re-filters and re-ranks."""
    excludes = base.hard_excludes | mods.exclude_methods | mods.exclude_attributes
    return ResolvedConstraints(by_nutrient=base.by_nutrient, hard_excludes=excludes,
                               conflicts=base.conflicts)
