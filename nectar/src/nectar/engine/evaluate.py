"""Two-stage evaluation: Stage 1 hard filter, Stage 2 graded score. [INVARIANT] Pure, no I/O.

Stage 1 excludes on absolute rules: allergens, absolute drug-food interactions, food-safety
exclusions gated by physiologic state, and equipment the patient cannot use. Stage 2 scores the
survivors with condition_score. A hard-limit breach is a contraindication (an exclusion), never a
low score. See ../../docs/PDD.md Section 6, SDD Section 4.
"""
from __future__ import annotations
from dataclasses import dataclass, field

from nectar.engine.constraints import ResolvedConstraints, VariantFacts
from nectar.scoring.suitability import condition_score


@dataclass(frozen=True)
class Evaluation:
    variant_id: str
    dish_id: str
    admissible: bool
    score: float
    contraindicated: bool
    reasons: list[str] = field(default_factory=list)


def stage1_filter(v: VariantFacts, hard_excludes: frozenset[str]) -> list[str]:
    """Return exclusion reasons; an empty list means the variant passes Stage 1."""
    hits = sorted(v.attributes & hard_excludes)
    return [f"excluded:{h}" for h in hits]


def evaluate_variant(v: VariantFacts, rc: ResolvedConstraints) -> Evaluation:
    blocked = stage1_filter(v, rc.hard_excludes)
    if blocked:
        return Evaluation(v.variant_id, v.dish_id, admissible=False, score=0.0,
                          contraindicated=True, reasons=blocked)
    result = condition_score(v.nutrients, list(rc.by_nutrient.values()))
    reasons = [f"contraindicated:{r}" for r in result.reasons] if result.contraindicated else []
    return Evaluation(v.variant_id, v.dish_id, admissible=not result.contraindicated,
                      score=result.score, contraindicated=result.contraindicated, reasons=reasons)


def evaluate(variants: list[VariantFacts], rc: ResolvedConstraints) -> list[Evaluation]:
    return [evaluate_variant(v, rc) for v in variants]
