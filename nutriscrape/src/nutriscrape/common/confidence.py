"""Confidence propagation. [INVARIANT] A value never has higher confidence than its inputs.

Pure, no I/O. Confidence is tracked from extraction through transform to the stored fact, and never
increases downstream of a low-confidence input. See nutriscrape SDD Section 7, DATA_CONTRACT Section 1.1.
"""
from __future__ import annotations
from collections.abc import Iterable


def clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def propagate(inputs: Iterable[float], *, floor: float = 0.5) -> float:
    """Downstream confidence is at most the minimum input confidence. With no inputs, returns the
    floor (a neutral default), never a higher value."""
    vals = [clamp01(v) for v in inputs]
    if not vals:
        return clamp01(floor)
    return clamp01(min(vals))


def penalize(confidence: float, factor: float) -> float:
    """Apply a multiplicative penalty for an added estimation step. factor in [0, 1]. Can only
    lower confidence, never raise it."""
    return clamp01(confidence) * clamp01(factor)
