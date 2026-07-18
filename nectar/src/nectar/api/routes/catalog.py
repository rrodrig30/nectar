"""GET /dishes/search, GET /conditions - read-only catalog lookups for the clinician UI.

Dish discovery (search by name) and the condition list are reads the UI needs before it can build
a `/recommend` request. They only marshal I/O: call the read-only contract client and shape rows
into response models. No clinical literal or scoring rule lives here (invariants in ../../CLAUDE.md).
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from nectar.api.deps import get_contract_client
from nectar.api.schemas import (
    BrowseDishOut,
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


def _parse_ceilings(raw: list[str]) -> list[dict[str, Any]]:
    """Parse `nutrient:max` filter strings (e.g. `potassium:400`) into `{nutrient, max}` maps.
    A malformed or non-numeric entry is a client error, not silently dropped."""
    out: list[dict[str, Any]] = []
    for item in raw:
        nutrient, _, value = item.partition(":")
        nutrient = nutrient.strip()
        if not nutrient or not value.strip():
            raise HTTPException(status_code=422, detail=f"bad ceiling {item!r}; use nutrient:max")
        try:
            out.append({"nutrient": nutrient, "max": float(value)})
        except ValueError as exc:
            raise HTTPException(
                status_code=422, detail=f"non-numeric ceiling in {item!r}"
            ) from exc
    return out


@router.get("/dishes/browse", response_model=list[BrowseDishOut])
def get_dishes_browse(
    q: str = Query(min_length=1, description="Full-text dish-name query (required)"),
    max: list[str] = Query(  # noqa: A002 - matches the query-string name the UI sends
        default_factory=list,
        description="Per-serving nutrient ceilings as nutrient:mg (e.g. potassium:400)",
    ),
    sort: str = Query(default="", description="nutrient_id to sort by (ascending median), or blank"),
    limit: int = Query(default=30, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    client: ContractClient = Depends(get_contract_client),
) -> list[BrowseDishOut]:
    """Browse dishes for meal ideas that meet a patient's needs: full-text name match refined by
    per-serving nutrient ceilings (a dish qualifies when a version is at or below each ceiling) and
    sorted by a nutrient or by name relevance. Read-only; a name term is required so the query uses
    the dish_name full-text index instead of scanning the whole corpus."""
    rows = client.browse_dishes(q, _parse_ceilings(max), sort, limit, offset)
    return [BrowseDishOut(**row) for row in rows]


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
