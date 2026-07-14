"""Multi-morbidity conflict resolution. [INVARIANT] Pure functions, no I/O.

Never silently average opposing constraints. A direction conflict (one condition restricts a
nutrient another targets) is resolved by the safety-dominant rule: the restriction wins when
exceeding it carries acute risk, and the conflict is surfaced, not hidden. Renal potassium
restriction overrides the DASH potassium target. See ../../docs/PDD.md Section 8.2, SDD Section 8.
"""
from __future__ import annotations
from collections import defaultdict
from dataclasses import dataclass

from nectar.scoring.suitability import Constraint


@dataclass(frozen=True)
class ConflictNote:
    nutrient: str
    kind: str            # "direction" | "agreement"
    resolution: str
    winning_rule: str
    guideline_ids: list[str]


def _most_restrictive(items: list[Constraint]) -> Constraint:
    # smallest ceiling wins
    return min(items, key=lambda c: (c.max_per_serving if c.max_per_serving is not None else float("inf")))


def _strongest_target(items: list[Constraint]) -> Constraint:
    # largest goal wins
    return max(items, key=lambda c: (c.goal if c.goal is not None else 0.0))


def resolve(constraints: list[Constraint]) -> tuple[dict[str, Constraint], list[ConflictNote]]:
    by_nutrient: dict[str, list[Constraint]] = defaultdict(list)
    for c in constraints:
        by_nutrient[c.nutrient].append(c)

    resolved: dict[str, Constraint] = {}
    conflicts: list[ConflictNote] = []

    for nutrient, items in by_nutrient.items():
        directions = {c.type for c in items}
        gids = [c.guideline_id for c in items if c.guideline_id]

        if "restrict" in directions and "target" in directions:
            restricts = [c for c in items if c.type == "restrict"]
            winner = _most_restrictive(restricts)
            resolved[nutrient] = winner
            if any(c.safety_critical for c in restricts):
                conflicts.append(ConflictNote(
                    nutrient=nutrient, kind="direction",
                    resolution="restriction applied (safety-dominant)",
                    winning_rule=f"{winner.guideline_id} (safety-critical)",
                    guideline_ids=gids))
            else:
                conflicts.append(ConflictNote(
                    nutrient=nutrient, kind="direction",
                    resolution="restriction preferred (non-safety conflict)",
                    winning_rule=winner.guideline_id, guideline_ids=gids))
        elif "restrict" in directions:
            resolved[nutrient] = _most_restrictive(items)
        else:
            resolved[nutrient] = _strongest_target(items)

    return resolved, conflicts
