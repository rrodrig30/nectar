"""Unit tests for the runtime settings overlay (operator model/display overrides)."""
import pytest

from nectar.common import runtime_settings as rs


@pytest.fixture(autouse=True)
def _clean_overlay():
    rs.reset_overrides()
    yield
    rs.reset_overrides()


def test_effective_defaults_before_any_override():
    s = rs.effective_settings()
    assert s.llm.backend in {"ollama", "anthropic", "openai"}
    assert rs.overridden_fields() == []


def test_apply_override_changes_effective_and_marks_field():
    updated = rs.apply_overrides({"temperature": 0.9, "generation_model": "llama3.2:3b"})
    assert updated.llm.temperature == 0.9
    assert updated.llm.generation_model == "llama3.2:3b"
    assert set(rs.overridden_fields()) == {"temperature", "generation_model"}
    # a fresh effective read still reflects the overlay (get_llm_backend reads this per request)
    assert rs.effective_settings().llm.temperature == 0.9


def test_none_values_are_ignored():
    rs.apply_overrides({"temperature": 0.5})
    rs.apply_overrides({"temperature": None, "unit_system": "metric"})
    assert rs.effective_settings().llm.temperature == 0.5
    assert rs.effective_settings().presentation.default_unit_system == "metric"


def test_invalid_value_is_rejected_and_overlay_unchanged():
    rs.apply_overrides({"backend": "anthropic"})
    with pytest.raises((ValueError, Exception)):
        rs.apply_overrides({"backend": "not-a-real-backend"})
    # the bad apply did not corrupt the overlay
    assert rs.effective_settings().llm.backend == "anthropic"


def test_unknown_field_rejected():
    with pytest.raises(ValueError):
        rs.apply_overrides({"nonexistent_knob": 1})


def test_reset_restores_defaults():
    default_temp = rs.effective_settings().llm.temperature
    rs.apply_overrides({"temperature": default_temp + 0.3})
    rs.reset_overrides()
    assert rs.effective_settings().llm.temperature == default_temp
    assert rs.overridden_fields() == []
