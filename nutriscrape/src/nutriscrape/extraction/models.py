"""Two-tier LLM client: small fine-tuned tier 1, escalation to tier 2.

[INVARIANT] Extraction only, never a nutrient value. `ModelClient.extract` returns
structured fields with calibrated per-field confidence; it never computes or returns a
nutrient amount. Callers (ingredients.py, preparation.py) are responsible for keeping
nutrient numbers out of the schemas they request.

Tier 1 is a small model tuned for the common case. Any field whose confidence falls below
`escalation_threshold` triggers a re-ask of tier 2 (a larger model); only the low-confidence
fields are replaced, from tier 2's answer. The transport is thin (a single Ollama HTTP call
per tier, via httpx); the escalation logic is the point of this module.

Anthropic and OpenAI backends are optional. Neither package is a hard dependency: the
import happens lazily inside the backend's constructor and is guarded with a clear error
if the package is not installed.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol, Sequence


@dataclass(frozen=True)
class Confidence:
    """Calibrated confidence for one extraction: overall and per field."""

    overall: float
    per_field: dict[str, float]


@dataclass(frozen=True)
class ExtractionResult:
    """A structured extraction with a confidence-carrying return.

    `fields` holds structural extraction values only, per the requested schema.
    [INVARIANT] Never a nutrient amount; that is a downstream transform concern, never
    this client's.
    """

    fields: dict[str, Any]
    confidence: Confidence
    escalated: bool
    source_tier: int


class ModelBackend(Protocol):
    """One model endpoint. Returns a raw JSON object; escalation logic lives above this."""

    def complete_json(self, prompt: str, schema: Mapping[str, str]) -> dict[str, Any]:
        """Return `{"fields": {...}, "confidence": {...}}` keyed by `schema`'s field names."""
        ...


def _build_instruction(prompt: str, schema: Mapping[str, str]) -> str:
    field_docs = "\n".join(f"  - {name}: {description}" for name, description in schema.items())
    return (
        "You are a structured data extractor for recipe text. Extract ONLY the fields "
        "described below. Never estimate, infer, or state a nutrient amount (calories, "
        "grams of any nutrient, milligrams of any mineral); that is out of scope and must "
        "be omitted entirely.\n\n"
        f"Fields to extract:\n{field_docs}\n\n"
        "Respond with ONLY a JSON object of the exact shape:\n"
        '{"fields": {<one entry per field above, null if not stated>}, '
        '"confidence": {<one calibrated 0..1 confidence entry per field above>}}\n'
        "No prose, no markdown fences, no extra keys.\n\n"
        f"{prompt}"
    )


@dataclass(frozen=True)
class OllamaBackend:
    """Thin HTTP client for a local Ollama-served model. Transport only."""

    base_url: str
    model: str
    timeout_s: float = 60.0

    def complete_json(self, prompt: str, schema: Mapping[str, str]) -> dict[str, Any]:
        import httpx

        payload = {
            "model": self.model,
            "prompt": _build_instruction(prompt, schema),
            "format": "json",
            "stream": False,
        }
        response = httpx.post(f"{self.base_url}/api/generate", json=payload, timeout=self.timeout_s)
        response.raise_for_status()
        body: dict[str, Any] = response.json()
        raw_text = str(body.get("response", "{}"))
        parsed: dict[str, Any] = json.loads(raw_text)
        if "fields" not in parsed:
            # Some models ignore the envelope and return the fields directly; tolerate it.
            parsed = {"fields": parsed, "confidence": {}}
        return parsed


class AnthropicBackend:
    """Hosted Anthropic backend. Optional: the `anthropic` package is imported lazily so it
    need not be installed unless this backend is actually constructed."""

    def __init__(self, model: str, api_key: str | None = None) -> None:
        try:
            import anthropic  # type: ignore[import-not-found]
        except ImportError as exc:
            raise RuntimeError(
                "the 'anthropic' package is not installed; install it to use AnthropicBackend"
            ) from exc
        self._client = anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()
        self.model = model

    def complete_json(self, prompt: str, schema: Mapping[str, str]) -> dict[str, Any]:
        instruction = _build_instruction(prompt, schema)
        message = self._client.messages.create(
            model=self.model,
            max_tokens=1024,
            messages=[{"role": "user", "content": instruction}],
        )
        text = message.content[0].text
        parsed: dict[str, Any] = json.loads(text)
        if "fields" not in parsed:
            parsed = {"fields": parsed, "confidence": {}}
        return parsed


class OpenAIBackend:
    """Hosted OpenAI backend. Optional: the `openai` package is imported lazily so it need
    not be installed unless this backend is actually constructed."""

    def __init__(self, model: str, api_key: str | None = None) -> None:
        try:
            import openai  # type: ignore[import-not-found]
        except ImportError as exc:
            raise RuntimeError(
                "the 'openai' package is not installed; install it to use OpenAIBackend"
            ) from exc
        self._client = openai.OpenAI(api_key=api_key) if api_key else openai.OpenAI()
        self.model = model

    def complete_json(self, prompt: str, schema: Mapping[str, str]) -> dict[str, Any]:
        instruction = _build_instruction(prompt, schema)
        completion = self._client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": instruction}],
            response_format={"type": "json_object"},
        )
        text = completion.choices[0].message.content or "{}"
        parsed: dict[str, Any] = json.loads(text)
        if "fields" not in parsed:
            parsed = {"fields": parsed, "confidence": {}}
        return parsed


