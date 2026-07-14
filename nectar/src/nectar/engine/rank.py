"""Ranking: best admissible version per dish, and versions within a dish. Pure, no I/O.

Across dishes, the best admissible version represents each dish. Within a dish, the real corpus
versions are ordered for this patient, which is the clinically useful mode: it meets the patient at
a food they already want. Dishes with no admissible version are reported as gaps for remediation.
See ../../docs/PDD.md Section 6, SDD Section 4.
"""
from __future__ import annotations
from collections import defaultdict
from dataclasses import dataclass

from nectar.engine.evaluate import Evaluation


@dataclass(frozen=True)
class DishRanking:
    dish_id: str
    best: Evaluation | None            # None when the dish has no admissible version
    versions: list[Evaluation]         # admissible versions, best first


def rank_within_dish(evals: list[Evaluation]) -> list[Evaluation]:
    admissible = [e for e in evals if e.admissible]
    return sorted(admissible, key=lambda e: e.score, reverse=True)


def rank_across_dishes(evals: list[Evaluation]) -> list[DishRanking]:
    by_dish: dict[str, list[Evaluation]] = defaultdict(list)
    for e in evals:
        by_dish[e.dish_id].append(e)
    rankings = [
        DishRanking(dish_id=dish_id, best=(versions[0] if versions else None), versions=versions)
        for dish_id, items in by_dish.items()
        for versions in (rank_within_dish(items),)
    ]
    rankings.sort(key=lambda d: (d.best is not None, d.best.score if d.best else 0.0), reverse=True)
    return rankings


def gaps(rankings: list[DishRanking]) -> list[str]:
    """Dish ids with no admissible version. These are the only candidates for remediation."""
    return [r.dish_id for r in rankings if r.best is None]
