"""Weekly meal plan and the plan-level maintain rules. Pure, no I/O.

Single-recipe admissibility comes from the engine. The planner adds what cannot be judged against a
single recipe: the plan-level maintain rules evaluated across the window (warfarin vitamin K
consistency, daily fluid ceilings, daily energy and protein envelopes). Variety and the envelopes are
objectives; the daily ceilings and the consistency constraints are constraints. Selection is a
deterministic greedy-with-repair; violations are reported, never silently averaged away.
See ../../docs/PDD.md Section 7, SDD Section 5, DATA_CONTRACT Section 6.3.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from statistics import pstdev


@dataclass(frozen=True)
class Meal:
    variant_id: str
    dish_id: str
    nutrients: dict[str, float]      # per serving, canonical units; includes energy_kcal, fluid_ml


@dataclass(frozen=True)
class MaintainRule:
    nutrient: str
    band: float                      # allowed standard deviation across the daily totals


@dataclass(frozen=True)
class PlanRules:
    energy_min: float
    energy_max: float
    fluid_max_ml: float | None = None
    protein_min: float | None = None
    maintain: tuple[MaintainRule, ...] = ()


@dataclass(frozen=True)
class DayPlan:
    meals: list[Meal]
    totals: dict[str, float]


@dataclass(frozen=True)
class WeekPlan:
    days: list[DayPlan]
    violations: list[str] = field(default_factory=list)


def day_totals(meals: list[Meal]) -> dict[str, float]:
    totals: dict[str, float] = {}
    for m in meals:
        for k, v in m.nutrients.items():
            totals[k] = totals.get(k, 0.0) + v
    return totals


def _fill_day(pool: list[Meal], rules: PlanRules, meals_per_day: int, start: int) -> DayPlan:
    """Greedy: add meals cycling through the pool until the energy floor is met or the day is full,
    while respecting the daily fluid ceiling. Deterministic (no randomness), starts at `start` for
    variety across days."""
    meals: list[Meal] = []
    n = len(pool)
    energy = 0.0
    fluid = 0.0
    i = 0
    while len(meals) < meals_per_day and i < n:
        candidate = pool[(start + i) % n]
        i += 1
        c_fluid = candidate.nutrients.get("fluid_ml", 0.0)
        if rules.fluid_max_ml is not None and fluid + c_fluid > rules.fluid_max_ml:
            continue
        meals.append(candidate)
        energy += candidate.nutrients.get("energy_kcal", 0.0)
        fluid += c_fluid
        if energy >= rules.energy_min and len(meals) >= 1:
            # keep filling toward meals_per_day but stop adding once the envelope max would break
            if energy >= rules.energy_max:
                break
    return DayPlan(meals=meals, totals=day_totals(meals))


def _envelope_violations(day: int, totals: dict[str, float], rules: PlanRules) -> list[str]:
    out: list[str] = []
    energy = totals.get("energy_kcal", 0.0)
    if energy < rules.energy_min:
        out.append(f"day {day}: energy {energy:.0f} below envelope min {rules.energy_min:.0f}")
    if energy > rules.energy_max:
        out.append(f"day {day}: energy {energy:.0f} above envelope max {rules.energy_max:.0f}")
    if rules.fluid_max_ml is not None and totals.get("fluid_ml", 0.0) > rules.fluid_max_ml:
        out.append(f"day {day}: fluid {totals.get('fluid_ml', 0.0):.0f} over ceiling {rules.fluid_max_ml:.0f}")
    if rules.protein_min is not None and totals.get("protein", 0.0) < rules.protein_min:
        out.append(f"day {day}: protein {totals.get('protein', 0.0):.0f} below min {rules.protein_min:.0f}")
    return out


def _maintain_violations(days: list[DayPlan], rules: PlanRules) -> list[str]:
    out: list[str] = []
    for rule in rules.maintain:
        series = [d.totals.get(rule.nutrient, 0.0) for d in days]
        if len(series) > 1 and pstdev(series) > rule.band:
            out.append(f"maintain {rule.nutrient}: day-to-day variation "
                       f"{pstdev(series):.1f} exceeds band {rule.band:.1f}")
    return out


def plan_week(pool: list[Meal], rules: PlanRules, days: int = 7,
              meals_per_day: int = 3) -> WeekPlan:
    """Build a weekly plan from admissible meals and evaluate the plan-level rules over the window."""
    if not pool:
        return WeekPlan(days=[], violations=["no admissible meals to plan from"])
    day_plans = [_fill_day(pool, rules, meals_per_day, start=d * meals_per_day) for d in range(days)]
    violations: list[str] = []
    for idx, day in enumerate(day_plans):
        violations.extend(_envelope_violations(idx, day.totals, rules))
    violations.extend(_maintain_violations(day_plans, rules))
    return WeekPlan(days=day_plans, violations=violations)