@dataclass(frozen=True)
class ExtractionConfig:
    """Tier model names and transport settings, sourced from the environment by default."""

    tier1_model: str = field(default_factory=lambda: os.environ.get("EXTRACT_MODEL_TIER1", "llama3.2:3b"))
    tier2_model: str = field(default_factory=lambda: os.environ.get("EXTRACT_MODEL_TIER2", "llama3.1:8b"))
    ollama_base_url: str = field(
        default_factory=lambda: os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
    )
    escalation_threshold: float = 0.6
    timeout_s: float = 60.0


def _default_tier1_backend(config: ExtractionConfig) -> ModelBackend:
    return OllamaBackend(base_url=config.ollama_base_url, model=config.tier1_model, timeout_s=config.timeout_s)


def _default_tier2_backend(config: ExtractionConfig) -> ModelBackend:
    return OllamaBackend(base_url=config.ollama_base_url, model=config.tier2_model, timeout_s=config.timeout_s)


def _split_fields_and_confidence(
    raw: Mapping[str, Any], schema: Mapping[str, str]
) -> tuple[dict[str, Any], dict[str, float]]:
    raw_fields = raw.get("fields", {}) or {}
    raw_confidence = raw.get("confidence", {}) or {}
    fields: dict[str, Any] = {}
    confidence: dict[str, float] = {}
    for name in schema:
        fields[name] = raw_fields.get(name)
        try:
            confidence[name] = float(raw_confidence.get(name, 0.5))
        except (TypeError, ValueError):
            confidence[name] = 0.5
    return fields, confidence


def _overall_confidence(per_field: Mapping[str, float]) -> float:
    """Overall confidence never exceeds the weakest field; mirrors the platform's rule that
    confidence never increases downstream of a low-confidence input."""
    if not per_field:
        return 0.5
    return min(per_field.values())


class ModelClient:
    """Two-tier extraction client. `extract` calls tier 1, escalates only the fields whose
    confidence is below threshold to tier 2, and merges the result."""

    def __init__(
        self,
        tier1: ModelBackend | None = None,
        tier2: ModelBackend | None = None,
        config: ExtractionConfig | None = None,
        escalation_threshold: float | None = None,
    ) -> None:
        cfg = config or ExtractionConfig()
        self.tier1: ModelBackend = tier1 if tier1 is not None else _default_tier1_backend(cfg)
        self.tier2: ModelBackend | None = tier2 if tier2 is not None else _default_tier2_backend(cfg)
        self.escalation_threshold = (
            escalation_threshold if escalation_threshold is not None else cfg.escalation_threshold
        )

    def extract(self, prompt: str, schema: Mapping[str, str]) -> ExtractionResult:
        """Run tier 1, escalate low-confidence fields to tier 2, return the merged result.

        [INVARIANT] `schema` must describe structural extraction fields only. Nutrient
        amounts must never be requested here; they are read from the graph via the
        four-channel transform, never from this client.
        """
        raw1 = self.tier1.complete_json(prompt, schema)
        fields, confidence = _split_fields_and_confidence(raw1, schema)
        low_confidence_fields = {
            name for name, value in confidence.items() if value < self.escalation_threshold
        }

        if not low_confidence_fields or self.tier2 is None:
            return ExtractionResult(
                fields=fields,
                confidence=Confidence(overall=_overall_confidence(confidence), per_field=confidence),
                escalated=False,
                source_tier=1,
            )

        raw2 = self.tier2.complete_json(prompt, schema)
        fields2, confidence2 = _split_fields_and_confidence(raw2, schema)
        merged_fields = dict(fields)
        merged_confidence = dict(confidence)
        for name in low_confidence_fields:
            if fields2.get(name) is not None:
                merged_fields[name] = fields2[name]
                merged_confidence[name] = confidence2[name]

        return ExtractionResult(
            fields=merged_fields,
            confidence=Confidence(overall=_overall_confidence(merged_confidence), per_field=merged_confidence),
            escalated=True,
            source_tier=2,
        )


def build_hosted_backend(provider: str, model: str, api_key: str | None = None) -> ModelBackend:
    """Construct an optional hosted backend by name ("anthropic" or "openai"). Lazy-imports
    the corresponding SDK; raises RuntimeError if it is not installed, or ValueError if the
    provider name is unknown."""
    if provider == "anthropic":
        return AnthropicBackend(model=model, api_key=api_key)
    if provider == "openai":
        return OpenAIBackend(model=model, api_key=api_key)
    raise ValueError(f"unknown hosted provider: {provider!r}")


__all__: Sequence[str] = (
    "Confidence",
    "ExtractionResult",
    "ModelBackend",
    "OllamaBackend",
    "AnthropicBackend",
    "OpenAIBackend",
    "ExtractionConfig",
    "ModelClient",
    "build_hosted_backend",
)
