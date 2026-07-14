"""Constraint assembly and the confirmed-only gate. [INVARIANT] Pure functions, no I/O.

Bridges the abstraction layer's confirmed constraint set to the scoring Constraint set the engine
evaluates. Nutrient ceilings and targets (Stage 2 scoring) are separated from absolute attribute
exclusions (Stage 1 hard filter). Direction conflicts are resolved by the safety-dominant rule in
scoring/conflicts.py, never by averaging. See ../../docs/PDD.md Section 6, SDD Section 4.
"""
from __future__ import annotations
from collections.abc import Iterable
from dataclasses import dataclass, field

from nectar.abstraction.derive import DerivedConstraint
from nectar.scoring.conflicts import ConflictNote, resolve
from nectar.scoring.suitability import Constraint


@dataclass(frozen=True)
class VariantFacts:
    """The per-serving facts NECTAR reads for one RecipeVariant (DATA_CONTRACT.md Section 3.1).

    Nutrient amounts are in canonical units; `attributes` holds the resolved attribute, allergen,
    and compound ids present on the variant, which Stage 1 filters against.
    """
    variant_id: str
    dish_id: str
    nutrients: dict[str, float]
    attributes: frozenset[str] = frozenset()
    method: str = ""
    # nutrient_id -> (source, confidence) from the graph HAS_NUTRIENT edge, so the presentation
    # layer's calculated-not-measured disclaimer is specific (DATA_CONTRACT.md Section 7), not generic.
    nutrient_provenance: dict[str, tuple[str, float]] = field(default_factory=dict)


@dataclass(frozen=True)
class ResolvedConstraints:
    """The merged constraint set the engine evaluates against one variant."""
    by_nutrient: dict[str, Constraint]
    hard_excludes: frozenset[str]
    conflicts: list[ConflictNote] = field(default_factory=list)


class UnconfirmedConstraintError(RuntimeError):
    """Raised when an unconfirmed DerivedConstraint reaches the engine. [INVARIANT]"""


def require_confirmed(derived: Iterable[DerivedConstraint]) -> None:
    """[INVARIANT] No DerivedConstraint with confirmed=False may drive a recommendation."""
    unconfirmed = [d.source_signal for d in derived if not d.confirmed]
    if unconfirmed:
        raise UnconfirmedConstraintError(
            "constraints must be physician-confirmed before evaluation: " + ", ".join(unconfirmed)
        )


def assemble(nutrient_constraints: Iterable[Constraint],
             hard_excludes: Iterable[str] = ()) -> ResolvedConstraints:
    """Group nutrient constraints by target with safety-dominant conflict resolution, and collect
    the absolute exclusion set (allergens, food-safety exclusions, equipment the patient lacks)."""
    by_nutrient, conflicts = resolve(list(nutrient_constraints))
    return ResolvedConstraints(by_nutrient=by_nutrient,
                               hard_excludes=frozenset(hard_excludes),
                               conflicts=conflicts)
