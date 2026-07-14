"""Remediation: propose a preparation change only when no admissible version exists. Pure, no I/O.

The remediation engine matches a failing target's mechanism to an InterventionClass (the graph's
ADDRESSED_BY edge), applies the modeled change to the closest variant, and re-runs the FULL
constraint set against the modified variant. [INVARIANT] A change that fixes one target but breaks
another is not admissible and is flagged, never silently returned. Tier C hypotheses never enter
this path (they belong to the research channel). See ../../docs/PDD.md Section 6, SDD Section 4.
"""
from __future__ import annotations
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

from nectar.engine.constraints import ResolvedConstraints, VariantFacts
from nectar.engine.evaluate import Evaluation, evaluate_variant


@dataclass(frozen=True)
class InterventionProposal:
    """A candidate preparation change. `apply` models the change on the variant's facts; it comes
    from a graph InterventionClass mechanism, not from a language model."""
    intervention_class: str
    target: str
    apply: Callable[[VariantFacts], VariantFacts]
    label: str


@dataclass(frozen=True)
class Remediation:
    dish_id: str
    base_variant_id: str
    intervention_class: str
    label: str
    evaluation: Evaluation
    admissible: bool
    broke: list[str] = field(default_factory=list)   # targets newly excluded by the change


def remediate_dish(base: VariantFacts, proposals: Iterable[InterventionProposal],
                   rc: ResolvedConstraints) -> list[Remediation]:
    """Evaluate each proposal against the full constraint set. Callers keep only admissible
    remediations; non-admissible ones carry `broke` so the break can be surfaced, not hidden."""
    out: list[Remediation] = []
    for p in proposals:
        ev = evaluate_variant(p.apply(base), rc)
        broke = [r.split(":", 1)[-1] for r in ev.reasons] if not ev.admissible else []
        out.append(Remediation(
            dish_id=base.dish_id, base_variant_id=base.variant_id,
            intervention_class=p.intervention_class, label=p.label,
            evaluation=ev, admissible=ev.admissible, broke=broke))
    return out
