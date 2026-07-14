"""The gated promotion service: server-side logic for the ONE write-back path NECTAR has to the
shared graph (contract/DATA_CONTRACT.md Section 8). Deployed as its own service with its own
Neo4j role that may only set `evidence_tier`/`status` on transform-family nodes (see
deploy/README.md); this module holds the validation and audit logic that service applies before
ever touching the graph.

[INVARIANT] No tier promotion without a linked measurement record and a named reviewer.
[INVARIANT] Only C->B or B->A. No skipping, no automated promotion.
[INVARIANT] Every promotion writes an immutable audit entry (who, when, evidence id, prior, new).

See ../../docs/PDD.md Section 10. Invariants in ../../CLAUDE.md apply.
"""
from __future__ import annotations

import hashlib
import os
from typing import Callable, Literal

from neo4j import Driver, GraphDatabase, ManagedTransaction
from pydantic import BaseModel, ConfigDict, Field

from nectar_contract.types import EvidenceTier

# The two node/relationship families a promotion may target (contract Section 2.2, 3.2):
# TRANSFORM edges (Food|FoodClass -[:TRANSFORM]-> Method) and :HypothesisTransform nodes.
TargetKind = Literal["TRANSFORM", "HypothesisTransform"]

# The only legal tier transitions. C->B or B->A, never a skip, never A downward.
_ALLOWED_PROMOTIONS: frozenset[tuple[EvidenceTier, EvidenceTier]] = frozenset(
    {("C", "B"), ("B", "A")}
)


class PromotionError(ValueError):
    """Raised when a promotion request violates the gated write-back rules
    (contract Section 8). Refusal, not a lenient fallback."""


class MeasurementRecord(BaseModel):
    """A structured, linked measurement submitted by a lab or clinician (contract Section 8)."""

    model_config = ConfigDict(frozen=True)

    measurement: float
    unit: str
    assay: str
    n: int = Field(gt=0)
    method: str
    submitter: str


class PromotionRequest(BaseModel):
    """A request to promote one transform-family node's evidence tier."""

    model_config = ConfigDict(frozen=True)

    target_id: str
    target_kind: TargetKind
    prior_tier: EvidenceTier
    new_tier: EvidenceTier
    measurement: MeasurementRecord | None
    reviewer: str


class AuditEntry(BaseModel):
    """Immutable audit record for one promotion: who, when, evidence id, prior tier, new tier."""

    model_config = ConfigDict(frozen=True)

    who: str
    when: str
    evidence_id: str
    target_id: str
    target_kind: TargetKind
    prior_tier: EvidenceTier
    new_tier: EvidenceTier


AuditSink = Callable[[AuditEntry], None]


def validate_promotion(request: PromotionRequest) -> None:
    """Raise PromotionError unless `request` satisfies every gated write-back rule. Shared by the
    server-side `promote` below and the NECTAR-side client (research/verify.py) so both enforce
    the identical preconditions rather than two hand-maintained copies that could drift."""
    if request.measurement is None:
        raise PromotionError(
            "Tier promotion requires a linked measurement record; none was submitted."
        )
    if not request.reviewer.strip():
        raise PromotionError("Tier promotion requires a named reviewer; none was submitted.")
    transition = (request.prior_tier, request.new_tier)
    if transition not in _ALLOWED_PROMOTIONS:
        raise PromotionError(
            f"Illegal tier transition {request.prior_tier} -> {request.new_tier}. "
            "Only C->B or B->A promotions are permitted; no skipping, no automated promotion."
        )


def _evidence_id(measurement: MeasurementRecord) -> str:
    """A deterministic id linking the audit entry to the submitted measurement. Deterministic
    (no randomness, no wall clock) so the same submission always yields the same evidence id."""
    digest_input = "|".join(
        (
            measurement.assay,
            measurement.method,
            str(measurement.n),
            repr(measurement.measurement),
            measurement.unit,
            measurement.submitter,
        )
    )
    return hashlib.sha256(digest_input.encode("utf-8")).hexdigest()[:16]


