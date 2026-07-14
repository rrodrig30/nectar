"""POST /profile/derive, /profile/confirm, /recommend, /modify.

Routes only marshal I/O: build the domain dataclasses from the request, call the already-built
abstraction/engine/interact modules, and shape their output back into the response schemas. No
clinical literal, threshold, or scoring rule lives here.

See ../../docs/PDD.md Section 6, Section 9, Section 11. Invariants in ../../CLAUDE.md apply.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from nectar.abstraction.confirm import as_review_items, confirm
from nectar.abstraction.derive import DerivedConstraint, derive
from nectar.abstraction.intake import IdentifierRejected, ingest
from nectar.api.deps import get_contract_client
from nectar.api.schemas import (
    ConfirmRequest,
    ConfirmResponse,
    ConflictNoteOut,
    DeriveRequest,
    DeriveResponse,
    DerivedConstraintIn,
    DerivedConstraintOut,
    DishNutrientStatOut,
    DishRankingOut,
    EvaluationOut,
    ModifyRequest,
    NutrientValueOut,
    RecommendRequest,
    RecommendResponse,
    ReviewItemOut,
)
from nectar.common.contract_client import ContractClient, DishNutrientStat
from nectar.engine.constraints import (
    ResolvedConstraints,
    UnconfirmedConstraintError,
    VariantFacts,
    assemble,
)
from nectar.engine.evaluate import Evaluation
from nectar.engine.rank import DishRanking
from nectar.engine.recommend import Recommendation, recommend as run_recommend
from nectar.interact.modify import Modifications, apply as apply_modifications, parse_equipment
from nectar.present.disclaimer import attach as attach_disclaimer
from nectar.present.units import nutrient_amount
from nectar.scoring.conflicts import ConflictNote
from nectar.scoring.suitability import Constraint

router = APIRouter()


def _to_dataclass(c: DerivedConstraintIn) -> DerivedConstraint:
    return DerivedConstraint(
        source_signal=c.source_signal,
        direction=c.direction,
        target=c.target,
        severity=c.severity,
        value=c.value,
        unit=c.unit,
        formula=c.formula,
        guideline_id=c.guideline_id,
        confirmed=c.confirmed,
    )


def _to_out(c: DerivedConstraint) -> DerivedConstraintOut:
    return DerivedConstraintOut.model_validate(c)


@router.post("/profile/derive", response_model=DeriveResponse)
def post_profile_derive(req: DeriveRequest) -> DeriveResponse:
    """Snapshot in, deterministically derived constraints out (all `confirmed=False`)."""
    try:
        snapshot = ingest(req.model_dump())
    except IdentifierRejected as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    constraints = derive(snapshot)
    return DeriveResponse(
        constraints=[_to_out(c) for c in constraints],
        review_items=[ReviewItemOut.model_validate(item) for item in as_review_items(constraints)],
    )


@router.post("/profile/confirm", response_model=ConfirmResponse)
def post_profile_confirm(req: ConfirmRequest) -> ConfirmResponse:
    """Apply the physician's per-index approvals and overrides. Only approved/overridden entries
    return `confirmed=True`; anything else is dropped, never silently admitted."""
    constraints = [_to_dataclass(c) for c in req.constraints]
    overrides = (
        {idx: _to_dataclass(c) for idx, c in req.overrides.items()} if req.overrides else None
    )
    confirmed = confirm(constraints, req.approvals, overrides)
    return ConfirmResponse(confirmed=[_to_out(c) for c in confirmed])


def _resolve_scoring_inputs(
    confirmed: list[DerivedConstraint], condition_ids: list[str], client: ContractClient
) -> ResolvedConstraints:
    """Pull nutrient `Constraint`s for the requested conditions from the contract graph, and take
    the allergy/state-derived hard excludes (`direction == "avoid"`) from the confirmed set."""
    nutrient_constraints: list[Constraint] = []
    for condition_id in condition_ids:
        nutrient_constraints.extend(client.constraints_for_condition(condition_id))
    hard_excludes = {c.target for c in confirmed if c.direction == "avoid"}
    return assemble(nutrient_constraints, hard_excludes)


def _variants_for_dishes(dish_ids: list[str], client: ContractClient) -> list[VariantFacts]:
    variants: list[VariantFacts] = []
    for dish_id in dish_ids:
        variants.extend(client.variants_for_dish(dish_id))
    return variants


def _nutrients_out(variant: VariantFacts | None) -> list[NutrientValueOut]:
    """Every nutrient value a ranked variant carries, with the calculated-not-measured disclaimer
    attached (DATA_CONTRACT.md Section 7). The per-nutrient source and confidence come from the
    graph HAS_NUTRIENT edge via `VariantFacts.nutrient_provenance`, making the note specific; a value
    with no recorded provenance falls back to a conservative calculated default, never confidence 1.0."""
    if variant is None:
        return []
    out: list[NutrientValueOut] = []
    for nutrient, amount in sorted(variant.nutrients.items()):
        source, confidence = variant.nutrient_provenance.get(nutrient, ("calculated", 0.5))
        disclosed = attach_disclaimer(amount, unit="", source=source, confidence=confidence)
        out.append(
            NutrientValueOut(
                nutrient=nutrient,
                value=disclosed.value,
                measured=disclosed.measured,
                disclaimer=disclosed.disclaimer,
            )
        )
    return out


def _evaluation_out(
    evaluation: Evaluation, variants_by_id: dict[str, VariantFacts]
) -> EvaluationOut:
    return EvaluationOut(
        variant_id=evaluation.variant_id,
        dish_id=evaluation.dish_id,
        admissible=evaluation.admissible,
        score=evaluation.score,
        contraindicated=evaluation.contraindicated,
        reasons=list(evaluation.reasons),
        nutrients=_nutrients_out(variants_by_id.get(evaluation.variant_id)),
    )


def _stat_out(stat: DishNutrientStat) -> DishNutrientStatOut:
    """Present one dish nutrient distribution: each value rounded and labeled through
    `present.units.nutrient_amount` (nutrient amounts are unit-system independent, so they are not
    converted the way bulk serving mass is)."""
    unit = nutrient_amount(stat.mean, stat.unit).unit
    return DishNutrientStatOut(
        nutrient=stat.nutrient,
        unit=unit,
        count=stat.count,
        minimum=nutrient_amount(stat.minimum, stat.unit).value,
        maximum=nutrient_amount(stat.maximum, stat.unit).value,
        mean=nutrient_amount(stat.mean, stat.unit).value,
        median=nutrient_amount(stat.median, stat.unit).value,
        stdev=nutrient_amount(stat.stdev, stat.unit).value,
    )


def _ranking_out(
    ranking: DishRanking,
    variants_by_id: dict[str, VariantFacts],
    stats: dict[str, DishNutrientStat],
) -> DishRankingOut:
    return DishRankingOut(
        dish_id=ranking.dish_id,
        best=_evaluation_out(ranking.best, variants_by_id) if ranking.best is not None else None,
        versions=[_evaluation_out(e, variants_by_id) for e in ranking.versions],
        nutrient_stats={nutrient_id: _stat_out(stat) for nutrient_id, stat in stats.items()},
    )


def _conflict_out(conflict: ConflictNote) -> ConflictNoteOut:
    return ConflictNoteOut.model_validate(conflict, from_attributes=True)


def _stats_for_rankings(
    result: Recommendation, client: ContractClient
) -> dict[str, dict[str, DishNutrientStat]]:
    """Fetch the dish-level nutrient distribution stats (contract Section 5) for each ranked dish.
    One read per dish; an unstatistified dish returns an empty map and is carried as such."""
    return {ranking.dish_id: client.dish_nutrient_stats(ranking.dish_id) for ranking in result.rankings}


def _recommendation_response(
    result: Recommendation,
    variants_by_id: dict[str, VariantFacts],
    stats_by_dish: dict[str, dict[str, DishNutrientStat]],
) -> RecommendResponse:
    return RecommendResponse(
        rankings=[
            _ranking_out(r, variants_by_id, stats_by_dish.get(r.dish_id, {}))
            for r in result.rankings
        ],
        conflicts=[_conflict_out(c) for c in result.conflicts],
        gaps=list(result.gaps),
        boundary=result.boundary,
    )


@router.post("/recommend", response_model=RecommendResponse)
def post_recommend(
    req: RecommendRequest, client: ContractClient = Depends(get_contract_client)
) -> RecommendResponse:
    """Confirmed constraints in, ranked dishes/versions out. [INVARIANT] An unconfirmed constraint
    in `req.confirmed` is rejected here (422), never allowed to reach the engine as a 500."""
    confirmed = [_to_dataclass(c) for c in req.confirmed]
    rc = _resolve_scoring_inputs(confirmed, req.condition_ids, client)
    variants = _variants_for_dishes(req.dish_ids, client)
    variants_by_id = {v.variant_id: v for v in variants}
    try:
        result = run_recommend(confirmed, variants, rc)
    except UnconfirmedConstraintError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _recommendation_response(result, variants_by_id, _stats_for_rankings(result, client))


@router.post("/modify", response_model=RecommendResponse)
def post_modify(
    req: ModifyRequest, client: ContractClient = Depends(get_contract_client)
) -> RecommendResponse:
    """Taste/equipment change, re-ranked result. A method the patient cannot perform (or a taste
    dislike) grows the Stage 1 exclusion set and reruns the identical evaluation; the scoring
    middle is untouched (see `interact/modify.py`)."""
    confirmed = [_to_dataclass(c) for c in req.confirmed]
    base_rc = _resolve_scoring_inputs(confirmed, req.condition_ids, client)
    mods = Modifications(
        exclude_methods=parse_equipment(req.equipment_limits),
        exclude_attributes=frozenset(req.exclude_attributes),
    )
    rc = apply_modifications(base_rc, mods)
    variants = _variants_for_dishes(req.dish_ids, client)
    variants_by_id = {v.variant_id: v for v in variants}
    try:
        result = run_recommend(confirmed, variants, rc)
    except UnconfirmedConstraintError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _recommendation_response(result, variants_by_id, _stats_for_rankings(result, client))
