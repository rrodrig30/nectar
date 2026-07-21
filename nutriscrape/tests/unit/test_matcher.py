"""Unit tests for the candidate-and-rank matcher. Pure, no network, no fixtures needed.

Covers token overlap ranking, data_type preference (foundation/sr_legacy over branded), and
threshold behavior in `rank_candidates` / `best_match`. See ../../src/nutriscrape/resolution/matcher.py.
"""
from __future__ import annotations

from nutriscrape.resolution.fdc_client import FdcCandidate
from nutriscrape.resolution.matcher import best_match, rank_candidates, stem


def test_stem_singularizes_common_food_plurals() -> None:
    assert stem("eggs") == "egg"
    assert stem("onions") == "onion"
    assert stem("sugars") == "sugar"
    assert stem("potatoes") == "potato"
    assert stem("tomatoes") == "tomato"
    assert stem("berries") == "berry"
    # left alone: short tokens and -ss words
    assert stem("oil") == "oil"
    assert stem("bass") == "bass"


def test_plural_query_matches_singular_food_word() -> None:
    # "eggs" must reach "Egg, whole, raw" over a specialty that carries the exact plural token
    real = _candidate(1, "Egg, whole, raw, fresh")
    specialty = _candidate(2, "Eggs, scrambled, frozen mixture")
    ranked = rank_candidates("eggs", [specialty, real])
    assert ranked[0].candidate.fdc_id == real.fdc_id


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


def test_head_term_beats_specialty_item_on_a_tie() -> None:
    # The real bug: "potatoes" tied "Potatoes, raw, skin" and "Babyfood, potatoes, toddler" on
    # token overlap and data_type; the head-term match must pick the base food.
    raw = _candidate(1, "Potatoes, raw, skin", data_type="sr_legacy_food", score=2.67)
    baby = _candidate(2, "Babyfood, potatoes, toddler", data_type="sr_legacy_food", score=2.67)
    ranked = rank_candidates("potatoes", [baby, raw])  # baby first to prove order does not decide
    assert ranked[0].candidate.fdc_id == raw.fdc_id
    assert ranked[0].head_match == 1.0 and next(r for r in ranked if r.candidate.fdc_id == 2).head_match == 0.0


def test_head_match_is_prefix_tolerant_for_plurals() -> None:
    raw = _candidate(1, "Potatoes, raw, skin")
    baby = _candidate(2, "Babyfood, potatoes, toddler")
    ranked = rank_candidates("potato", [baby, raw])  # singular query, plural description
    assert ranked[0].candidate.fdc_id == raw.fdc_id


def test_raw_form_preferred_over_cooked_on_a_near_tie() -> None:
    # Ingredients are cooked by the transform, so the base food should resolve raw.
    raw = _candidate(1, "Carrots, raw")
    baked = _candidate(2, "Carrots, cooked, boiled, drained, without salt")
    ranked = rank_candidates("carrots", [baked, raw])
    assert ranked[0].candidate.fdc_id == raw.fdc_id


def test_verbose_canonical_food_beats_short_specialty_mock() -> None:
    # The corpus bug: bare "chicken" resolved to "Chicken, meatless" (a short description that beat
    # the verbose canonical food on Jaccard). Coverage + the specialty penalty must pick real chicken.
    real = _candidate(1, "Chicken, broilers or fryers, breast, meat only, raw")
    meatless = _candidate(2, "Chicken, meatless")
    ranked = rank_candidates("chicken", [meatless, real])  # mock first to prove order does not decide
    assert ranked[0].candidate.fdc_id == real.fdc_id
    assert ranked[0].token_overlap == 1.0                  # verbose description covers the query fully


def test_specialty_mock_demoted_only_when_query_did_not_ask_for_it() -> None:
    real = _candidate(1, "Bacon, cured, pan-fried")
    meatless = _candidate(2, "Bacon, meatless")
    # bare "bacon" -> the real cured food, not the meatless analog
    assert rank_candidates("bacon", [meatless, real])[0].candidate.fdc_id == real.fdc_id
    # but an explicit "meatless bacon" -> the meatless analog (the penalty does not apply)
    assert rank_candidates("meatless bacon", [real, meatless])[0].candidate.fdc_id == meatless.fdc_id
