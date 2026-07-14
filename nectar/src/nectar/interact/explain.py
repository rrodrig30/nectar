"""LLM at the back: grounded, cited narration over the engine ranking (GraphRAG). [INVARIANT].

The narrator may only cite retrieved guideline nodes and may only reference dishes in the ranked set,
and it reads nutrient numbers from the graph facts it is given, never inventing them. A grounding
pass strips any sentence that cites an unretrieved guideline, names an out-of-set dish, or makes a
numeric claim with no citation. No citations means the claim does not reach the clinician.
See ../../docs/PDD.md Section 9, SDD Section 7, DATA_CONTRACT Section 7.
"""
from __future__ import annotations
import re

from nectar.llm.backends import LLMBackend

# markers the narrator must use: [[guideline_id]] for a citation, {{dish_id}} for a dish reference
_CITE = re.compile(r"\[\[([^\]]+)\]\]")
_DISH = re.compile(r"\{\{([^}]+)\}\}")
_SENTENCE = re.compile(r"[^.!?]*[.!?]")

_SYSTEM = ("Narrate the ranking in grounded prose. Cite every clinical claim with [[guideline_id]] "
           "from the provided guidelines only. Reference dishes only as {{dish_id}} from the ranked "
           "set. Use only the nutrient numbers provided. Do not invent recipes, citations, or numbers.")


def _sentences(text: str) -> list[str]:
    found = [s.strip() for s in _SENTENCE.findall(text) if s.strip()]
    return found or ([text.strip()] if text.strip() else [])


def ground(text: str, allowed_citations: set[str], allowed_dishes: set[str]) -> str:
    """Keep only grounded sentences. Strips: a sentence citing a guideline not retrieved, a sentence
    naming a dish not in the ranked set, and a numeric claim carrying no citation."""
    kept: list[str] = []
    for sent in _sentences(text):
        cites = _CITE.findall(sent)
        dishes = _DISH.findall(sent)
        if any(c not in allowed_citations for c in cites):
            continue
        if any(d not in allowed_dishes for d in dishes):
            continue
        if any(ch.isdigit() for ch in sent) and not cites:
            continue
        kept.append(sent)
    return " ".join(kept)


def narrate(ranking_summary: str, allowed_citations: set[str], allowed_dishes: set[str],
            backend: LLMBackend) -> str:
    """Generate a narration then ground it. The returned prose contains only grounded, cited claims."""
    raw = backend.generate(ranking_summary, system=_SYSTEM)
    return ground(raw, allowed_citations, allowed_dishes)
