"""Unit tests for the candidate-and-rank matcher. Pure, no network, no fixtures needed.

Covers token overlap ranking, data_type preference (foundation/sr_legacy over branded), and
threshold behavior in `rank_candidates` / `best_match`. See ../../src/nutriscrape/resolution/matcher.py.
"""
from __future__ import annotations

from nutriscrape.resolution.fdc_client import FdcCandidate
from nutriscrape.resolution.matcher import best_match, rank_candidates


def _candidate(
    fdc_id: int, description: str, data_type: str = "sr_legacy_food", score: float = 0.0
) -> FdcCandidate:
    return FdcCandidate(fdc_id=fdc_id, description=description, data_type=data_type, score=score)


def test_rank_candidates_orders_by_token_overlap() -> None:
    query = "raw russet potato"
    candidates = [
        _candidate(1, "Potato, russet, raw"),
        _candidate(2, "Broccoli, raw"),
        _candidate(3, "Potato salad with mayonnaise"),
    ]
    ranked = rank_candidates(query, candidates)
    assert [r.candidate.fdc_id for r in ranked][0] == 1
    # exact/near token match must score strictly above an unrelated candidate
    top = ranked[0]
    broccoli = next(r for r in ranked if r.candidate.fdc_id == 2)
    assert top.score > broccoli.score
    assert top.token_overlap > broccoli.token_overlap


def test_rank_candidates_empty_query_or_candidates() -> None:
    assert rank_candidates("potato", []) == []
    ranked = rank_candidates("", [_candidate(1, "Potato, raw")])
    assert ranked[0].token_overlap == 0.0


def test_rank_candidates_prefers_foundation_and_sr_legacy_over_branded() -> None:
    query = "cheddar cheese"
    branded = _candidate(1, "Cheddar Cheese", data_type="branded_food", score=50.0)
    foundation = _candidate(2, "Cheddar Cheese", data_type="foundation_food", score=50.0)
    ranked = rank_candidates(query, [branded, foundation])
    # identical text and FDC score: data_type preference must decide the order
    assert ranked[0].candidate.fdc_id == foundation.fdc_id
    assert ranked[0].data_type_preference > ranked[1].data_type_preference
    assert ranked[0].score > ranked[1].score


def test_rank_candidates_survey_between_legacy_and_branded() -> None:
    sr_legacy = _candidate(1, "match", data_type="sr_legacy_food")
    survey = _candidate(2, "match", data_type="survey_fndds_food")
    branded = _candidate(3, "match", data_type="branded_food")
    ranked = rank_candidates("match", [sr_legacy, survey, branded])
    scores_by_id = {r.candidate.fdc_id: r.score for r in ranked}
    assert scores_by_id[1] > scores_by_id[2] > scores_by_id[3]


def test_rank_candidates_fdc_score_breaks_ties_within_same_data_type() -> None:
    low = _candidate(1, "roasted chicken breast", data_type="sr_legacy_food", score=10.0)
    high = _candidate(2, "roasted chicken breast", data_type="sr_legacy_food", score=90.0)
    ranked = rank_candidates("roasted chicken breast", [low, high])
    assert ranked[0].candidate.fdc_id == high.fdc_id


def test_best_match_returns_top_candidate_above_threshold() -> None:
    candidates = [
        _candidate(1, "Potato, russet, raw", data_type="sr_legacy_food"),
        _candidate(2, "Broccoli, raw", data_type="sr_legacy_food"),
    ]
    match = best_match("raw russet potato", candidates, threshold=0.3)
    assert match is not None
    assert match.candidate.fdc_id == 1


def test_best_match_returns_none_when_below_threshold() -> None:
    candidates = [_candidate(1, "Broccoli, raw", data_type="branded_food")]
    match = best_match("raw russet potato", candidates, threshold=0.9)
    assert match is None


def test_best_match_returns_none_for_no_candidates() -> None:
    assert best_match("anything", [], threshold=0.0) is None


def test_best_match_threshold_is_inclusive_boundary() -> None:
    candidates = [_candidate(1, "exact match text", data_type="sr_legacy_food")]
    ranked = rank_candidates("exact match text", candidates)
    exact_score = ranked[0].score
    # at the boundary score itself, best_match must accept (score < threshold excludes, not <=)
    match = best_match("exact match text", candidates, threshold=exact_score)
    assert match is not None
