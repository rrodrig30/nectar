"""Recommendation facade: enforce the confirmed gate, evaluate, rank, report gaps. Pure, no I/O.

This ties the engine together for the API layer. It reads no graph and calls no model; it operates
on the confirmed constraint set and the contract variant facts the caller supplies. Every result
carries the intended-use boundary. See ../../docs/PDD.md Section 6, SDD Section 4.
"""
from __future__ import annotations
from dataclasses import dataclass

from nectar.abstraction.derive import DerivedConstraint
from nectar.engine.constraints import ResolvedConstraints, VariantFacts, require_confirmed
from nectar.engine.evaluate import evaluate
from nectar.engine.rank import DishRanking, gaps, rank_across_dishes
from nectar.scoring.conflicts import ConflictNote

BOUNDARY = ("Educational and research output, not medical nutrition therapy. Every nutrient value "
            "is calculated, not laboratory-measured.")


@dataclass(frozen=True)
class Recommendation:
    rankings: list[DishRanking]
    conflicts: list[ConflictNote]
    gaps: list[str]
    boundary: str = BOUNDARY


def recommend(confirmed: list[DerivedConstraint], variants: list[VariantFacts],
              rc: ResolvedConstraints) -> Recommendation:
    """`confirmed` is the physician-confirmed derived set (for the gate); `rc` is the resolved
    scoring constraints assembled from it; `variants` are the contract facts to rank."""
    require_confirmed(confirmed)                              # [INVARIANT]
    rankings = rank_across_dishes(evaluate(variants, rc))
    return Recommendation(rankings=rankings, conflicts=rc.conflicts, gaps=gaps(rankings))
