"""Unit tests for the parallel-ingest building blocks: batching and per-batch ingest (no Prefect)."""
from typing import Any

from nutriscrape import pipeline
from nutriscrape.acquisition.adapters.base import RawRecipe


def _recipes(n: int) -> list[RawRecipe]:
    return [
        RawRecipe(recipe_id=f"r{i}", title="T", source_id="s", license="l", servings=4.0,
                  ingredient_lines=("2 pounds potatoes",), preparation_steps=("Boil.",))
        for i in range(n)
    ]


def test_split_into_batches():
    items = _recipes(5)
    assert [len(batch) for batch in pipeline.split_into_batches(items, 2)] == [3, 2]
    assert pipeline.split_into_batches([], 3) == []
    # never more batches than items
    assert len(pipeline.split_into_batches(items, 10)) == 5


class _CmGraph:
    """A context-manager fake GraphClient serving the local-resolution reads and capturing writes."""

    def __init__(self) -> None:
        self.writes: list[tuple[str, dict[str, Any]]] = []

    def __enter__(self) -> "_CmGraph":
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def run(self, cypher: str, **params: Any) -> list[dict[str, Any]]:
        if "queryNodes" in cypher:
            return [{"fdc_id": "170026", "description": "Potatoes",
                     "data_type": "sr_legacy_food", "score": 5.0}]
        if "HAS_NUTRIENT_RAW" in cypher and "RETURN n.nutrient_id" in cypher:
            return [{"nutrient_id": "potassium", "amount": 425.0}]
        return []

    def run_write(self, cypher: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        self.writes.append((cypher, params))
        return []


def test_ingest_batch_uses_local_resolution_and_writes(monkeypatch):
    graph = _CmGraph()
    monkeypatch.setattr(pipeline.GraphClient, "from_env", lambda: graph)
    count = pipeline.ingest_batch(_recipes(2), use_local=True)
    assert count == 2
    # cooked per-serving nutrients were written (resolved and re-cooked from the graph's raw vector)
    assert any("amount_per_serving" in params for _cypher, params in graph.writes)
