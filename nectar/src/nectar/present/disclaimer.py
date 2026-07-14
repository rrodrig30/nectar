"""Attach the calculated-not-measured disclaimer to every displayed nutrient value. Pure, no I/O.

[INVARIANT] Every nutrient value in the graph is calculated, not laboratory-measured, unless its
source is an explicit measurement record. NECTAR surfaces this on every displayed value; the
contract's confidence and source make the note specific rather than generic.
See ../../docs/PDD.md Section 8, DATA_CONTRACT.md Section 7.
"""
from __future__ import annotations
from dataclasses import dataclass

MEASURED_SOURCE_TAGS = ("measurement", "measured", "lab", "assay")


@dataclass(frozen=True)
class DisclosedValue:
    value: float
    unit: str
    disclaimer: str
    measured: bool
    confidence: float
    source: str


def is_measured(source: str) -> bool:
    s = source.lower()
    return any(tag in s for tag in MEASURED_SOURCE_TAGS)


def disclaimer_text(source: str, confidence: float) -> str:
    if is_measured(source):
        return f"Measured value (source {source}), confidence {confidence:.0%}."
    return f"Calculated, not laboratory-measured (source {source}), confidence {confidence:.0%}."


def attach(value: float, unit: str, source: str, confidence: float) -> DisclosedValue:
    return DisclosedValue(value=value, unit=unit, disclaimer=disclaimer_text(source, confidence),
                          measured=is_measured(source), confidence=confidence, source=source)
