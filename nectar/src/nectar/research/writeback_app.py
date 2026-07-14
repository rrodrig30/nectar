"""FastAPI app for the gated write-back service (contract Section 8).

Runs as the `nectar-writeback` container with the promotion Neo4j role (see deploy/README.md). This
is the ONE service permitted to mutate the shared graph, and only to set evidence_tier/status on a
transform-family node through the validated promotion path. Its request handler supplies the wall
clock; the promotion logic itself stays deterministic and testable (writeback_service.py).
"""
from __future__ import annotations
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException

from nectar.research.writeback_service import (
    AuditEntry,
    GraphPromotionWriter,
    PromotionError,
    PromotionRequest,
)


def create_app(writer: GraphPromotionWriter | None = None) -> FastAPI:
    """Build the service. `writer` may be injected for tests; in production it is created lazily
    from the environment on first request so importing the module never opens a Neo4j connection."""
    app = FastAPI(title="NECTAR write-back service")
    state: dict[str, GraphPromotionWriter | None] = {"writer": writer}

    def _writer() -> GraphPromotionWriter:
        w = state["writer"]
        if w is None:
            w = GraphPromotionWriter.from_env()
            state["writer"] = w
        return w

    @app.post("/research/verify", response_model=AuditEntry)
    def verify(request: PromotionRequest) -> AuditEntry:
        try:
            return _writer().promote(request, timestamp=datetime.now(timezone.utc).isoformat())
        except PromotionError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    return app


app = create_app()
