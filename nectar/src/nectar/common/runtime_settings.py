"""Runtime settings overlay: operator overrides on top of the config-loaded defaults.

NECTAR's runtime configuration (LLM backend, model, hyperparameters, display defaults) is loaded
from `config/settings.yaml` with env expansion (see `config.py`). The operator surface (SDD Section
7) lets a running server be re-tuned without a restart: this module holds an in-process override
overlay and recomputes the effective `Settings` each call, so the per-request `get_llm_backend`
picks up a change on the next request. Defaults remain config/env-driven; overrides live only in
this process and reset to the config values on restart. [INVARIANT] No clinical threshold is a
setting; these are model/display knobs only.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Any

from nectar.common.config import Settings, load_settings

# Flat API field name -> (section, key) within the nested Settings model. Only these fields may be
# overridden; anything else is rejected. API keys are never here (they are a runtime secret read
# from the environment, not settings).
_FIELD_MAP: dict[str, tuple[str, str]] = {
    "backend": ("llm", "backend"),
    "base_url": ("llm", "base_url"),
    "generation_model": ("llm", "generation_model"),
    "temperature": ("llm", "temperature"),
    "context_window": ("llm", "context_window"),
    "embedding_model": ("embeddings", "model"),
    "unit_system": ("presentation", "default_unit_system"),
    "temp_scale": ("presentation", "default_temp_scale"),
}

_overrides: dict[str, Any] = {}


@lru_cache(maxsize=1)
def _base() -> Settings:
    """The config/env defaults, loaded once."""
    return load_settings()


def _merge(overrides: dict[str, Any]) -> Settings:
    """Apply a flat override set onto the base settings and validate the result."""
    data = _base().model_dump()
    for field, value in overrides.items():
        section, key = _FIELD_MAP[field]
        data[section][key] = value
    return Settings.model_validate(data)  # raises on an invalid value (e.g. bad backend/scale)


def effective_settings() -> Settings:
    """The current settings: config defaults with any operator overrides applied."""
    return _merge(_overrides)


def overridden_fields() -> list[str]:
    """Flat field names currently overridden (for the UI to mark them as non-default)."""
    return sorted(_overrides)


def apply_overrides(patch: dict[str, Any]) -> Settings:
    """Merge `patch` (flat field -> value; None ignored) into the overlay after validating the
    resulting settings. Unknown fields are rejected. Returns the new effective settings."""
    merged = dict(_overrides)
    for field, value in patch.items():
        if value is None:
            continue
        if field not in _FIELD_MAP:
            raise ValueError(f"unknown setting: {field!r}")
        merged[field] = value
    validated = _merge(merged)  # validates before we commit the overlay
    _overrides.clear()
    _overrides.update(merged)
    return validated


def reset_overrides() -> Settings:
    """Drop all overrides; effective settings return to the config defaults."""
    _overrides.clear()
    return effective_settings()
