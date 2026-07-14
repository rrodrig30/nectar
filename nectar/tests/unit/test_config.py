"""Unit tests for settings loading and ${VAR:-default} env expansion. No database required."""
from __future__ import annotations

from pathlib import Path

import pytest

from nectar.common.config import Settings, load_settings

_SETTINGS_YAML = """
llm:
  backend: ${LLM_BACKEND:-ollama}
  base_url: ${LLM_BASE_URL:-http://ollama:11434}
  generation_model: ${LLM_GENERATION_MODEL:-llama3.1:8b}
  temperature: ${LLM_TEMPERATURE:-0.2}
  context_window: ${LLM_CONTEXT_WINDOW:-8192}
embeddings:
  model: ${EMBEDDING_MODEL:-sentence-transformers/all-MiniLM-L6-v2}
presentation:
  default_unit_system: us
  default_temp_scale: F
"""


def _write_settings(tmp_path: Path) -> Path:
    path = tmp_path / "settings.yaml"
    path.write_text(_SETTINGS_YAML)
    return path


def test_defaults_apply_when_env_unset(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LLM_BACKEND", raising=False)
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    monkeypatch.delenv("LLM_TEMPERATURE", raising=False)
    monkeypatch.delenv("LLM_CONTEXT_WINDOW", raising=False)
    settings = load_settings(_write_settings(tmp_path))
    assert isinstance(settings, Settings)
    assert settings.llm.backend == "ollama"
    assert settings.llm.base_url == "http://ollama:11434"
    assert settings.llm.temperature == pytest.approx(0.2)
    assert settings.llm.context_window == 8192
    assert settings.embeddings.model == "sentence-transformers/all-MiniLM-L6-v2"
    assert settings.presentation.default_unit_system == "us"
    assert settings.presentation.default_temp_scale == "F"


def test_env_override_wins_over_default(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_BACKEND", "anthropic")
    monkeypatch.setenv("LLM_GENERATION_MODEL", "claude-sonnet")
    monkeypatch.setenv("LLM_TEMPERATURE", "0.7")
    settings = load_settings(_write_settings(tmp_path))
    assert settings.llm.backend == "anthropic"
    assert settings.llm.generation_model == "claude-sonnet"
    assert settings.llm.temperature == pytest.approx(0.7)


def test_real_settings_file_loads(monkeypatch: pytest.MonkeyPatch) -> None:
    """The checked-in nectar/config/settings.yaml parses and validates with no env overrides."""
    for var in (
        "LLM_BACKEND",
        "LLM_BASE_URL",
        "LLM_GENERATION_MODEL",
        "LLM_TEMPERATURE",
        "LLM_CONTEXT_WINDOW",
        "EMBEDDING_MODEL",
    ):
        monkeypatch.delenv(var, raising=False)
    settings = load_settings()
    assert settings.llm.backend == "ollama"
    assert settings.presentation.default_unit_system in ("us", "metric")


def test_missing_mapping_raises(tmp_path: Path) -> None:
    path = tmp_path / "settings.yaml"
    path.write_text("- not\n- a\n- mapping\n")
    with pytest.raises(ValueError, match="did not parse to a mapping"):
        load_settings(path)
