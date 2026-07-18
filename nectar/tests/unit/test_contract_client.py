"""Unit tests for contract-client row reconstruction (no live Neo4j)."""
from nectar.common.contract_client import DishNutrientStat, _dish_stats_from_row


def test_dish_stats_reassembled_from_parallel_arrays():
    # the shape NutriScrape writes on the :Dish node (parallel arrays indexed by stat_nutrient_ids)
    row = {
        "nutrient_ids": ["potassium", "sodium"],
        "count": [4, 4],
        "minimum": [378.0, 491.0],
        "maximum": [964.0, 491.0],
        "mean": [817.0, 491.0],
        "median": [964.0, 491.0],
        "stdev": [254.0, 0.0],
        "units": [{"id": "potassium", "unit": "mg"}, {"id": "sodium", "unit": "mg"}],
    }
    stats = _dish_stats_from_row(row)
    assert set(stats) == {"potassium", "sodium"}
    k = stats["potassium"]
    assert isinstance(k, DishNutrientStat)
    assert k.count == 4 and k.minimum == 378.0 and k.maximum == 964.0 and k.stdev == 254.0
    assert k.unit == "mg"                        # the nutrient's canonical unit, from :Nutrient
    assert stats["sodium"].stdev == 0.0          # identical across versions


def test_dish_without_materialized_stats_returns_empty():
    # a dish that clustered before run_materialize has null stat arrays
    row = {"nutrient_ids": None, "count": None, "minimum": None, "maximum": None,
           "mean": None, "median": None, "stdev": None}
    assert _dish_stats_from_row(row) == {}


def test_inconsistent_arrays_fail_closed():
    row = {"nutrient_ids": ["potassium", "sodium"], "count": [4], "minimum": [378.0],
           "maximum": [964.0], "mean": [817.0], "median": [964.0], "stdev": [254.0]}
    assert _dish_stats_from_row(row) == {}


# --- recipe-browser query sanitizer (dish_name full-text) ---
from nectar.common.contract_client import _lucene_query  # noqa: E402


def test_lucene_query_quotes_terms_and_neutralizes_operators():
    # reserved words (OR) and metacharacters must not break the full-text parser
    assert _lucene_query("chicken soup") == '"chicken" "soup"'
    assert _lucene_query("butter or margarine") == '"butter" "or" "margarine"'
    assert _lucene_query("low-sodium, creamy!") == '"low" "sodium" "creamy"'


def test_lucene_query_empty_for_no_usable_terms():
    assert _lucene_query("") == ""
    assert _lucene_query("   ,;!  ") == ""


# --- recipe-browser ceiling parsing (catalog route helper) ---
from nectar.api.routes.catalog import _parse_ceilings  # noqa: E402
from fastapi import HTTPException  # noqa: E402
import pytest  # noqa: E402


def test_parse_ceilings_builds_nutrient_max_maps():
    assert _parse_ceilings(["potassium:400", "sodium:600"]) == [
        {"nutrient": "potassium", "max": 400.0},
        {"nutrient": "sodium", "max": 600.0},
    ]
    assert _parse_ceilings([]) == []


def test_parse_ceilings_rejects_malformed():
    for bad in ["potassium", "potassium:", ":400", "potassium:high"]:
        with pytest.raises(HTTPException):
            _parse_ceilings([bad])
