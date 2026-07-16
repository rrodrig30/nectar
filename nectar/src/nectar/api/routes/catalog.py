"""GET /dishes/search, GET /conditions - read-only catalog lookups for the clinician UI.

Dish discovery (search by name) and the condition list are reads the UI needs before it can build
a `/recommend` request. They only marshal I/O: call the read-only contract client and shape rows
into response models. No clinical literal or scoring rule lives here (invariants in ../../CLAUDE.md).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from nectar.api.deps import get_contract_client
from nectar.api.schemas import (
    ConditionOut,
    DishSummaryOut,
    GuidelineOut,
    NutrientInfoOut,
    RecipeDetailOut,
)
from nectar.common.contract_client import ContractClient

router = APIRouter()


@router.get("/dishes/search", response_model=list[DishSummaryOut])
def get_dishes_search(
    q: str = Query(min_length=1, description="Case-insensitive substring of the dish name"),
    limit: int = Query(default=20, ge=1, le=50),
    client: ContractClient = Depends(get_contract_client),
) -> list[DishSummaryOut]:
    """Dishes whose canonical_name contains `q`, bounded by `limit`. Read-only."""
    return [DishSummaryOut(**row) for row in client.search_dishes(q, limit)]


@router.get("/conditions", response_model=list[ConditionOut])
def get_conditions(
    client: ContractClient = Depends(get_contract_client),
) -> list[ConditionOut]:
    """Every `:Condition` in the knowledge base, for the condition selector."""
    return [ConditionOut(**row) for row in client.list_conditions()]


@router.get("/guidelines", response_model=list[GuidelineOut])
def get_guidelines(
    ids: list[str] = Query(default_factory=list, description="Guideline ids to retrieve"),
    client: ContractClient = Depends(get_contract_client),
) -> list[GuidelineOut]:
    """Guideline passages by id, for the evidence panel behind a recommendation. Read-only; returns
    only the ids that resolve to a loaded `:Guideline` node (unresolved citation refs are omitted)."""
    if not ids:
        return []
    return [GuidelineOut(**row) for row in client.guideline_passages(ids)]


@router.get("/nutrients", response_model=list[NutrientInfoOut])
def get_nutrients(
    client: ContractClient = Depends(get_contract_client),
) -> list[NutrientInfoOut]:
    """The nutrient vocabulary (id, name, unit), so the UI can label nutrient values."""
    return [NutrientInfoOut(**row) for row in client.list_nutrients()]


@router.get("/recipe", response_model=RecipeDetailOut)
def get_recipe(
    dish_id: str = Query(min_length=1, description="Dish id to fetch the primary recipe for"),
    client: ContractClient = Depends(get_contract_client),
) -> RecipeDetailOut:
    """The primary recipe for a dish - title, servings, provenance, ingredients with preparation.
    404 when the dish has no recipe. Read-only."""
    recipe = client.recipe_for_dish(dish_id)
    if recipe is None:
        raise HTTPException(status_code=404, detail=f"no recipe for dish {dish_id!r}")
    return RecipeDetailOut(**recipe)
