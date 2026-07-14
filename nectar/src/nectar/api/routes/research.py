"""GET /research/hypotheses, POST /research/verify.

The research channel's read side surfaces Tier C hypotheses and never lets them leak into the
patient recommendation path (contract Section 1.3). Its write side, `/research/verify`, is the
single mutation NECTAR is permitted on the shared graph (contract Section 8): a measurement-backed
tier promotion through the gated service, never a direct Neo4j write session.
See ../../docs/PDD.md Section 10, Section 11. Invariants in ../../CLAUDE.md apply.
"""
from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from nectar.api.deps import Role, get_contract_client, require_role
from nectar.api.schemas import VerifyRequest
from nectar.common.contract_client import ContractClient
from nectar.research.hypotheses import HypothesisSurfaceResult, HypothesisTransform, surface_hypotheses
from nectar.research.verify import TargetRef, WritebackError, submit_measurement
from nectar.research.writeback_service import AuditEntry, PromotionError

router = APIRouter()

_WRITEBACK_SERVICE_URL_ENV = "WRITEBACK_SERVICE_URL"


def _target_hypotheses(client: ContractClient, target_id: str) -> list[HypothesisTransform]:
    """Adapt `ContractClient.interventions_for_target` to the `HypothesesReader` shape
    `surface_hypotheses` expects.

    `interventions_for_target` returns `InterventionClass` rows with their `Method` and
    `HypothesisTransform` implementations undistinguished by tier (see its docstring); this keeps
    only the `HypothesisTransform`-labeled implementations, since the research channel must see
    Tier C candidates only. The accessor does not carry `protocol`, `predicted_direction`, or
    `status` for those implementations, so those fields are reported as unavailable rather than
    invented. `evidence_tier` is fixed to `"C"` here as a routing default, not a fabricated
    clinical number: a `HypothesisTransform` is Tier C by construction (contract Section 2.2), and
    `surface_hypotheses` independently re-filters on tier for defense in depth.
    """
    hypotheses: list[HypothesisTransform] = []
    for intervention_row in client.interventions_for_target(target_id):
        mechanism = intervention_row.get("mechanism") or ""
        implementations: list[dict[str, Any]] = intervention_row.get("implementations") or []
        for impl in implementations:
            if impl is None:
                continue
            labels = impl.get("labels") or []
            if "HypothesisTransform" not in labels:
                continue
            hyp_id = impl.get("id")
            if not hyp_id:
                continue
            hypotheses.append(
                HypothesisTransform(
                    hyp_id=hyp_id,
                    target=target_id,
                    mechanism=mechanism,
                    protocol="not available from interventions_for_target",
                    predicted_direction="unspecified",
                    status="proposed",
                    evidence_tier="C",
                )
            )
    return hypotheses


@router.get("/research/hypotheses", response_model=HypothesisSurfaceResult)
def get_research_hypotheses(
    target_id: str, client: ContractClient = Depends(get_contract_client)
) -> HypothesisSurfaceResult:
    """Tier C items and study stub for a target. Never routed to a patient recommendation."""
    return surface_hypotheses(target_id, lambda tid: _target_hypotheses(client, tid))


@router.post("/research/verify", response_model=AuditEntry)
def post_research_verify(
    req: VerifyRequest, _role: Role = Depends(require_role("reviewer", "admin"))
) -> AuditEntry:
    """Submit a measurement to the gated write-back. [INVARIANT] This is the only mutation NECTAR
    performs on the shared graph, and it is refused locally (422) without a linked measurement, a
    named reviewer, or a legal C->B / B->A transition, before any network call is made."""
    service_url = req.service_url or os.environ.get(_WRITEBACK_SERVICE_URL_ENV)
    if not service_url:
        raise HTTPException(
            status_code=422,
            detail=(
                "no write-back service url configured; set WRITEBACK_SERVICE_URL or supply "
                "service_url in the request"
            ),
        )
    target = TargetRef(target_id=req.target_id, target_kind=req.target_kind)
    try:
        return submit_measurement(
            req.measurement,
            target,
            req.prior_tier,
            req.new_tier,
            req.reviewer,
            service_url,
        )
    except PromotionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except WritebackError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
