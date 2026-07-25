"""Unit tests for the dish-illustration backend selection and prompt (no network)."""
import pytest

from nectar.images.backends import (
    ImageBackendError,
    OpenAIImageBackend,
    backend_from_env,
    prompt_for_dish,
)


def test_backend_none_when_unconfigured(monkeypatch):
    for k in ("IMAGE_BACKEND", "IMAGE_API_KEY", "LLM_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    assert backend_from_env() is None                       # feature cleanly off, never faked


def test_openai_backend_requires_a_key(monkeypatch):
    monkeypatch.setenv("IMAGE_BACKEND", "openai")
    for k in ("IMAGE_API_KEY", "LLM_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    assert backend_from_env() is None                       # no key -> unavailable, not an error


def test_openai_backend_built_from_key(monkeypatch):
    monkeypatch.setenv("IMAGE_BACKEND", "openai")
    monkeypatch.setenv("IMAGE_API_KEY", "sk-test")
    monkeypatch.setenv("IMAGE_MODEL", "dall-e-3")
    backend = backend_from_env()
    assert isinstance(backend, OpenAIImageBackend)
    assert backend.api_key == "sk-test" and backend.model == "dall-e-3"


def test_unknown_backend_raises(monkeypatch):
    monkeypatch.setenv("IMAGE_BACKEND", "stability")
    with pytest.raises(ImageBackendError):
        backend_from_env()


def test_prompt_is_descriptive_and_bounded():
    p = prompt_for_dish("Chicken Soup")
    assert "chicken soup" in p.lower() and "no text" in p.lower()
    assert len(prompt_for_dish("x" * 500)) < 400            # over-long names are truncated
