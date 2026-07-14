"""Per-dish nutrient distribution statistics across a dish's recipe versions. Pure, no I/O.

DATA_CONTRACT.md Section 5 requires dish-level statistics (nutrient distributions across versions)
materialized on the `:Dish` node, so NECTAR can see a dish's version spread (for example, a potato
dish whose versions range 378 to 964 mg potassium) without re-reading every variant. This module only
summarizes values the four-channel transform already produced; it computes no nutrient value itself.
"""
from __future__ import annotations
from collections.abc import Sequence
from dataclasses import dataclass
from statistics import mean, median, pstdev


@dataclass(frozen=True)
class DistributionStats:
    count: int
    minimum: float
    maximum: float
    mean: float
    median: float
    stdev: float


def distribution(values: Sequence[float]) -> DistributionStats:
    """Summarize one nutrient's per-serving amounts across a dish's versions. Requires at least one
    value; a single version yields a zero-spread distribution."""
    vals = [float(v) for v in values]
    if not vals:
        raise ValueError("distribution requires at least one value")
    return DistributionStats(
        count=len(vals),
        minimum=min(vals),
        maximum=max(vals),
        mean=mean(vals),
        median=median(vals),
        stdev=pstdev(vals),
    )
