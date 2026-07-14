"""Structured intake of a de-identified, transient ClinicalSnapshot. Validation only, no persistence.

[INVARIANT] No patient records are persisted. The snapshot is de-identified and transient. This
module validates the incoming objective data and labs and builds the ClinicalSnapshot the
abstraction layer derives from, and rejects any payload that carries a direct identifier.
See ../../docs/PDD.md Section 5, SDD Sections 3 and 10.
"""
from __future__ import annotations
from typing import Any, Literal

from pydantic import BaseModel, Field

from nectar.abstraction.derive import ClinicalSnapshot

_IDENTIFIER_KEYS = frozenset({"name", "mrn", "dob", "ssn", "address", "phone", "email"})


class IdentifierRejected(ValueError):
    """Raised if the intake payload carries a direct identifier. [INVARIANT] De-identified only."""


class SnapshotInput(BaseModel):
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


def reject_identifiers(raw: dict[str, Any]) -> None:
    present = _IDENTIFIER_KEYS & {k.lower() for k in raw}
    if present:
        raise IdentifierRejected("de-identified intake only; remove: " + ", ".join(sorted(present)))


def to_snapshot(payload: SnapshotInput) -> ClinicalSnapshot:
    return ClinicalSnapshot(
        pmh=payload.pmh, metabolic_panel=payload.metabolic_panel, cbc=payload.cbc,
        medications=payload.medications, allergies=payload.allergies, age=payload.age,
        sex=payload.sex, weight_kg=payload.weight_kg, height_cm=payload.height_cm,
        activity_level=payload.activity_level, goal=payload.goal)


def ingest(raw: dict[str, Any]) -> ClinicalSnapshot:
    """Validate a de-identified payload and build the transient snapshot. Raises on identifiers."""
    reject_identifiers(raw)
    return to_snapshot(SnapshotInput.model_validate(raw))
