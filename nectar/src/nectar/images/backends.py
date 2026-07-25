"""Pluggable text-to-image backend for dish illustrations, selected by IMAGE_BACKEND.

Mirrors llm/backends.py: one interface, a real HTTP client per provider, config-driven and optional.
`backend_from_env()` returns None when nothing is configured, so the API can report the feature as
unavailable rather than fake an image. The output is a synthetic illustration for presentation only,
never a photograph of the actual dish and never a clinical or nutrient value.
"""
from __future__ import annotations

import base64
import os
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

import httpx

_DEFAULT_TIMEOUT_S = 120.0


class ImageBackendError(RuntimeError):
    """Raised when a backend cannot be constructed or a generation call fails to produce an image."""


@runtime_checkable
class ImageBackend(Protocol):
    """One interface: a text prompt in, PNG bytes out."""

    def generate(self, prompt: str) -> bytes:
        """Return PNG bytes for `prompt`, or raise ImageBackendError. The bytes are a synthetic
        illustration for display only; they are never interpreted as data about the real dish."""
        ...


@dataclass
class OpenAIImageBackend:
    """OpenAI Images API (gpt-image-1 / dall-e-3). Requests b64 PNG so no second fetch is needed."""

    api_key: str
    model: str = "gpt-image-1"
    base_url: str = "https://api.openai.com/v1"
    size: str = "1024x1024"
    timeout: float = _DEFAULT_TIMEOUT_S

    def generate(self, prompt: str) -> bytes:
        payload = {"model": self.model, "prompt": prompt, "n": 1, "size": self.size}
        # dall-e-* needs response_format; gpt-image-1 returns b64_json without it and rejects it.
        if self.model.startswith("dall-e"):
            payload["response_format"] = "b64_json"
        try:
            resp = httpx.post(
                f"{self.base_url}/images/generations",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json=payload,
                timeout=self.timeout,
            )
            resp.raise_for_status()
            data = resp.json()
            b64 = data["data"][0]["b64_json"]
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text[:300] if exc.response is not None else str(exc)
            raise ImageBackendError(f"image API returned {exc.response.status_code}: {detail}") from exc
        except (httpx.HTTPError, KeyError, IndexError, ValueError) as exc:
            raise ImageBackendError(f"image generation failed: {exc}") from exc
        return base64.b64decode(b64)


def backend_from_env() -> ImageBackend | None:
    """Build the configured image backend, or None if image generation is not set up.

    IMAGE_BACKEND selects the provider (currently `openai`). The key comes from IMAGE_API_KEY, or the
    shared LLM_API_KEY, so one OpenAI key covers text and images. IMAGE_MODEL / IMAGE_BASE_URL /
    IMAGE_SIZE override the defaults. Returns None (feature unavailable) when unconfigured.
    """
    backend = (os.environ.get("IMAGE_BACKEND") or "").strip().lower()
    if backend in ("", "none", "off", "disabled"):
        return None
    if backend == "openai":
        api_key = os.environ.get("IMAGE_API_KEY") or os.environ.get("LLM_API_KEY")
        if not api_key:
            return None
        return OpenAIImageBackend(
            api_key=api_key,
            model=os.environ.get("IMAGE_MODEL") or "gpt-image-1",
            base_url=os.environ.get("IMAGE_BASE_URL") or "https://api.openai.com/v1",
            size=os.environ.get("IMAGE_SIZE") or "1024x1024",
        )
    raise ImageBackendError(f"unknown IMAGE_BACKEND {backend!r} (expected 'openai' or unset)")


def prompt_for_dish(name: str) -> str:
    """A food-illustration prompt from a dish name. Kept plainly descriptive; the UI labels the result
    as an AI illustration, so the prompt aims for a representative plated dish, not a specific claim."""
    clean = " ".join((name or "a prepared dish").split())[:200]
    return (
        f"A single serving of {clean}, plated appetizingly on a simple white plate, "
        "overhead natural daylight, clean neutral background, realistic home-cooked food, "
        "no text, no labels, no people."
    )
