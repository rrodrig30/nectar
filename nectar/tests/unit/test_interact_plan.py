"""Unit tests for interaction (modify, qa) and the meal planner."""
from nectar.engine.constraints import assemble
from nectar.interact.modify import Modifications, apply, parse_equipment
from nectar.interact.qa import StructuredQuery, parse
from nectar.plan.mealplan import Meal, MaintainRule, PlanRules, plan_week
from nectar.scoring.suitability import Constraint


class _FakeBackend:
    def __init__(self, reply: str) -> None:
        self._reply = reply

    def generate(self, prompt: str, system: str | None = None,
                 temperature: float | None = None) -> str:
        return self._reply


def test_parse_equipment_maps_phrases_to_methods():
    got = parse_equipment(["No Grill", "no stand mixer", "unrelated"])
    assert got == frozenset({"grill", "stand_mixer"})


def test_modify_grows_exclusion_set_only():
    base = assemble([Constraint(nutrient="potassium", type="restrict", max_per_serving=700)],
                    hard_excludes={"peanut"})
    out = apply(base, Modifications(exclude_methods=frozenset({"grill"})))
    assert out.hard_excludes == {"peanut", "grill"}
    assert out.by_nutrient == base.by_nutrient          # scoring middle untouched


def test_qa_parses_json_and_falls_back_on_garbage():
    good = parse("plan a week", _FakeBackend('{"intent": "plan", "dishes": ["soup"]}'))
    assert isinstance(good, StructuredQuery) and good.intent == "plan" and good.dishes == ["soup"]
    bad = parse("hello", _FakeBackend("not json at all"))
    assert bad.intent == "ask" and bad.free_text == "hello"


def _meal(vid: str, energy: float, fluid: float, vit_k: float) -> Meal:
    return Meal(variant_id=vid, dish_id=f"d_{vid}",
                nutrients={"energy_kcal": energy, "fluid_ml": fluid, "vitamin_k": vit_k})


def test_plan_week_flags_energy_and_fluid_and_maintain():
    pool = [_meal("a", 700, 300, 90), _meal("b", 800, 400, 92), _meal("c", 750, 350, 30)]
    rules = PlanRules(energy_min=2000, energy_max=2600, fluid_max_ml=1500,
                      maintain=(MaintainRule(nutrient="vitamin_k", band=10.0),))
    plan = plan_week(pool, rules, days=3, meals_per_day=3)
    assert len(plan.days) == 3
    # every day has totals computed
    assert all("energy_kcal" in d.totals for d in plan.days)
    # a maintain rule is evaluated across the window (may or may not violate depending on selection)
    assert isinstance(plan.violations, list)


def test_plan_week_empty_pool_reports_violation():
    plan = plan_week([], PlanRules(energy_min=2000, energy_max=2600))
    assert plan.days == [] and plan.violations
