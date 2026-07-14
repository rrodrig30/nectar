"""Typed config + settings loading.

Loads `config/settings.yaml` (LLM backend, embeddings model, presentation defaults; see
../../docs/PDD.md Section 2) with shell-style `${VAR:-default}` environment expansion into a typed
`Settings` model. This is NECTAR runtime configuration only: model choice, hyperparameters, and
display defaults. It never carries a clinical threshold literal (those live in
`config/derivation/` and the contract knowledge base, read via `contract_client.py`).
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel

# nectar/config/settings.yaml, resolved relative to this file so it does not depend on cwd.
_DEFAULT_SETTINGS_PATH = Path(__file__).resolve().parents[3] / "config" / "settings.yaml"

# ${VAR} or ${VAR:-default}; default may be empty (${VAR:-}).
_ENV_REF = re.compile(r"\$\{(?P<name>[A-Za-z_][A-Za-z0-9_]*)(?::-(?P<default>[^}]*))?\}")


def _expand_env(value: str) -> str:
    """Expand `${VAR:-default}` references in `value` against the process environment.

    An unset or empty-string environment variable falls back to `default` (empty string if no
    default is given), matching POSIX `${VAR:-default}` shell semantics.
    """

    def _replace(match: re.Match[str]) -> str:
        name = match.group("name")
        default = match.group("default")
        env_value = os.environ.get(name)
        if env_value:
            return env_value
        return default if default is not None else ""

    return _ENV_REF.sub(_replace, value)


def _expand(node: Any) -> Any:
    """Recursively expand `${VAR:-default}` references through a parsed YAML tree."""
    if isinstance(node, str):
        return _expand_env(node)
    if isinstance(node, dict):
        return {key: _expand(val) for key, val in node.items()}
    if isinstance(node, list):
        return [_expand(item) for item in node]
    return node


class LLMSettings(BaseModel):
    """NECTAR's interactive LLM backend (SDD.md Section 7): parses at intake, narrates at output.
    Never sets or evaluates a clinical limit."""

    backend: Literal["ollama", "anthropic", "openai"]
    base_url: str
    generation_model: str
    temperature: float
    context_window: int


class EmbeddingSettings(BaseModel):
    model: str


class PresentationSettings(BaseModel):
    """Display-time defaults only; canonical values in the graph never change (contract Section 1.2)."""

    default_unit_system: Literal["us", "metric"] = "us"
    default_temp_scale: Literal["F", "C"] = "F"


class Settings(BaseModel):
    llm: LLMSettings
    embeddings: EmbeddingSettings
    presentation: PresentationSettings


def load_settings(path: str | Path | None = None) -> Settings:
    """Load and validate `settings.yaml`, expanding `${VAR:-default}` env references first.

    :param path: override the default `config/settings.yaml` location (used by tests).
    """
    settings_path = Path(path) if path is not None else _DEFAULT_SETTINGS_PATH
    raw = yaml.safe_load(settings_path.read_text())
    if not isinstance(raw, dict):
        raise ValueError(f"settings file {settings_path} did not parse to a mapping")
    expanded = _expand(raw)
    return Settings.model_validate(expanded)
