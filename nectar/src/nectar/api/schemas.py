"""Request/response models for the HTTP surface. Every recommendation carries boundary + citations.

These models marshal between JSON and the pure domain types already defined in `abstraction/`,
`engine/`, `plan/`, `interact/`, and `research/`. No clinical literal, threshold, or scoring rule is
defined here; this module only shapes I/O. Where a domain type is already a pydantic model
(`nectar.interact.qa.StructuredQuery`, `nectar.research.hypotheses.HypothesisSurfaceResult`,
`nectar.research.writeback_service.AuditEntry`/`MeasurementRecord`), routes reuse it directly
instead of a duplicate wrapper defined here.

[INVARIANT] Every recommendation response (`RecommendResponse`, `PlanResponse`) carries a
`boundary` string, and every nutrient value it returns carries a calculated-not-measured flag
(`NutrientValueOut.measured` / `.disclaimer`), per DATA_CONTRACT.md Section 7 and
../../docs/PDD.md Section 11.
See ../../docs/PDD.md. Invariants in ../../CLAUDE.md apply.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from nectar.abstraction.derive import Direction
from nectar.research.writeback_service import MeasurementRecord, TargetKind
from nectar_contract.types import EvidenceTier

# ---------------------------------------------------------------------------
# Derived constraints (abstraction/derive.py, abstraction/confirm.py)
# ---------------------------------------------------------------------------


class DerivedConstraintIn(BaseModel):
    """Wire shape of one `abstraction.derive.DerivedConstraint`, as sent back by the client after
    `/profile/derive` (unconfirmed) or `/profile/confirm` (confirmed). The physician-facing
    confirmation gate is enforced downstream by `engine.constraints.require_confirmed`; this model
    only carries the flag, it does not itself gate anything."""

    source_signal: str
    direction: Direction
    target: str
    severity: str
    value: float | None = None
    unit: str | None = None
    formula: str | None = None
    guideline_id: str | None = None
    confirmed: bool = False


class DerivedConstraintOut(BaseModel):
    """Response mirror of `abstraction.derive.DerivedConstraint`, built with `from_attributes` so
    it can be constructed directly from the dataclass instance."""

    model_config = ConfigDict(from_attributes=True)

    source_signal: str
    direction: Direction
    target: str
    severity: str
    value: float | None = None
    unit: str | None = None
    formula: str | None = None
    guideline_id: str | None = None
    confirmed: bool = False


class ReviewItemOut(BaseModel):
    """Mirror of one `abstraction.confirm.as_review_items` entry: what was derived, and why, for
    the physician confirmation UI."""

    index: int
    source_signal: str
    target: str
    direction: str
    severity: str
    value: float | None = None
    unit: str | None = None
    formula: str | None = None


class DeriveRequest(BaseModel):
    """The de-identified clinical snapshot payload for `/profile/derive`.

    `extra="allow"` is deliberate: `abstraction.intake.ingest` rejects payloads that carry a direct
    identifier (name, mrn, dob, ...) by inspecting the *raw* dict keys. If this model stripped
    unknown fields instead, an identifier smuggled in under an unexpected key would never reach
    that check.
    """

    model_config = ConfigDict(extra="allow")

    pmh: list[str] = Field(default_factory=list)
    metabolic_panel: dict[str, float] = Field(default_factory=dict)
    cbc: dict[str, float] = Field(default_factory=dict)
    medications: list[str] = Field(default_factory=list)
    allergies: list[str] = Field(default_factory=list)
    age: int
    sex: Literal["M", "F"]
    weight_kg: float
    height_cm: float
    activity_level: Literal["sedentary", "light", "moderate", "active"]
    goal: str


class DeriveResponse(BaseModel):
    """Unconfirmed constraints plus the review payload the physician confirmation UI shows."""

    constraints: list[DerivedConstraintOut]
    review_items: list[ReviewItemOut]


class ConfirmRequest(BaseModel):
    """The derived set the client got from `/profile/derive`, plus the physician's per-index
    approvals and optional overrides. [INVARIANT] Only approved/overridden entries return
    confirmed=True; anything else is dropped by `abstraction.confirm.confirm`."""

    constraints: list[DerivedConstraintIn]
    approvals: dict[int, bool]
    overrides: dict[int, DerivedConstraintIn] | None = None


class ConfirmResponse(BaseModel):
    confirmed: list[DerivedConstraintOut]


# ---------------------------------------------------------------------------
# Catalog lookups (common/contract_client.py) - dish discovery and condition list for the UI
# ---------------------------------------------------------------------------


class DishSummaryOut(BaseModel):
    """One dish-search hit: enough to show and select a dish, not its facts (those come from
    `/recommend`). `canonical_name` may be null for a dish that has no materialized name."""

    dish_id: str
    canonical_name: str | None = None


class ConditionOut(BaseModel):
    """One `:Condition` from the knowledge base, for the condition selector."""

    condition_id: str
    name: str | None = None


class GuidelineOut(BaseModel):
    """One `:Guideline` passage (contract Section 2.2), for the evidence panel. `chunk` is the
    passage text; it may be null when only the citation stub is loaded (KB curation is a standing
    effort, so passage text can lag the citation)."""

    guideline_id: str
    org: str | None = None
    title: str | None = None
    year: int | None = None
    chunk: str | None = None


# ---------------------------------------------------------------------------
# Recommendation (engine/*, present/disclaimer.py)
# ---------------------------------------------------------------------------


class NutrientValueOut(BaseModel):
    """One nutrient amount on a ranked variant, with the calculated-not-measured disclaimer
    attached (DATA_CONTRACT.md Section 7). [INVARIANT] carried on every displayed value."""

    nutrient: str
    value: float
    measured: bool
    disclaimer: str


class EvaluationOut(BaseModel):
    """Mirror of `engine.evaluate.Evaluation`, enriched with the variant's disclosed nutrients."""

    variant_id: str
    dish_id: str
    admissible: bool
    score: float
    contraindicated: bool
    reasons: list[str]
    nutrients: list[NutrientValueOut]


