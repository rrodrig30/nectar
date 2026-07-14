"""Physician confirmation gate. [INVARIANT] No unconfirmed constraint reaches the engine.

The system proposes the abstraction; the clinician owns it. Each DerivedConstraint is presented with
its source_signal and formula and must be explicitly approved (or overridden) before it can drive a
recommendation. Anything not approved is dropped, never silently admitted.
See ../../docs/PDD.md Section 5.3, SDD Section 3.3.
"""
from __future__ import annotations
from dataclasses import replace

from nectar.abstraction.derive import DerivedConstraint

ReviewItem = dict[str, str | float | None]


def as_review_items(constraints: list[DerivedConstraint]) -> list[ReviewItem]:
    """The payload the UI shows for confirmation: what was derived, and the formula behind it."""
    return [{"index": i, "source_signal": c.source_signal, "target": c.target,
             "direction": c.direction, "severity": c.severity, "value": c.value,
             "unit": c.unit, "formula": c.formula}
            for i, c in enumerate(constraints)]


def confirm(constraints: list[DerivedConstraint], approvals: dict[int, bool],
            overrides: dict[int, DerivedConstraint] | None = None) -> list[DerivedConstraint]:
    """Apply per-index physician approvals and optional overrides. Returns only confirmed
    constraints (confirmed=True); anything not explicitly approved is excluded."""
    overrides = overrides or {}
    out: list[DerivedConstraint] = []
    for i, c in enumerate(constraints):
        if i in overrides:
            out.append(replace(overrides[i], confirmed=True))
        elif approvals.get(i, False):
            out.append(replace(c, confirmed=True))
    return out
