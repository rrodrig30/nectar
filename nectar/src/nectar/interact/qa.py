"""LLM at the front: a clinician request becomes a structured query. [INVARIANT] Parse only.

The model parses intent into structured fields; it never sets a clinical limit or emits a nutrient
number. This is one of the two language-model touchpoints in the query path, at the ends, never in
the scoring middle. See ../../docs/PDD.md Section 9, SDD Section 7.
"""
from __future__ import annotations
import json
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

from nectar.llm.backends import LLMBackend

QueryIntent = Literal["recommend", "plan", "ask", "modify", "research"]

_SYSTEM = ("Convert the clinician request into a compact JSON object with keys: intent (one of "
           "recommend, plan, ask, modify, research), dishes (list of dish names), exclude (list of "
           "equipment or ingredient limits), free_text (the residual question). Do not provide any "
           "nutrition number or clinical limit.")


class StructuredQuery(BaseModel):
    intent: QueryIntent = "ask"
    dishes: list[str] = Field(default_factory=list)
    exclude: list[str] = Field(default_factory=list)
    free_text: str = ""


def parse(request: str, backend: LLMBackend) -> StructuredQuery:
    """Parse a request via the backend, falling back to a plain free-text query if the model output
    is not valid structured JSON. No clinical number is ever taken from the model here."""
    raw = backend.generate(request, system=_SYSTEM)
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return StructuredQuery(free_text=request)
    if not isinstance(data, dict):
        return StructuredQuery(free_text=request)
    data.setdefault("free_text", request)
    try:
        return StructuredQuery.model_validate(data)
    except ValidationError:
        return StructuredQuery(free_text=request)
