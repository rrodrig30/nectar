"""Build the contract Section 1.1 metadata block for a written value. Pure, no I/O.

Every value that was computed, estimated, matched, or extracted carries source, confidence,
evidence_tier, computed_by, and the contract_version it was produced under. See DATA_CONTRACT Section 1.1.
"""
from __future__ import annotations

from nectar_contract import CONTRACT_VERSION
from nectar_contract.types import EvidenceTier, Provenance


def make_provenance(source: str, confidence: float, computed_by: str,
                    evidence_tier: EvidenceTier | None = None) -> Provenance:
    """Assemble the metadata block, stamping the pinned contract version automatically."""
    return Provenance(source=source, confidence=confidence, evidence_tier=evidence_tier,
                      computed_by=computed_by, contract_version=CONTRACT_VERSION)
