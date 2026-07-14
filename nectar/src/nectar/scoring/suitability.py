"""Disease-suitability scoring. [INVARIANT] Pure functions, no I/O.

A hard-limit breach produces a contraindication, not a low score. Contraindications are exclusions,
not deductions. See ../../docs/PDD.md Section 8.1 and SDD Section 7.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Literal

CONTRAINDICATED = -1.0


@dataclass(frozen=True)
class Constraint:
    nutrient: str
    type: Literal["restrict", "target"]
    unit: str = ""
    max_per_serving: float | None = None
    hard_limit: float | None = None
    band: float | None = None
    safety_critical: bool = False
    goal: float | None = None
    min_per_serving: float | None = None
    guideline_id: str = ""


@dataclass(frozen=True)
class ScoreResult:
    score: float
    contraindicated: bool
    reasons: list[str] = field(default_factory=list)


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def sub_score(value: float | None, c: Constraint) -> float:
    """One constraint -> [0,1], or CONTRAINDICATED for a hard-limit breach."""
    if value is None:
        return 0.5  # unknown -> neutral; lowers confidence upstream, not the score
    if c.type == "restrict":
        if c.hard_limit is not None and value > c.hard_limit:
            return CONTRAINDICATED  # [INVARIANT] exclusion, not a low score
        limit = c.max_per_serving if c.max_per_serving is not None else (c.hard_limit or value)
        band = c.band or ((c.hard_limit or limit) - limit) or 1.0
        return _clamp(1.0 - max(0.0, value - limit) / band, 0.0, 1.0)
    # target
    goal = c.goal or c.min_per_serving or 1.0
    return _clamp(value / goal, 0.0, 1.0)


def condition_score(nutrients: dict[str, float], constraints: list[Constraint]) -> ScoreResult:
    subs = {c.nutrient: sub_score(nutrients.get(c.nutrient), c) for c in constraints}
    contraindicated = [n for n, s in subs.items() if s == CONTRAINDICATED]
    if contraindicated:
        return ScoreResult(score=0.0, contraindicated=True, reasons=contraindicated)
    graded = [s for s in subs.values() if s != CONTRAINDICATED]
    mean = sum(graded) / len(graded) if graded else 0.0
    return ScoreResult(score=mean, contraindicated=False)