class DishNutrientStatOut(BaseModel):
    """Mirror of `common.contract_client.DishNutrientStat`: one nutrient's distribution across a
    dish's versions (DATA_CONTRACT.md Section 5), so the clinician sees the version spread at a
    glance (for example, potassium 378 to 964 mg across four versions). Values are display-ready
    (rounded and labeled by `present.units.nutrient_amount`); `unit` is the label they carry."""

    nutrient: str
    unit: str
    count: int
    minimum: float
    maximum: float
    mean: float
    median: float
    stdev: float


class DishRankingOut(BaseModel):
    """Mirror of `engine.rank.DishRanking`: best admissible version per dish, plus all admissible
    versions within it, best first. `nutrient_stats` carries the dish-level distribution across all
    of the dish's versions (contract Section 5); empty when the dish has no materialized statistics."""

    dish_id: str
    best: EvaluationOut | None
    versions: list[EvaluationOut]
    nutrient_stats: dict[str, DishNutrientStatOut] = Field(default_factory=dict)


class ConflictNoteOut(BaseModel):
    """Mirror of `scoring.conflicts.ConflictNote`: a surfaced, never-averaged direction conflict."""

    nutrient: str
    kind: str
    resolution: str
    winning_rule: str
    guideline_ids: list[str]


class RecommendRequest(BaseModel):
    """Physician-confirmed constraints plus which dishes and conditions to evaluate against.

    `condition_ids` are resolved to nutrient `Constraint`s via
    `ContractClient.constraints_for_condition`; `confirmed` supplies the allergy/state-derived hard
    excludes (`direction == "avoid"`) and satisfies the confirmed-only gate.
    """

    confirmed: list[DerivedConstraintIn]
    condition_ids: list[str] = Field(default_factory=list)
    dish_ids: list[str]


