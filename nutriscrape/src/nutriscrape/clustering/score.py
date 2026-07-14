"""Within-block similarity score. Pure, no I/O.

A weighted blend of core-ingredient overlap (Jaccard), proportion similarity, and method
compatibility, with title-embedding similarity as an optional secondary signal. See SDD Section 5,
PDD Section 7.
"""
from __future__ import annotations

from nutriscrape.clustering.fingerprint import Fingerprint

W_JACCARD = 0.5
W_PROPORTION = 0.3
W_METHOD = 0.2
TITLE_WEIGHT = 0.15     # secondary signal, blended lightly when present


def jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    if not a and not b:
        return 1.0
    union = len(a | b)
    return len(a & b) / union if union else 0.0


def proportion_similarity(a: Fingerprint, b: Fingerprint) -> float:
    shared = a.core_foods & b.core_foods
    if not shared:
        return 0.0
    diffs = [abs(a.proportions.get(f, 0.0) - b.proportions.get(f, 0.0)) for f in shared]
    return max(0.0, 1.0 - sum(diffs) / len(diffs))


def method_compatibility(a: Fingerprint, b: Fingerprint) -> float:
    if not a.primary_method or not b.primary_method:
        return 0.5      # unknown method is neutral, neither a match nor a mismatch
    return 1.0 if a.primary_method == b.primary_method else 0.0


def score(a: Fingerprint, b: Fingerprint, title_sim: float | None = None) -> float:
    base = (W_JACCARD * jaccard(a.core_foods, b.core_foods)
            + W_PROPORTION * proportion_similarity(a, b)
            + W_METHOD * method_compatibility(a, b))
    if title_sim is None:
        return base
    return (1.0 - TITLE_WEIGHT) * base + TITLE_WEIGHT * max(0.0, min(1.0, title_sim))
