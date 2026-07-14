"""Submit measurement to the gated promotion service. The ONLY write path NECTAR has to the
shared graph (contract/DATA_CONTRACT.md Section 8).

This client applies the identical preconditions the service enforces (see
`writeback_service.validate_promotion`) before making any network call, so a caller that is
missing a reviewer or a measurement, or that attempts a tier skip, is refused locally instead of
round-tripping to a service that would reject it anyway.

See ../../docs/PDD.md Section 10. Invariants in ../../CLAUDE.md apply.
"""
from __future__ import annotations

from typing import Any

import httpx

from nectar.research.writeback_service import (
    AuditEntry,
    MeasurementRecord,
    PromotionRequest,
    TargetKind,
    validate_promotion,
)
from nectar_contract.types import EvidenceTier

_DEFAULT_TIMEOUT_S = 30.0


class WritebackError(RuntimeError):
    """Raised when the gated promotion service is unreachable or rejects the submission."""


class TargetRef:
    """Identifies the transform-family node or edge family a submission targets."""

    __slots__ = ("target_id", "target_kind")

    def __init__(self, target_id: str, target_kind: TargetKind) -> None:
        self.target_id = target_id
        self.target_kind = target_kind


def submit_measurement(
    record: MeasurementRecord,
    target: TargetRef,
    prior_tier: EvidenceTier,
    new_tier: EvidenceTier,
    reviewer: str,
    service_url: str,
    *,
    timeout: float = _DEFAULT_TIMEOUT_S,
) -> AuditEntry:
    """Post a measurement-backed promotion request to the gated write-back service.

    Refuses locally (raising `writeback_service.PromotionError`, without any network call) unless
    the request carries a linked measurement, a named reviewer, and a legal C->B or B->A
    transition. This is the only function in NECTAR that writes to the shared graph, and it does
    so only through the gated service, never a direct Neo4j write session.
    """
    request = PromotionRequest(
        target_id=target.target_id,
        target_kind=target.target_kind,
        prior_tier=prior_tier,
        new_tier=new_tier,
        measurement=record,
        reviewer=reviewer,
    )
    validate_promotion(request)  # [INVARIANT] refuse locally before any network call

    url = f"{service_url.rstrip('/')}/research/verify"
    body: dict[str, Any] = request.model_dump(mode="json")
    try:
        response = httpx.post(url, json=body, timeout=timeout)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise WritebackError(f"Write-back submission to {url} failed: {exc}") from exc
    return AuditEntry.model_validate(response.json())
