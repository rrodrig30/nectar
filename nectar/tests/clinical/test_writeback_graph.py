"""Clinical golden test for the gated graph write-back. [INVARIANT] The one NECTAR graph mutation.

The gated write refuses any promotion missing a reviewer or measurement, or any illegal tier jump,
BEFORE touching the graph; a valid promotion issues exactly the SET on the transform-family target
plus the immutable audit write, in one transaction. See DATA_CONTRACT Section 8, PDD Section 10.
"""
from typing import Any

import pytest

from nectar.research.writeback_service import (
    GraphPromotionWriter,
    MeasurementRecord,
    PromotionError,
    PromotionRequest,
)

_MEAS = MeasurementRecord(measurement=612.0, unit="mg", assay="ICP-MS", n=8,
                          method="boil-drain", submitter="lab-a")


class _FakeResult:
    def __init__(self, record: dict[str, Any] | None) -> None:
        self._record = record

    def single(self) -> dict[str, Any] | None:
        return self._record


class _FakeTx:
    def __init__(self, updated: int | None) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self._updated = updated

    def run(self, cypher: str, **params: Any) -> _FakeResult:
        self.calls.append((cypher, params))
        if "RETURN count(t)" in cypher:
            return _FakeResult({"updated": self._updated} if self._updated is not None else None)
        return _FakeResult(None)


class _FakeSession:
    def __init__(self, tx: _FakeTx) -> None:
        self._tx = tx

    def __enter__(self) -> "_FakeSession":
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def execute_write(self, fn: Any) -> Any:
        return fn(self._tx)


class _FakeDriver:
    def __init__(self, updated: int | None = 1) -> None:
        self.tx = _FakeTx(updated)

    def session(self, database: str | None = None) -> _FakeSession:
        return _FakeSession(self.tx)

    def close(self) -> None:
        return None


def _req(**over: Any) -> PromotionRequest:
    base: dict[str, Any] = dict(
        target_id="171705:boil:potassium:leaching", target_kind="TRANSFORM",
        prior_tier="C", new_tier="B", measurement=_MEAS, reviewer="Dr. Smith")
    base.update(over)
    return PromotionRequest(**base)


def test_refuses_without_reviewer_before_any_write():
    drv = _FakeDriver()
    with pytest.raises(PromotionError):
        GraphPromotionWriter(drv).promote(_req(reviewer=" "), timestamp="2026-07-12T00:00:00Z")
    assert drv.tx.calls == []                # nothing written to the graph


def test_refuses_illegal_tier_skip():
    drv = _FakeDriver()
    with pytest.raises(PromotionError):
        GraphPromotionWriter(drv).promote(_req(prior_tier="C", new_tier="A"), timestamp="t")
    assert drv.tx.calls == []


def test_refuses_without_measurement():
    drv = _FakeDriver()
    with pytest.raises(PromotionError):
        GraphPromotionWriter(drv).promote(_req(measurement=None), timestamp="t")
    assert drv.tx.calls == []


def test_valid_promotion_sets_tier_then_writes_audit():
    drv = _FakeDriver(updated=1)
    entry = GraphPromotionWriter(drv).promote(_req(), timestamp="2026-07-12T00:00:00Z")
    assert entry.new_tier == "B" and entry.who == "Dr. Smith"
    assert len(drv.tx.calls) == 2            # the SET, then the audit MERGE, in one transaction
    set_cypher, set_params = drv.tx.calls[0]
    assert "SET t.evidence_tier = $new_tier" in set_cypher
    assert set_params["new_tier"] == "B" and set_params["target_id"] == _req().target_id
    audit_cypher, audit_params = drv.tx.calls[1]
    assert ":PromotionAudit" in audit_cypher and audit_params["new_tier"] == "B"


def test_unknown_target_raises_and_writes_no_audit():
    drv = _FakeDriver(updated=0)             # no transform-family node with that id
    with pytest.raises(PromotionError):
        GraphPromotionWriter(drv).promote(_req(), timestamp="t")
    assert len(drv.tx.calls) == 1 and "RETURN count(t)" in drv.tx.calls[0][0]
