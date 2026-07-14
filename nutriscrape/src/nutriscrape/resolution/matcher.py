"""Candidate-and-rank food match; LLM may normalize the query string, validated against FDC.

[INVARIANT] The model, if used upstream to normalize a messy ingredient string, never asserts
composition or a nutrient value. This module only ranks FDC search candidates against the
(possibly normalized) query string and validates the top candidate against a threshold. The
ranking itself is pure and I/O-free per ../../docs/PDD.md Section 1 (resolution/ layout) and
../../CLAUDE.md: I/O lives in `fdc_client.py`; `rank_candidates` and `best_match` here take
in-memory candidates only, so they are unit-testable without a network call.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

from nutriscrape.resolution.fdc_client import FdcCandidate, FdcClient

# Preference weight by FDC data_type: prefer curated, method-consistent sources (foundation,
# sr_legacy) over survey and branded data, which are noisier for cooked-nutrition composition.
DATA_TYPE_PREFERENCE: Final[dict[str, float]] = {
    "foundation_food": 1.0,
    "sr_legacy_food": 1.0,
    "survey_fndds_food": 0.6,
    "branded_food": 0.3,
}
DEFAULT_DATA_TYPE_PREFERENCE: Final[float] = 0.2

# Relative weights in the composite score. Token overlap dominates because it is the direct
# textual signal against the (normalized) query; data-type preference and FDC's own search
# score are secondary tie-breakers.
TOKEN_OVERLAP_WEIGHT: Final[float] = 0.55
DATA_TYPE_WEIGHT: Final[float] = 0.30
FDC_SCORE_WEIGHT: Final[float] = 0.15

# FDC search scores are unbounded; this divisor puts typical top-hit scores near 1.0 for the
# purpose of blending with the other two normalized [0, 1] signals. Illustrative, not calibrated.
FDC_SCORE_NORMALIZER: Final[float] = 100.0

DEFAULT_THRESHOLD: Final[float] = 0.4

_TOKEN_RE: Final[re.Pattern[str]] = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True)
class ScoredCandidate:
    """An `FdcCandidate` with its composite match score against a query."""

    candidate: FdcCandidate
    score: float
    token_overlap: float
    data_type_preference: float


def _tokenize(text: str) -> set[str]:
    return set(_TOKEN_RE.findall(text.lower()))


def _token_overlap(query_tokens: set[str], candidate_tokens: set[str]) -> float:
    """Jaccard similarity between query and candidate description tokens."""
    if not query_tokens or not candidate_tokens:
        return 0.0
    intersection = query_tokens & candidate_tokens
    union = query_tokens | candidate_tokens
    return len(intersection) / len(union)


def _data_type_preference(data_type: str) -> float:
    return DATA_TYPE_PREFERENCE.get(data_type.lower(), DEFAULT_DATA_TYPE_PREFERENCE)


def _normalized_fdc_score(raw_score: float) -> float:
    if raw_score <= 0.0:
        return 0.0
    return min(1.0, raw_score / FDC_SCORE_NORMALIZER)


def rank_candidates(query: str, candidates: list[FdcCandidate]) -> list[ScoredCandidate]:
    """Score and rank FDC candidates against `query`. Pure, no I/O, unit-testable in isolation.

    Composite score blends token overlap (direct textual match), a data-type preference (prefer
    foundation/sr_legacy over branded/survey), and FDC's own search relevance score. Higher is
    better. Ties are broken by candidate order (stable sort).
    """
    query_tokens = _tokenize(query)
    scored: list[ScoredCandidate] = []
    for candidate in candidates:
        overlap = _token_overlap(query_tokens, _tokenize(candidate.description))
        type_pref = _data_type_preference(candidate.data_type)
        fdc_component = _normalized_fdc_score(candidate.score)
        composite = (
            TOKEN_OVERLAP_WEIGHT * overlap
            + DATA_TYPE_WEIGHT * type_pref
            + FDC_SCORE_WEIGHT * fdc_component
        )
        scored.append(
            ScoredCandidate(
                candidate=candidate,
                score=composite,
                token_overlap=overlap,
                data_type_preference=type_pref,
            )
        )
    return sorted(scored, key=lambda s: s.score, reverse=True)


def best_match(
    query: str, candidates: list[FdcCandidate], threshold: float = DEFAULT_THRESHOLD
) -> ScoredCandidate | None:
    """Return the top-ranked candidate if its composite score clears `threshold`, else None.

    Pure, no I/O. Returning None signals the caller (or a human review queue) that no candidate
    was validated as a confident match; it is never papered over with a guess.
    """
    ranked = rank_candidates(query, candidates)
    if not ranked:
        return None
    top = ranked[0]
    if top.score < threshold:
        return None
    return top


def resolve_food(
    food_str: str, client: FdcClient, threshold: float = DEFAULT_THRESHOLD
) -> ScoredCandidate | None:
    """Normalize-then-validate: query FDC for `food_str` and rank the results against it.

    `food_str` may already be an LLM-normalized ingredient string; this function performs the
    validation half of normalize-then-validate. It never asserts composition itself, only
    identifies (or fails to identify) a canonical FDC match for downstream nutrition code to
    read verbatim values from.
    """
    candidates = client.search(food_str)
    return best_match(food_str, candidates, threshold=threshold)
