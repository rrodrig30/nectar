"""Clinical golden tests for the gated tier-promotion write-back path.
[INVARIANT] Must always pass in CI. See contract/DATA_CONTRACT.md Section 8: no promotion
without a reviewer, no promotion without a linked measurement, no tier-skip, and a valid
promotion writes exactly one immutable audit entry.
"""
from __future__ import annotations

import pytest

from nectar.research.writeback_service import (
    AuditEntry,
    MeasurementRecord,
    PromotionError,
    PromotionRequest,
    promote,
)

TIMESTAMP = "2026-07-12T00:00:00Z"

MEASUREMENT = MeasurementRecord(
    measurement=42.0,
    unit="mg",
    assay="ICP-MS",
    n=12,
    method="boil-drain-cubed",
    submitter="lab-tech-1",
)


def test_promote_raises_without_reviewer() -> None:
    request = PromotionRequest(
        target_id="transform-potassium-boil-1",
        target_kind="TRANSFORM",
        prior_tier="C",
        new_tier="B",
        measurement=MEASUREMENT,
        reviewer="",
    )
    with pytest.raises(PromotionError):
        promote(request, audit_sink=lambda entry: None, timestamp=TIMESTAMP)


def test_promote_raises_on_tier_skip() -> None:
    request = PromotionRequest(
        target_id="transform-potassium-boil-1",
        target_kind="TRANSFORM",
        prior_tier="C",
        new_tier="A",
        measurement=MEASUREMENT,
        reviewer="Dr. Rodriguez",
    )
    with pytest.raises(PromotionError):
        promote(request, audit_sink=lambda entry: None, timestamp=TIMESTAMP)


def test_promote_raises_without_measurement() -> None:
    request = PromotionRequest(
        target_id="transform-potassium-boil-1",
        target_kind="TRANSFORM",
        prior_tier="C",
        new_tier="B",
        measurement=None,
        reviewer="Dr. Rodriguez",
    )
    with pytest.raises(PromotionError):
        promote(request, audit_sink=lambda entry: None, timestamp=TIMESTAMP)


def test_promote_succeeds_on_c_to_b_with_reviewer_and_measurement() -> None:
    audit_log: list[AuditEntry] = []
    request = PromotionRequest(
        target_id="transform-potassium-boil-1",
        target_kind="TRANSFORM",
        prior_tier="C",
        new_tier="B",
        measurement=MEASUREMENT,
        reviewer="Dr. Rodriguez",
    )
    entry = promote(request, audit_sink=audit_log.append, timestamp=TIMESTAMP)
    assert len(audit_log) == 1
    assert audit_log[0] is entry
    assert entry.prior_tier == "C"
    assert entry.new_tier == "B"
    assert entry.who == "Dr. Rodriguez"
    assert entry.when == TIMESTAMP


def test_promote_raises_on_b_to_a_skip_reversal_is_not_allowed() -> None:
    """A->B (demotion / reversal) is not a promotion path either; only forward C->B, B->A."""
    request = PromotionRequest(
        target_id="transform-potassium-boil-1",
        target_kind="TRANSFORM",
        prior_tier="A",
        new_tier="B",
        measurement=MEASUREMENT,
        reviewer="Dr. Rodriguez",
    )
    with pytest.raises(PromotionError):
        promote(request, audit_sink=lambda entry: None, timestamp=TIMESTAMP)
