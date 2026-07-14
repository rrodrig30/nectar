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
