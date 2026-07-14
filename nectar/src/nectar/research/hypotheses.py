"""Surface Tier C items for a target; build the experimental-design stub.

[INVARIANT] Evidence tiers (contract Section 1.3): Tier C is research-only and MUST NOT surface
as a patient recommendation or remediation. This module is the research channel's read side
(SDD Section 8); nothing it returns may be passed into engine/, plan/, or present/. Promotion out
of Tier C happens only through the gated path in research/verify.py.

Reads go through an injected client/callable, never a direct Neo4j import, so this module stays
testable without a database and cannot accidentally acquire write access.

See ../../docs/PDD.md Section 10. Invariants in ../../CLAUDE.md apply.
"""
from __future__ import annotations

from typing import Callable, Sequence

from pydantic import BaseModel, ConfigDict

from nectar_contract.types import EvidenceTier

# Generic confounders relevant to any preparation-technique verification study. The protocol-
# specific confounders a reviewer must additionally control are a research-design judgment, not
# a clinical threshold, and are out of scope for this stub generator.
_BASE_CONFOUNDERS: tuple[str, ...] = (
    "preparation time",
    "temperature",
    "operator technique",
    "sample handling and storage",
)


class HypothesisTransform(BaseModel):
    """A Tier C research hypothesis (contract :HypothesisTransform)."""

    model_config = ConfigDict(frozen=True)

    hyp_id: str
    target: str
    mechanism: str
    protocol: str
    predicted_direction: str
    status: str
    evidence_tier: EvidenceTier


class StudyStub(BaseModel):
    """Experimental-design stub for one hypothesis (SDD Section 8): mechanism, endpoint, assay,
    baseline to beat, and confounders to control."""

    model_config = ConfigDict(frozen=True)

    hyp_id: str
    mechanism: str
    endpoint: str
    assay: str
    baseline_to_beat: str
    confounders: list[str]


class HypothesisSurfaceResult(BaseModel):
    """Everything the research channel shows a reviewer for one target: the Tier C candidates
    and their study stubs. Never a recommendation; never routed to a patient."""

    model_config = ConfigDict(frozen=True)

    target_id: str
    hypotheses: list[HypothesisTransform]
    study_stubs: list[StudyStub]


# Reads a target's hypotheses from the contract graph. Satisfied by a bound method on
# common/contract_client.py's client, or a plain callable/fake in tests. Never neo4j directly here.
HypothesesReader = Callable[[str], Sequence[HypothesisTransform]]


def _study_stub(hypothesis: HypothesisTransform) -> StudyStub:
    return StudyStub(
        hyp_id=hypothesis.hyp_id,
        mechanism=hypothesis.mechanism,
        endpoint=f"Change in {hypothesis.target} under protocol {hypothesis.protocol}",
        assay="measured assay appropriate to the target and protocol (reviewer-specified)",
        baseline_to_beat=f"as-authored preparation; predicted direction: {hypothesis.predicted_direction}",
        confounders=list(_BASE_CONFOUNDERS),
    )


def surface_hypotheses(target_id: str, client: HypothesesReader) -> HypothesisSurfaceResult:
    """Return the Tier C hypotheses for `target_id` plus a study stub for each.

    Defensively filters to `evidence_tier == "C"` even though the injected reader is expected to
    return only Tier C candidates for this target: Tier A/B facts are graph-verified nutrient and
    transform data, not research hypotheses, and must never be mixed into this research-only view.
    """
    hypotheses = [h for h in client(target_id) if h.evidence_tier == "C"]
    stubs = [_study_stub(h) for h in hypotheses]
    return HypothesisSurfaceResult(target_id=target_id, hypotheses=hypotheses, study_stubs=stubs)
