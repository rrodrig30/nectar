"""FastAPI application factory. Read-oriented surface; the sole write path is
`routes/research.py` -> `research/verify.py` -> the gated promotion service.

See ../../docs/PDD.md Section 11 for the route table. Invariants in ../../CLAUDE.md apply.
"""
from __future__ import annotations

from fastapi import FastAPI

from nectar.api.routes import ask, catalog, plan, recommend, research, settings


def create_app() -> FastAPI:
    """Build the NECTAR API. Routers are included here rather than at import time so tests can
    build independent app instances (each with its own `dependency_overrides`) without module-
    level state leaking between them."""
    app = FastAPI(
        title="NECTAR",
        description=(
            "Clinician-facing research and educational tool. Not medical nutrition therapy; "
            "not validated for individual patient care."
        ),
        version="1.0",
    )
    app.include_router(catalog.router)
    app.include_router(settings.router)
    app.include_router(recommend.router)
    app.include_router(plan.router)
    app.include_router(ask.router)
    app.include_router(research.router)
    return app


# uvicorn nectar.api.app:app (see ../../Makefile `make api`)
app = create_app()
