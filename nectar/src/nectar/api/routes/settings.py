"""GET/PUT /settings and GET /settings/models - the operator model/display surface (SDD Section 7).

Runtime configuration only: LLM backend, model, hyperparameters, and display defaults. Overrides
are applied in-process over the config/env defaults and take effect on the next request; they are
not persisted (config remains the source of the default). [INVARIANT] No clinical threshold is a
setting, and an API key is never accepted or returned here (it is an environment secret).
"""
from __future__ import annotations

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import ValidationError

from nectar.api.schemas import SettingsOut, SettingsUpdate
from nectar.common.config import Settings
from nectar.common.runtime_settings import (
    apply_overrides,
    effective_settings,
    overridden_fields,
    reset_overrides,
)

router = APIRouter()


def _to_out(s: Settings) -> SettingsOut:
    return SettingsOut(
        backend=s.llm.backend,
        base_url=s.llm.base_url,
        generation_model=s.llm.generation_model,
        temperature=s.llm.temperature,
        context_window=s.llm.context_window,
        embedding_model=s.embeddings.model,
        unit_system=s.presentation.default_unit_system,
        temp_scale=s.presentation.default_temp_scale,
        overridden=overridden_fields(),
    )


@router.get("/settings", response_model=SettingsOut)
def get_settings_endpoint() -> SettingsOut:
    """The effective runtime settings (config defaults with any operator overrides applied)."""
    return _to_out(effective_settings())


@router.put("/settings", response_model=SettingsOut)
def put_settings(update: SettingsUpdate) -> SettingsOut:
    """Apply an operator override. Only the provided fields change; the result is validated before
    it takes effect, so an invalid value (bad backend, non-numeric temperature) is rejected 422."""
    try:
        settings = apply_overrides(update.model_dump(exclude_unset=True))
    except (ValueError, ValidationError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _to_out(settings)


@router.delete("/settings", response_model=SettingsOut)
def reset_settings() -> SettingsOut:
    """Drop all operator overrides; effective settings return to the config/env defaults."""
    return _to_out(reset_overrides())


@router.get("/settings/models", response_model=list[str])
def get_models() -> list[str]:
    """Models available from the active backend, for the model picker. Ollama exposes them at
    `/api/tags`; other backends have no discovery endpoint, so the list is empty and the UI falls
    back to a free-text model field. A backend that cannot be reached yields an empty list, not an
    error, so the settings page still loads."""
    settings = effective_settings()
    if settings.llm.backend != "ollama":
        return []
    try:
        resp = httpx.get(f"{settings.llm.base_url}/api/tags", timeout=5.0)
        resp.raise_for_status()
        models = resp.json().get("models", [])
    except (httpx.HTTPError, ValueError):
        return []
    names = [str(m["name"]) for m in models if isinstance(m, dict) and "name" in m]
    return sorted(names)
