"""POST /plan/week.

Marshals the admissible-meal pool and plan-level rules into `plan.mealplan.plan_week` and back.
No plan-level rule (energy envelope, fluid ceiling, maintain band) is computed here; this route
only shapes I/O around the pure planner. See ../../docs/PDD.md Section 7, Section 11.
"""
from __future__ import annotations

from fastapi import APIRouter

from nectar.api.schemas import DayPlanOut, MealIn, PlanRequest, PlanResponse
from nectar.engine.recommend import BOUNDARY
from nectar.plan.mealplan import Meal, MaintainRule, PlanRules, plan_week

router = APIRouter()


def _to_meal(m: MealIn) -> Meal:
    return Meal(variant_id=m.variant_id, dish_id=m.dish_id, nutrients=m.nutrients)


def _to_meal_out(m: Meal) -> MealIn:
    return MealIn(variant_id=m.variant_id, dish_id=m.dish_id, nutrients=m.nutrients)


@router.post("/plan/week", response_model=PlanResponse)
def post_plan_week(req: PlanRequest) -> PlanResponse:
    """Weekly meal plan with plan-level constraints (DATA_CONTRACT.md Section 6.3): warfarin
    vitamin K consistency, daily fluid ceilings, daily energy and protein envelopes. Draws only
    from the admissible meal pool the caller supplies; violations are reported, never averaged
    away."""
    pool = [_to_meal(m) for m in req.pool]
    rules = PlanRules(
        energy_min=req.energy_min,
        energy_max=req.energy_max,
        fluid_max_ml=req.fluid_max_ml,
        protein_min=req.protein_min,
        maintain=tuple(MaintainRule(nutrient=m.nutrient, band=m.band) for m in req.maintain),
    )
    week = plan_week(pool, rules, days=req.days, meals_per_day=req.meals_per_day)
    return PlanResponse(
        days=[
            DayPlanOut(meals=[_to_meal_out(m) for m in day.meals], totals=day.totals)
            for day in week.days
        ],
        violations=list(week.violations),
        boundary=BOUNDARY,
    )