def build_audit_entry(request: PromotionRequest, timestamp: str) -> AuditEntry:
    """Validate `request` against the gated rules and build the immutable audit entry. Raises
    PromotionError on any rule violation before an entry exists. Shared by `promote` (callback sink)
    and `GraphPromotionWriter` (graph sink) so the validation runs on exactly one code path."""
    validate_promotion(request)
    assert request.measurement is not None  # validate_promotion already enforced this
    return AuditEntry(
        who=request.reviewer.strip(),
        when=timestamp,
        evidence_id=_evidence_id(request.measurement),
        target_id=request.target_id,
        target_kind=request.target_kind,
        prior_tier=request.prior_tier,
        new_tier=request.new_tier,
    )


def promote(request: PromotionRequest, audit_sink: AuditSink, timestamp: str) -> AuditEntry:
    """Validate `request` against the gated rules, then write one immutable audit entry via the
    injected `audit_sink` and return it. Raises PromotionError on any rule violation; nothing is
    written to `audit_sink` when validation fails.

    `timestamp` is supplied by the caller rather than read from the wall clock, so this function
    stays deterministic and testable; the caller (the service's request handler) is responsible
    for supplying a real clock reading in production.
    """
    entry = build_audit_entry(request, timestamp)
    audit_sink(entry)
    return entry


# The gated graph mutation: set evidence_tier/status on a transform-family target, keyed by the
# target's own id. HypothesisTransform is a node (hyp_id); a TRANSFORM edge carries a transform_id.
_PROMOTE_CYPHER: dict[TargetKind, str] = {
    "HypothesisTransform": (
        "MATCH (t:HypothesisTransform {hyp_id: $target_id}) "
        "SET t.evidence_tier = $new_tier, t.status = $status "
        "RETURN count(t) AS updated"
    ),
    "TRANSFORM": (
        "MATCH ()-[t:TRANSFORM {transform_id: $target_id}]->() "
        "SET t.evidence_tier = $new_tier, t.status = $status "
        "RETURN count(t) AS updated"
    ),
}

_WRITE_AUDIT_CYPHER = (
    "MERGE (a:PromotionAudit {evidence_id: $evidence_id}) "
    "SET a.who = $who, a.when = $when, a.target_id = $target_id, a.target_kind = $target_kind, "
    "a.prior_tier = $prior_tier, a.new_tier = $new_tier"
)


class GraphPromotionWriter:
    """Applies a validated promotion to the graph under the promotion Neo4j role: the ONLY mutation
    NECTAR performs on the shared graph (contract Section 8). Sets evidence_tier/status on the
    transform-family target and writes the immutable audit node, both in one write transaction, so a
    promotion and its audit record cannot diverge."""

    def __init__(self, driver: Driver, *, database: str | None = None,
                 promoted_status: str = "verified") -> None:
        self._driver = driver
        self._database = database
        self._status = promoted_status

    @classmethod
    def from_env(cls) -> GraphPromotionWriter:
        uri = os.environ["NEO4J_URI"]
        user = os.environ["NEO4J_USER"]
        password = os.environ["NEO4J_PASSWORD"]
        driver = GraphDatabase.driver(uri, auth=(user, password))
        return cls(driver, database=os.environ.get("NEO4J_DATABASE"))

    def close(self) -> None:
        self._driver.close()

    def promote(self, request: PromotionRequest, timestamp: str) -> AuditEntry:
        """Validate, then set the tier/status and write the audit node in one transaction. Raises
        PromotionError before any write on a rule violation or an unknown target id."""
        entry = build_audit_entry(request, timestamp)  # refuses before touching the graph
        set_cypher = _PROMOTE_CYPHER[request.target_kind]
        status = self._status

        def _txn(tx: ManagedTransaction) -> None:
            record = tx.run(set_cypher, target_id=request.target_id,
                            new_tier=request.new_tier, status=status).single()
            if record is None or record["updated"] == 0:
                raise PromotionError(
                    f"no {request.target_kind} with id {request.target_id!r} to promote")
            tx.run(_WRITE_AUDIT_CYPHER, **entry.model_dump())

        with self._driver.session(database=self._database) as session:
            session.execute_write(_txn)
        return entry
