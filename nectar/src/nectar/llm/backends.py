"""Pluggable LLM client selected by LLM_BACKEND: ollama | anthropic | openai. One interface.

[INVARIANT] These backends are a generic text-in, text-out interface. They are used only at the
two language-model touchpoints in the query path: intake parsing (free text -> structured factors,
see abstraction/parse_history.py and interact/qa.py) and output narration (interact/explain.py).
No caller may use `generate` to set or evaluate a clinical limit, and its return value must never
be treated as a nutrient number. Thresholds, scoring, and derivation are code, never a model.

See ../../docs/PDD.md Section 2, Section 9. Invariants in ../../CLAUDE.md apply.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

import httpx

_DEFAULT_TIMEOUT_S = 60.0
_DEFAULT_MAX_TOKENS = 4096


class LLMBackendError(RuntimeError):
    """Raised when a backend cannot be constructed or a generation call fails to produce text."""


@runtime_checkable
class LLMBackend(Protocol):
    """One interface every backend implements. Text in, text out. Nothing more."""

    def generate(
        self,
        prompt: str,
        system: str | None = None,
        temperature: float | None = None,
    ) -> str:
        """Return the model's text completion for `prompt`. Never a parsed nutrient or a number
        the caller should trust as clinical data; callers that need structure parse this string
        themselves and validate it against the graph, never the reverse."""
        ...


@dataclass
class OllamaBackend:
    """Local backend, the platform default (see deploy/README.md). Talks to Ollama's HTTP API."""

    base_url: str
    model: str
    timeout: float = _DEFAULT_TIMEOUT_S

    def generate(
        self,
        prompt: str,
        system: str | None = None,
        temperature: float | None = None,
    ) -> str:
        payload: dict[str, Any] = {"model": self.model, "prompt": prompt, "stream": False}
        if system is not None:
            payload["system"] = system
        if temperature is not None:
            payload["options"] = {"temperature": temperature}
        url = f"{self.base_url.rstrip('/')}/api/generate"
        try:
            response = httpx.post(url, json=payload, timeout=self.timeout)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise LLMBackendError(f"Ollama request to {url} failed: {exc}") from exc
        data = response.json()
        text = data.get("response") if isinstance(data, dict) else None
        if not isinstance(text, str):
            raise LLMBackendError("Ollama response did not contain a 'response' text field.")
        return text


class AnthropicBackend:
    """Hosted backend. The `anthropic` SDK is an optional dependency; import it lazily so a
    deployment that never turns this backend on does not need it installed."""

    def __init__(self, api_key: str, model: str, timeout: float = _DEFAULT_TIMEOUT_S) -> None:
        try:
            import anthropic
        except ImportError as exc:
            raise LLMBackendError(
                "LLM_BACKEND=anthropic requires the 'anthropic' package, which is not installed. "
                "Install it (e.g. `pip install anthropic`) or select a different LLM_BACKEND."
            ) from exc
        self._client: Any = anthropic.Anthropic(api_key=api_key, timeout=timeout)
        self.model = model

    def generate(
        self,
        prompt: str,
        system: str | None = None,
        temperature: float | None = None,
    ) -> str:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": _DEFAULT_MAX_TOKENS,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system is not None:
            kwargs["system"] = system
        if temperature is not None:
            kwargs["temperature"] = temperature
        try:
            response = self._client.messages.create(**kwargs)
        except Exception as exc:  # SDK-specific errors; the SDK is untyped from mypy's view
            raise LLMBackendError(f"Anthropic generation failed: {exc}") from exc
        blocks = response.content
        text = getattr(blocks[0], "text", None) if blocks else None
        if not isinstance(text, str):
            raise LLMBackendError("Anthropic response did not contain text content.")
        return text


class OpenAIBackend:
    """Hosted backend. The `openai` SDK is an optional dependency; import it lazily so a
    deployment that never turns this backend on does not need it installed."""

    def __init__(self, api_key: str, model: str, timeout: float = _DEFAULT_TIMEOUT_S) -> None:
        try:
            import openai
        except ImportError as exc:
            raise LLMBackendError(
                "LLM_BACKEND=openai requires the 'openai' package, which is not installed. "
                "Install it (e.g. `pip install openai`) or select a different LLM_BACKEND."
            ) from exc
        self._client: Any = openai.OpenAI(api_key=api_key, timeout=timeout)
        self.model = model

    def generate(
        self,
        prompt: str,
        system: str | None = None,
        temperature: float | None = None,
    ) -> str:
        messages: list[dict[str, str]] = []
        if system is not None:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        kwargs: dict[str, Any] = {"model": self.model, "messages": messages}
        if temperature is not None:
            kwargs["temperature"] = temperature
        try:
            response = self._client.chat.completions.create(**kwargs)
        except Exception as exc:  # SDK-specific errors; the SDK is untyped from mypy's view
            raise LLMBackendError(f"OpenAI generation failed: {exc}") from exc
        choices = response.choices
        content = choices[0].message.content if choices else None
        if not isinstance(content, str):
            raise LLMBackendError("OpenAI response did not contain text content.")
        return content


@runtime_checkable
class LLMSettings(Protocol):
    """Structural shape of the `llm:` section of config/settings.yaml. Any object with these
    attributes (a loaded Settings instance, or a plain namespace in a test) can be passed to
    `make_backend`; this module does not import the settings loader itself."""

    backend: str
    base_url: str | None
    generation_model: str
    temperature: float | None
    api_key: str | None


def make_backend(settings: LLMSettings) -> LLMBackend:
    """Select and construct the configured backend. Backend choice and hyperparameters are
    NECTAR runtime configuration (SDD Section 7); this factory does not hardcode a default model
    or endpoint beyond what `settings` supplies."""
    backend = settings.backend.strip().lower()
    if backend == "ollama":
        if not settings.base_url:
            raise LLMBackendError("LLM_BACKEND=ollama requires LLM_BASE_URL.")
        return OllamaBackend(base_url=settings.base_url, model=settings.generation_model)
    if backend == "anthropic":
        if not settings.api_key:
            raise LLMBackendError("LLM_BACKEND=anthropic requires an API key (LLM_API_KEY).")
        return AnthropicBackend(api_key=settings.api_key, model=settings.generation_model)
    if backend == "openai":
        if not settings.api_key:
            raise LLMBackendError("LLM_BACKEND=openai requires an API key (LLM_API_KEY).")
        return OpenAIBackend(api_key=settings.api_key, model=settings.generation_model)
    raise LLMBackendError(
        f"Unknown LLM_BACKEND {settings.backend!r}; expected ollama, anthropic, or openai."
    )
