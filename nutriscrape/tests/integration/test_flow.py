"""Test the Prefect orchestration DAG: stage order and parallel ingest fan-out.

Runs the real flow in-process with the pipeline stage functions monkeypatched to recorders, so it
validates the DAG structure without a Neo4j / FDC / model backend. Requires Prefect (an optional
dependency), so it is skipped where Prefect is not installed; `make test-int` runs it there.
"""
from __future__ import annotations

import pytest

pytest.importorskip("prefect")

from nutriscrape import pipeline  # noqa: E402
from nutriscrape.acquisition.adapters.base import RawRecipe  # noqa: E402
from nutriscrape.orchestration.flows import nutriscrape_flow  # noqa: E402

_STAGE_FUNCS = ("run_schema", "run_knowledge", "run_fdc_import", "run_cluster", "run_materialize")


def test_flow_orders_stages_and_fans_out_ingest(monkeypatch, tmp_path):
    monkeypatch.setenv("PREFECT_HOME", str(tmp_path))   # isolate Prefect state to the tmp dir
    calls: list[str] = []
    for name in _STAGE_FUNCS:
        monkeypatch.setattr(pipeline, name, (lambda n: lambda: calls.append(n))(name))

    recipes = [
        RawRecipe(recipe_id=f"r{i}", title="T", source_id="s", license="l", servings=4.0,
                  ingredient_lines=("1 egg",), preparation_steps=("Cook.",))
        for i in range(5)
    ]
    monkeypatch.setattr(pipeline, "acquire_recipes", lambda: recipes)
    monkeypatch.setattr(pipeline, "local_resolution_available", lambda: True)

    batches: list[tuple[int, bool]] = []

    def _fake_ingest_batch(batch, use_local):
        batches.append((len(batch), use_local))
        return len(batch)

    monkeypatch.setattr(pipeline, "ingest_batch", _fake_ingest_batch)

    nutriscrape_flow(max_parallel=2)

    # stages run in dependency order: setup first, cluster/materialize last (ingest fans out between)
    assert calls[:3] == ["run_schema", "run_knowledge", "run_fdc_import"]
    assert calls[-2:] == ["run_cluster", "run_materialize"]
    # ingest fanned out into 2 batches covering all 5 recipes, using local resolution
    assert len(batches) == 2
    assert sum(size for size, _ in batches) == 5
    assert all(use_local for _, use_local in batches)
