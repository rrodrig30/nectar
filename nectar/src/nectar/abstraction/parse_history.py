"""LLM: free-text PMH -> structured factors ONLY. [INVARIANT] Never a number.

A language model may turn narrative history into structured factors (condition names, medication
names, flags). The factor-to-number step is code (derive.py), never the model. This module returns
factor labels only; it does not read labs, set thresholds, or emit any numeric value.
See ../../docs/PDD.md Section 5.2, SDD Section 3.3.
"""
from __future__ import annotations
from collections.abc import Callable
from dataclasses import dataclass, field

# A Parser is an injected LLM boundary: free text -> lists of factor strings. Kept abstract so this
# module has no hard model dependency and stays unit-testable.
Parser = Callable[[str], dict[str, list[str]]]


@dataclass(frozen=True)
class ParsedFactors:
    conditions: list[str] = field(default_factory=list)
    medications: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _looks_free_text(item: str) -> bool:
    # a short token (an icd10 code or a single condition name) is already structured; a sentence is not
    return len(item.split()) > 3


def _coerce(raw: dict[str, list[str]]) -> ParsedFactors:
    return ParsedFactors(
        conditions=[str(c).strip().lower() for c in raw.get("conditions", []) if str(c).strip()],
        medications=[str(m).strip().lower() for m in raw.get("medications", []) if str(m).strip()],
        notes=[str(n).strip() for n in raw.get("notes", []) if str(n).strip()],
    )


def parse_history(pmh: list[str] | str, parser: Parser | None = None) -> ParsedFactors:
    """Coded items pass through as factors. Free text is handed to the injected parser (the LLM
    boundary). With no parser, only already-structured items become factors. No number is produced."""
    if isinstance(pmh, str):
        free_text, coded = pmh, []
    else:
        free_text = "\n".join(p for p in pmh if _looks_free_text(p))
        coded = [p.strip().lower() for p in pmh if p.strip() and not _looks_free_text(p)]

    if free_text.strip() and parser is not None:
        parsed = _coerce(parser(free_text))
        return ParsedFactors(conditions=coded + parsed.conditions,
                             medications=parsed.medications, notes=parsed.notes)
    return ParsedFactors(conditions=coded)
