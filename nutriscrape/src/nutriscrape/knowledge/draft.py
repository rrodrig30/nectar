"""LLM-drafted candidate knowledge-base entries with citations -> review queue.

[INVARIANT] Nothing the drafter produces reaches live authority without a named human reviewer.
``draft_candidates`` returns :class:`DraftEntry` objects that are always ``status="pending_review"``
with an empty ``reviewer`` field, regardless of anything the model claims. The single gate out of
the queue is :func:`promote_to_live`, which refuses to act without a named reviewer. This mirrors
the contract's write-back governance (DATA_CONTRACT.md Section 8) applied to initial authoring
(NutriScrape SDD Section 6).

The LLM call is injected. ``anthropic`` / ``openai`` are NOT dependencies: pass any
``LLMClient`` callable, or use :func:`build_anthropic_client`, which lazily imports and guards.
"""
from __future__ import annotations

import json
import os
from typing import Any, Callable, Literal

from pydantic import BaseModel, Field

from nectar_contract.types import EvidenceTier

CONTRACT_VERSION = os.environ.get("CONTRACT_VERSION", "1.0")

EntryKind = Literal["rule", "interaction", "transform", "guideline"]
DraftStatus = Literal["pending_review", "approved", "rejected"]

# A drafter LLM: takes a prompt, returns raw text (expected to be a JSON list of candidates).
LLMClient = Callable[[str], str]


class ReviewGateError(RuntimeError):
    """Raised when a draft is asked to enter live authority without a named reviewer."""


class Citation(BaseModel):
    """A source backing a drafted entry. A citationless draft is low value and the reviewer should
    reject it; the contract rejects any patient-facing claim without citations."""

    source: str
    locator: str | None = None


class DraftEntry(BaseModel):
    """A candidate knowledge-base entry awaiting human review. Never a live authority record."""

    kind: EntryKind
    payload: dict[str, Any]
    citations: list[Citation] = Field(default_factory=list)
    rationale: str | None = None
    evidence_tier: EvidenceTier | None = None
    drafted_by: str
    confidence: float
    status: DraftStatus = "pending_review"
    reviewer: str | None = None
    contract_version: str = CONTRACT_VERSION


_PROMPT_TEMPLATE = """You are drafting candidate {kind} entries for a clinical nutrition knowledge
base. You are a drafter for HUMAN REVIEW; you have no authority to approve or publish anything.

Rules:
- Propose entries only as a JSON list. Each item must have: payload, citations, rationale,
  confidence (0..1), evidence_tier (A, B, or C).
- Every entry MUST cite real sources in `citations` (each with a `source`, optional `locator`).
- Do not invent nutrient numbers; cite them to a source. Do not set a status or a reviewer.

Context:
{context}
"""


def build_prompt(kind: EntryKind, context: str) -> str:
    """Build the drafter prompt for a given entry kind and free-text context."""
    return _PROMPT_TEMPLATE.format(kind=kind, context=context)


def draft_candidates(
    kind: EntryKind,
    context: str,
    llm: LLMClient,
    *,
    drafted_by: str = "llm-drafter",
) -> list[DraftEntry]:
    """Ask an injected LLM to propose candidate ``kind`` entries and parse them into the review
    queue. Every returned entry is ``pending_review`` with no reviewer, by construction.
    """
    prompt = build_prompt(kind, context)
    raw = llm(prompt)
    return parse_draft_response(raw, kind, drafted_by)


def parse_draft_response(raw: str, kind: EntryKind, drafted_by: str) -> list[DraftEntry]:
    """Parse a raw LLM response (a JSON list, or an object wrapping ``candidates``/``entries``)
    into :class:`DraftEntry` objects. Model-supplied ``status`` and ``reviewer`` are discarded.
    """
    data: Any = json.loads(raw)
    if isinstance(data, dict):
        data = data.get("candidates", data.get("entries", []))
    if not isinstance(data, list):
        raise ValueError("draft response must be a JSON list of candidate entries")
    return [_entry_from_item(item, kind, drafted_by) for item in data]


def promote_to_live(draft: DraftEntry, reviewer: str | None) -> DraftEntry:
    """[INVARIANT] The one gate out of the review queue. Refuse without a named reviewer.

    Returns a new :class:`DraftEntry` marked ``approved`` and stamped with the reviewer; the input
    is left unchanged. Approval records the human sign-off only; persisting an approved entry to the
    graph is a separate writer's job, not this function's.
    """
    if reviewer is None or not reviewer.strip():
        raise ReviewGateError("a named reviewer is required to promote a draft to live authority")
    if draft.status == "rejected":
        raise ReviewGateError("cannot promote a rejected draft")
    return draft.model_copy(update={"status": "approved", "reviewer": reviewer.strip()})


def build_anthropic_client(model: str, *, max_tokens: int = 2048) -> LLMClient:
    """Optional convenience adapter. ``anthropic`` is NOT a dependency of this package; prefer
    injecting your own :data:`LLMClient`. This lazily imports ``anthropic`` and raises a clear
    error when it is absent.
    """
    try:
        import anthropic  # type: ignore[import-not-found]
    except ModuleNotFoundError as exc:  # pragma: no cover - depends on optional package
        raise RuntimeError(
            "anthropic is not installed; pass an LLMClient callable to draft_candidates instead"
        ) from exc

    client = anthropic.Anthropic()

    def _call(prompt: str) -> str:
        message = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        parts = [block.text for block in message.content if getattr(block, "type", None) == "text"]
        return "".join(str(part) for part in parts)

    return _call


# ----------------------------------------------------------------------------- helpers


def _entry_from_item(item: Any, kind: EntryKind, drafted_by: str) -> DraftEntry:
    citations = [_as_citation(c) for c in (item.get("citations") or [])]
    payload = item.get("payload")
    if not isinstance(payload, dict):
        payload = item if isinstance(item, dict) else {"value": item}
    return DraftEntry(
        kind=kind,
        payload=dict(payload),
        citations=citations,
        rationale=None if item.get("rationale") is None else str(item.get("rationale")),
        evidence_tier=_as_tier(item.get("evidence_tier")),
        drafted_by=drafted_by,
        confidence=_coerce_float(item.get("confidence"), 0.5),
        status="pending_review",  # [INVARIANT] never trust a model-supplied status
        reviewer=None,  # [INVARIANT] a reviewer is set only by promote_to_live
    )


def _as_citation(value: Any) -> Citation:
    if isinstance(value, dict):
        source = value.get("source") or value.get("url") or ""
        locator = value.get("locator")
        return Citation(source=str(source), locator=None if locator is None else str(locator))
    return Citation(source=str(value))


def _coerce_float(value: object, default: float) -> float:
    if isinstance(value, (int, float, str)):
        try:
            return float(value)
        except ValueError:
            return default
    return default


def _as_tier(value: object) -> EvidenceTier | None:
    if value is None:
        return None
    text = str(value).strip().upper()
    if text == "A":
        return "A"
    if text == "B":
        return "B"
    if text == "C":
        return "C"
    return None