class RecommendResponse(BaseModel):
    """[INVARIANT] Always carries `boundary`; every nutrient value carried under `rankings` carries
    its own calculated-not-measured disclaimer (see `NutrientValueOut`)."""

    rankings: list[DishRankingOut]
    conflicts: list[ConflictNoteOut]
    gaps: list[str]
    boundary: str


class ModifyRequest(BaseModel):
    """Taste/equipment limits layered onto a `RecommendRequest`. Equipment phrases are mapped to
    method exclusions by `interact.modify.parse_equipment`; `exclude_attributes` are added directly
    as Stage 1 hard excludes (taste dislikes, ingredient exclusions)."""

    confirmed: list[DerivedConstraintIn]
    condition_ids: list[str] = Field(default_factory=list)
    dish_ids: list[str]
    equipment_limits: list[str] = Field(default_factory=list)
    exclude_attributes: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Meal plan (plan/mealplan.py)
# ---------------------------------------------------------------------------


class MealIn(BaseModel):
    """Mirror of `plan.mealplan.Meal`: one admissible variant's per-serving facts."""

    variant_id: str
    dish_id: str
    nutrients: dict[str, float]


class MaintainRuleIn(BaseModel):
    """Mirror of `plan.mealplan.MaintainRule`: a plan-level consistency band."""

    nutrient: str
    band: float


class PlanRequest(BaseModel):
    """The admissible-meal pool and the plan-level rules (DATA_CONTRACT.md Section 6.3)."""

    pool: list[MealIn]
    energy_min: float
    energy_max: float
    fluid_max_ml: float | None = None
    protein_min: float | None = None
    maintain: list[MaintainRuleIn] = Field(default_factory=list)
    days: int = 7
    meals_per_day: int = 3


class DayPlanOut(BaseModel):
    meals: list[MealIn]
    totals: dict[str, float]


class PlanResponse(BaseModel):
    """[INVARIANT] Carries `boundary`, matching every other recommendation-shaped response."""

    days: list[DayPlanOut]
    violations: list[str]
    boundary: str


# ---------------------------------------------------------------------------
# Interaction (interact/qa.py, interact/explain.py)
# ---------------------------------------------------------------------------


class AskRequest(BaseModel):
    """A clinician's natural-language request, plus the grounding sets `explain.narrate` must
    stay within: guideline ids actually retrieved and dish ids actually in the current ranking."""

    request: str
    allowed_citations: list[str] = Field(default_factory=list)
    allowed_dishes: list[str] = Field(default_factory=list)
    ranking_summary: str = ""


class AskResponse(BaseModel):
    """The parsed structured query (mirroring `nectar.interact.qa.StructuredQuery`) alongside the
    grounded, cited narration from `nectar.interact.explain.narrate`. Both are LLM touchpoints at
    the ends of the query path; neither ever carries a clinical limit or an unsourced number."""

    intent: str
    dishes: list[str]
    exclude: list[str]
    free_text: str
    narration: str


# ---------------------------------------------------------------------------
# Research and write-back (research/hypotheses.py, research/verify.py)
# ---------------------------------------------------------------------------
# GET /research/hypotheses takes `target_id` as a query parameter (no request body) and its
# response reuses `nectar.research.hypotheses.HypothesisSurfaceResult` directly: it is already the
# contract-shaped pydantic model the research channel defines, so it is not duplicated here.


class VerifyRequest(BaseModel):
    """A measurement-backed promotion request for `/research/verify`. Reuses
    `nectar.research.writeback_service.MeasurementRecord` and the `TargetKind`/`EvidenceTier`
    types directly rather than redefining them. [INVARIANT] `research.verify.submit_measurement`
    (via `writeback_service.validate_promotion`) refuses locally without a reviewer, without a
    measurement, or on an illegal tier transition; this model does not relax those checks, it only
    carries the fields they need."""

    measurement: MeasurementRecord
    target_id: str
    target_kind: TargetKind
    prior_tier: EvidenceTier
    new_tier: EvidenceTier
    reviewer: str
    service_url: str | None = None
