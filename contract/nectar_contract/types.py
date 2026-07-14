"""Shared types used at the boundary between programs. Keep minimal; program-specific models live
in each program's package."""
from __future__ import annotations
from datetime import datetime
from typing import Literal
from pydantic import BaseModel

EvidenceTier = Literal["A", "B", "C"]


class Provenance(BaseModel):
    """Metadata every derived value must carry (DATA_CONTRACT.md Section 1.1)."""
    source: str
    confidence: float
    evidence_tier: EvidenceTier | None = None
    computed_by: str
    contract_version: str


class Measurement(BaseModel):
    value: float
    unit: str


class Fact(BaseModel):
    """A computed value with its provenance."""
    value: float
    unit: str
    provenance: Provenance
