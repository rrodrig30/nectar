"""POST /ask.

The two language-model touchpoints in the query path, at the ends, never in the scoring middle:
`qa.parse` turns the clinician's request into a structured query, and `explain.narrate` produces
grounded, cited prose over the engine's ranking. Neither call ever sets or evaluates a clinical
limit, and `narrate`'s grounding pass strips any uncited or out-of-set claim before it reaches this
route's response. See ../../docs/PDD.md Section 9, Section 11.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from nectar.api.deps import get_llm_backend
from nectar.api.schemas import AskRequest, AskResponse
from nectar.interact.explain import narrate
from nectar.interact.qa import parse as qa_parse
from nectar.llm.backends import LLMBackend

router = APIRouter()


@router.post("/ask", response_model=AskResponse)
def post_ask(req: AskRequest, backend: LLMBackend = Depends(get_llm_backend)) -> AskResponse:
    """Natural-language question over the current context. `allowed_citations` and
    `allowed_dishes` bound what `narrate` may reference; anything outside those sets is stripped
    by its grounding pass, not by this route."""
    query = qa_parse(req.request, backend)
    narration = narrate(
        req.ranking_summary or req.request,
        set(req.allowed_citations),
        set(req.allowed_dishes),
        backend,
    )
    return AskResponse(
        intent=query.intent,
        dishes=query.dishes,
        exclude=query.exclude,
        free_text=query.free_text,
        narration=narration,
    )
