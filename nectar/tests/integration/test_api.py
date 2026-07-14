"""Integration test for the FastAPI wiring: /profile/derive -> /profile/confirm -> /recommend.

No live Neo4j or LLM backend is used: `get_contract_client` and `get_llm_backend` are overridden
with an in-memory fake graph and a fake text backend via `app.dependency_overrides`. This exercises
the real route/schema/engine wiring end to end while staying a fast, hermetic unit-style test.

[INVARIANT] Every recommendation response carries the `boundary` string and per-value
calculated-not-measured flags (DATA_CONTRACT.md Section 7; nectar/docs/PDD.md Section 11).
[INVARIANT] No unconfirmed constraint may reach the engine; posting one to `/recommend` must be
rejected with a 4xx, never crash the process as a 500 (nectar/docs/PDD.md Section 12).
"""
from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from nectar.api.app import create_app
from nectar.api.deps import get_contract_client, get_llm_backend
from nectar.common.contract_client import DishNutrientStat
from nectar.engine.constraints import VariantFacts
from nectar.scoring.suitability import Constraint

_SNAPSHOT: dict[str, object] = {
    "pmh": ["ckd"],
    "metabolic_panel": {"K": 5.4, "Cr": 1.8},
    "cbc": {"Hgb": 13.0, "ANC": 3000},
    "medications": [],
    "allergies": [],
    "age": 67,
    "sex": "M",
    "weight_kg": 80.0,
    "height_cm": 175.0,
    "activity_level": "sedentary",
    "goal": "cardiovascular improvement",
}


class _FakeContractClient:
    """A tiny in-memory stand-in for `ContractClient`: one condition's rule, one dish's two
    variants (one admissible, one breaching the potassium hard limit), nothing else."""

    def constraints_for_condition(self, condition_id: str) -> list[Constraint]:
        if condition_id == "ckd":
            return [
                Constraint(
                    nutrient="potassium",
                    type="restrict",
                    max_per_serving=700.0,
                    hard_limit=1000.0,
                    safety_critical=True,
                    guideline_id="kdoqi-potassium",
                )
            ]
        return []

    def variants_for_dish(self, dish_id: str) -> list[VariantFacts]:
        if dish_id == "mashed_potatoes":
            return [
                VariantFacts(variant_id="v1", dish_id=dish_id, nutrients={"potassium": 500.0}),
                VariantFacts(variant_id="v2", dish_id=dish_id, nutrients={"potassium": 1200.0}),
            ]
        return []

    def dish_nutrient_stats(self, dish_id: str) -> dict[str, DishNutrientStat]:
        if dish_id == "mashed_potatoes":
            return {
                "potassium": DishNutrientStat(
                    nutrient="potassium", count=2, minimum=500.0, maximum=1200.0,
                    mean=850.0, median=850.0, stdev=350.0, unit="mg",
                )
            }
        return {}


class _FakeLLMBackend:
    """Text in, text out, never a nutrient number. Not exercised by the derive/confirm/recommend
    path below (only `/ask` calls the backend), but wired in so no test in this module can
    accidentally reach a live LLM if the route set changes."""

    def generate(
        self, prompt: str, system: str | None = None, temperature: float | None = None
    ) -> str:
        return '{"intent": "ask", "dishes": [], "exclude": [], "free_text": ""}'


@pytest.fixture()
def client() -> Iterator[TestClient]:
    app = create_app()
    app.dependency_overrides[get_contract_client] = lambda: _FakeContractClient()
    app.dependency_overrides[get_llm_backend] = lambda: _FakeLLMBackend()
    with TestClient(app) as test_client:
        yield test_client


def test_derive_confirm_recommend_end_to_end(client: TestClient) -> None:
    derive_resp = client.post("/profile/derive", json=_SNAPSHOT)
    assert derive_resp.status_code == 200
    derived = derive_resp.json()["constraints"]
    assert derived, "serum K 5.4 and Cr 1.8 should each derive a constraint"
    assert all(c["confirmed"] is False for c in derived)

    approvals = {i: True for i in range(len(derived))}
    confirm_resp = client.post(
        "/profile/confirm", json={"constraints": derived, "approvals": approvals}
    )
    assert confirm_resp.status_code == 200
    confirmed = confirm_resp.json()["confirmed"]
    assert len(confirmed) == len(derived)
    assert all(c["confirmed"] is True for c in confirmed)

    recommend_resp = client.post(
        "/recommend",
        json={
            "confirmed": confirmed,
            "condition_ids": ["ckd"],
            "dish_ids": ["mashed_potatoes"],
        },
    )
    assert recommend_resp.status_code == 200
    body = recommend_resp.json()

    assert body["boundary"], "[INVARIANT] every recommendation response carries a boundary"

    rankings = body["rankings"]
    assert len(rankings) == 1 and rankings[0]["dish_id"] == "mashed_potatoes"
    best = rankings[0]["best"]
    assert best is not None
    assert best["variant_id"] == "v1", "v2 breaches the potassium hard limit and must be excluded"
    assert best["admissible"] is True and best["contraindicated"] is False

    assert best["nutrients"], "the admissible variant's nutrient vector must be disclosed"
    for nutrient_value in best["nutrients"]:
        assert nutrient_value["measured"] is False
        assert nutrient_value["disclaimer"], "[INVARIANT] calculated-not-measured disclaimer"

    # v2 is excluded from the dish's own ranked versions, not silently averaged in
    version_ids = {v["variant_id"] for v in rankings[0]["versions"]}
    assert version_ids == {"v1"}

    # the dish-level nutrient distribution (contract Section 5) is surfaced on the ranking,
    # each value presented (rounded + labeled) through present.units.nutrient_amount
    stats = rankings[0]["nutrient_stats"]
    assert "potassium" in stats
    assert stats["potassium"]["minimum"] == 500.0 and stats["potassium"]["maximum"] == 1200.0
    assert stats["potassium"]["count"] == 2
    assert stats["potassium"]["unit"] == "mg"     # nutrient amounts stay label-style (mg), not oz


def test_recommend_rejects_unconfirmed_constraint_set(client: TestClient) -> None:
    unconfirmed = [
        {
            "source_signal": "serum K 5.4",
            "direction": "limit",
            "target": "potassium",
            "severity": "strong",
            "confirmed": False,
        }
    ]
    resp = client.post(
        "/recommend",
        json={
            "confirmed": unconfirmed,
            "condition_ids": ["ckd"],
            "dish_ids": ["mashed_potatoes"],
        },
    )
    assert resp.status_code == 422, "an unconfirmed constraint must be rejected, not a 500"
