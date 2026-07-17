"""End-to-end clinical golden: ingested recipes form dishes. [INVARIANT] Must pass in CI.

Drives the clustering stage over a fake graph (reads return recipe rows, writes are captured): two
near-identical boiled-potato recipes cluster into one :Dish with two HAS_VERSION links, while a
distinct recipe forms its own dish. This closes the ingest -> cluster loop that gives NECTAR a
queryable Dish -> Recipe -> RecipeVariant -> HAS_NUTRIENT path. See SDD Section 5, PDD Section 7.
"""
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from nutriscrape.pipeline import _run_cluster_with_client

_ROWS: list[dict[str, Any]] = [
    {"recipe_id": "pot_a", "title": "Boiled Potatoes A",
     "foods": [{"fdc_id": "170026", "mass_g": 900.0, "method": "boil"},
               {"fdc_id": "173468", "mass_g": 5.0, "method": "boil"}]},
    {"recipe_id": "pot_b", "title": "Boiled Potatoes B",
     "foods": [{"fdc_id": "170026", "mass_g": 920.0, "method": "boil"},
               {"fdc_id": "173468", "mass_g": 6.0, "method": "boil"}]},
    {"recipe_id": "rice_c", "title": "Plain Rice",
     "foods": [{"fdc_id": "169756", "mass_g": 200.0, "method": "boil"}]},
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

    @contextmanager
    def batch(self) -> Iterator[None]:
        # The real client buffers writes into one transaction; the fake records them directly, so
        # this is a no-op context that still exercises the batched persist path.
        yield


def _has_version_links(client: _FakeGraph) -> dict[str, set[str]]:
    links: dict[str, set[str]] = {}
    for cypher, params in client.writes:
        if "HAS_VERSION" in cypher:
            links.setdefault(params["dish_id"], set()).add(params["recipe_id"])
    return links


def test_ingested_recipes_form_dishes():
    client = _FakeGraph(_ROWS)
    n_dishes = _run_cluster_with_client(client)
    assert n_dishes >= 2
    # a :Dish node was upserted for each cluster
    assert any("MERGE (d:Dish" in cypher for cypher, _ in client.writes)

    links = _has_version_links(client)
    potato_dishes = [d for d, members in links.items() if members == {"pot_a", "pot_b"}]
    rice_dishes = [d for d, members in links.items() if members == {"rice_c"}]
    assert len(potato_dishes) == 1          # the two similar potato recipes share one dish
    assert len(rice_dishes) == 1            # the distinct recipe is its own dish
    assert potato_dishes[0] != rice_dishes[0]


def test_clustering_keeps_distinct_recipes_apart():
    # every recipe here has a different core food, so each is its own dish (finer split)
    rows: list[dict[str, Any]] = [
        {"recipe_id": r, "title": r, "foods": [{"fdc_id": fid, "mass_g": 100.0, "method": "boil"}]}
        for r, fid in (("a", "1"), ("b", "2"), ("c", "3"))
    ]
    client = _FakeGraph(rows)
    n_dishes = _run_cluster_with_client(client)
    assert n_dishes == 3
