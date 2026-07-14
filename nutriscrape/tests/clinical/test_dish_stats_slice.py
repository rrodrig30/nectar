"""End-to-end clinical golden: per-dish nutrient distribution stats. [INVARIANT] Must pass in CI.

Drives the dish-statistics step over a fake graph that serves the cooked nutrient amounts across a
dish's versions and captures the write. A potato dish with a drained version (378 mg K) and baked
versions (964 mg K) gets its potassium spread materialized on the :Dish, so NECTAR can see the
version range without re-reading every variant. See DATA_CONTRACT Section 5.
"""
from typing import Any

from nutriscrape.pipeline import _run_dish_stats_with_client

_ROWS: list[dict[str, Any]] = [
    {"dish_id": "dish:boiled_potatoes", "nutrient_id": "potassium",
     "amounts": [378.0, 964.0, 964.0]},
    {"dish_id": "dish:boiled_potatoes", "nutrient_id": "sodium",
     "amounts": [491.0, 491.0, 491.0]},
]


class _FakeGraph:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows
        self.writes: list[tuple[str, dict[str, Any]]] = []

    def run(self, cypher: str, **params: Any) -> list[dict[str, Any]]:
        return self._rows

    def run_write(self, cypher: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        self.writes.append((cypher, params))
        return []


def test_dish_nutrient_distribution_is_materialized():
    client = _FakeGraph(_ROWS)
    n_dishes = _run_dish_stats_with_client(client)
    assert n_dishes == 1

    stat_writes = [p for c, p in client.writes if "nutrient_ids" in p]
    assert len(stat_writes) == 1
    params = stat_writes[0]
    assert params["dish_id"] == "dish:boiled_potatoes"

    ids = params["nutrient_ids"]
    assert ids == ["potassium", "sodium"]                 # sorted, parallel-array indexed
    k = ids.index("potassium")
    assert params["count"][k] == 3
    assert params["minimum"][k] == 378.0 and params["maximum"][k] == 964.0
    assert params["stdev"][k] > 0.0                       # the versions genuinely spread
    s = ids.index("sodium")
    assert params["stdev"][s] == 0.0                      # identical across versions


def test_dish_stats_no_op_without_variants():
    client = _FakeGraph([])
    assert _run_dish_stats_with_client(client) == 0
    assert client.writes == []
