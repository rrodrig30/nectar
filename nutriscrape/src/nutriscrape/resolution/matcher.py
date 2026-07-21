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
# textual signal against the (normalized) query; the head-term match distinguishes the base food
# from a specialty item that merely mentions it; data-type preference and FDC's own search score
# are secondary tie-breakers.
TOKEN_OVERLAP_WEIGHT: Final[float] = 0.45
HEAD_MATCH_WEIGHT: Final[float] = 0.25
DATA_TYPE_WEIGHT: Final[float] = 0.20
FDC_SCORE_WEIGHT: Final[float] = 0.10

# FDC descriptions lead with the primary food ("Potatoes, raw, skin"). A description led by a
# category word ("Babyfood, potatoes, toddler"; "Restaurant, ...") is a specialty item that only
# mentions the queried food, not the base ingredient. Without this signal the two tie on token
# overlap and data_type and the arbitrary tie-break can pick the specialty item.
_MIN_HEAD_TOKEN: Final[int] = 3

# Ingredients enter a recipe raw and are cooked by the four-channel transform, so the base food
# should resolve raw; a pre-cooked candidate ("Potatoes, baked") would double-count the recipe's
# own method. A small bonus, enough only to break a near-tie in favor of the raw form.
RAW_PREFERENCE_BONUS: Final[float] = 0.04

# Non-equivalent specialty products whose short FDC descriptions ("Bacon, meatless", "Babyfood,
# ...") outscore the verbose canonical food on text alone. A recipe calling for "bacon" almost never
# means the meatless analog, yet the analog was resolved 64k+ times across the corpus, understating
# real composition. Demote such a candidate UNLESS the query itself asked for it (so an explicit
# "meatless bacon" is unaffected). The penalty clears the ~0.9 a same-food tie reaches.
SPECIALTY_TERMS: Final[frozenset[str]] = frozenset(
    {"meatless", "imitation", "substitute", "babyfood"}
)
SPECIALTY_PENALTY: Final[float] = 0.25

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
    head_match: float = 0.0


def stem(token: str) -> str:
    """Crude singularization so a query word matches the FDC food word across plural/singular forms
    ("eggs" vs "Egg, whole", "sugar" vs "Sugars, granulated", "potatoes" vs "Potatoes, raw"). Without
    it, exact-token comparison misses the base food and a specialty variant that happens to carry the
    exact word wins (query "eggs" -> "Eggs, scrambled, frozen" over "Egg, whole, raw"). Linguistic
    precision is not the goal: query and index are stemmed the same way, so a consistent over-strip
    still matches. Short tokens and -ss words (bass, molasses) are left alone."""
    if len(token) <= 3 or token.endswith("ss"):
        return token
    if token.endswith("ies"):
        return token[:-3] + "y"                 # berries -> berry
    if token.endswith("es") and token[-3] in "shxzo":
        return token[:-2]                       # tomatoes -> tomato, dishes -> dish
    if token.endswith("s"):
        return token[:-1]                       # eggs -> egg, onions -> onion, sugars -> sugar
    return token


def _tokenize(text: str) -> set[str]:
    return {stem(t) for t in _TOKEN_RE.findall(text.lower())}


def _token_overlap(query_tokens: set[str], candidate_tokens: set[str]) -> float:
    """Fraction of the query's tokens the candidate covers (recall of the query).

    This replaced Jaccard, which divided by the union and so penalized a verbose canonical FDC
    description ("Chicken, broilers or fryers, breast, meat only, raw") relative to a short specialty
    one ("Chicken, meatless") that merely shares the word. Recall does not penalize the extra
    descriptive tokens of the real food, so the base ingredient is not lost; the head-term match,
    raw preference, and specialty penalty then decide among candidates that fully cover the query.
    """
    if not query_tokens or not candidate_tokens:
        return 0.0
    return len(query_tokens & candidate_tokens) / len(query_tokens)


def _specialty_penalty(query_tokens: set[str], candidate_tokens: set[str]) -> float:
    """Demote a non-equivalent specialty product the query did not ask for (see SPECIALTY_TERMS).
    Zero when the specialty term is also in the query, so an explicit "meatless bacon" is kept."""
    if (SPECIALTY_TERMS & candidate_tokens) - query_tokens:
        return -SPECIALTY_PENALTY
    return 0.0


def _data_type_preference(data_type: str) -> float:
    return DATA_TYPE_PREFERENCE.get(data_type.lower(), DEFAULT_DATA_TYPE_PREFERENCE)


def _head_match(query_tokens: set[str], description: str) -> float:
    """1.0 if the candidate's leading (primary-food) term matches a query token, else 0.0.

    `query_tokens` are already stemmed (via `_tokenize`); the head is stemmed here too so a plural
    query and a singular food word (or vice versa) align. Matching stays prefix-tolerant as a
    backstop. Short leading tokens are ignored to avoid spurious matches.
    """
    head_tokens = _TOKEN_RE.findall(description.lower())
    if not head_tokens:
        return 0.0
    head = stem(head_tokens[0])
    if len(head) < _MIN_HEAD_TOKEN:
        return 0.0
    for token in query_tokens:
        if len(token) >= _MIN_HEAD_TOKEN and (head.startswith(token) or token.startswith(head)):
            return 1.0
    return 0.0


def _raw_preference(candidate_tokens: set[str]) -> float:
    return RAW_PREFERENCE_BONUS if "raw" in candidate_tokens else 0.0


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
        candidate_tokens = _tokenize(candidate.description)
        overlap = _token_overlap(query_tokens, candidate_tokens)
        head = _head_match(query_tokens, candidate.description)
        type_pref = _data_type_preference(candidate.data_type)
        fdc_component = _normalized_fdc_score(candidate.score)
        composite = (
            TOKEN_OVERLAP_WEIGHT * overlap
            + HEAD_MATCH_WEIGHT * head
            + DATA_TYPE_WEIGHT * type_pref
            + FDC_SCORE_WEIGHT * fdc_component
            + _raw_preference(candidate_tokens)
            + _specialty_penalty(query_tokens, candidate_tokens)
        )
        scored.append(
            ScoredCandidate(
                candidate=candidate,
                score=composite,
                token_overlap=overlap,
                data_type_preference=type_pref,
                head_match=head,
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
