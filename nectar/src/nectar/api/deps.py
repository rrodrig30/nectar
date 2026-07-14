"""FastAPI dependencies: settings, the read-only contract client, the LLM backend, and auth.

Every dependency here is a plain function usable with `Depends`, never a module-level instance, so
tests can swap behavior with `app.dependency_overrides[get_x] = fake_x` without touching process
state or a live Neo4j/LLM backend. Production callers get cached singletons (`lru_cache`); a test
override replaces the function entirely and never runs the cached path.

See ../../docs/PDD.md Section 4, Section 11. Invariants in ../../CLAUDE.md apply.
"""
from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache
from typing import Literal

from fastapi import Depends, Header, HTTPException

from nectar.common.config import Settings, load_settings
from nectar.common.contract_client import ContractClient
from nectar.llm.backends import LLMBackend, make_backend

# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def _settings_singleton() -> Settings:
    return load_settings()


def get_settings() -> Settings:
    """NECTAR runtime configuration (LLM backend choice, hyperparameters, display defaults).
    Never a clinical threshold; those come from the contract knowledge base and the derivation
    config (config/equations.yaml, config/conditions/), not through this dependency."""
    return _settings_singleton()


# ---------------------------------------------------------------------------
# Contract client (read-only Neo4j access)
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def _contract_client_singleton() -> ContractClient:
    return ContractClient.from_env()


def get_contract_client() -> ContractClient:
    """A read-only accessor over the shared graph (NECTAR holds the read role; see
    ../../../deploy/README.md). Routes never open a Neo4j write session; the sole write path is
    `research/verify.py` to the gated promotion service, wired in `routes/research.py`."""
    return _contract_client_singleton()


# ---------------------------------------------------------------------------
# LLM backend (the two interactive touchpoints: intake parsing, output narration)
# ---------------------------------------------------------------------------


@dataclass
class _BackendSettingsAdapter:
    """Adapts `common.config.LLMSettings` (no `api_key` field; it is a runtime secret, not
    settings-file configuration) to the structural `llm.backends.LLMSettings` protocol, which
    needs one. The key is read from `LLM_API_KEY` at call time, never hardcoded."""

    backend: str
    base_url: str | None
    generation_model: str
    temperature: float | None
    api_key: str | None


def get_llm_backend(settings: Settings = Depends(get_settings)) -> LLMBackend:
    """Construct the configured backend (Ollama, Anthropic, or OpenAI) from `settings.llm`.
    [INVARIANT] This backend is text-in, text-out only; callers never treat its output as a
    nutrient number or a clinical limit (see llm/backends.py)."""
    adapter = _BackendSettingsAdapter(
        backend=settings.llm.backend,
        base_url=settings.llm.base_url,
        generation_model=settings.llm.generation_model,
        temperature=settings.llm.temperature,
        api_key=os.environ.get("LLM_API_KEY"),
    )
    return make_backend(adapter)


# ---------------------------------------------------------------------------
# Auth (role-scoped; permissive by default, present so a real IdP can slot in later)
# ---------------------------------------------------------------------------

Role = Literal["researcher", "reviewer", "admin"]

_ALL_ROLES: frozenset[Role] = frozenset({"researcher", "reviewer", "admin"})
# Fail closed: an absent header yields the least-privileged role, never admin. A missing edge
# identity must not silently grant the write-back scope (require_role gates that path).
_DEFAULT_ROLE: Role = "researcher"


def get_current_role(
    x_nectar_role: str | None = Header(default=None, alias="X-NECTAR-Role"),
) -> Role:
    """Stub auth: trusts an `X-NECTAR-Role` header and defaults to the LEAST-privileged role when
    absent, so a misconfigured edge fails closed rather than granting admin. A deployment that
    terminates auth at the edge (see ../../../deploy/README.md) sets this header from the verified
    identity; this dependency does not itself authenticate the caller."""
    if x_nectar_role is None:
        return _DEFAULT_ROLE
    role = x_nectar_role.strip().lower()
    if role not in _ALL_ROLES:
        raise HTTPException(status_code=401, detail=f"unknown role {x_nectar_role!r}")
    return role


def require_role(*allowed: Role) -> Callable[[Role], Role]:
    """Build a dependency that rejects any role outside `allowed`. Used to scope the research
    write-back path (`research/verify.py`) to reviewer/admin roles; every other route stays
    permissive by default per `get_current_role`."""
    allowed_set = frozenset(allowed)

    def _check(role: Role = Depends(get_current_role)) -> Role:
        if role not in allowed_set:
            raise HTTPException(
                status_code=403,
                detail=f"role {role!r} is not permitted; requires one of {sorted(allowed_set)}",
            )
        return role

    return _check
