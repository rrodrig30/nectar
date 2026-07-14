"""Selective variant generation. Pure, no I/O.

The as-authored variant is always materialized. Alternative preparation variants are generated
selectively, not as a full cross-product, and only for methods physically valid for the food (from
the transform table's method coverage). Broad remediation variants are generated lazily by NECTAR at
query time, not precomputed here. See PDD Section 6, SDD Section 8.
"""
from __future__ import annotations
from collections.abc import Iterable

from nutriscrape.nutrition.transform import Preparation

# a small, culinarily sane cap so eager materialization stays bounded
MAX_EAGER_VARIANTS = 4


def select_variants(authored: Preparation, valid_methods: Iterable[str],
                    max_variants: int = MAX_EAGER_VARIANTS) -> list[Preparation]:
    """Return the as-authored prep first, then a bounded set of alternative-method preps. Only
    methods in valid_methods are eligible; the authored method and duplicates are not repeated."""
    out: list[Preparation] = [authored]
    seen: set[str] = {authored.method}
    for method in valid_methods:
        if len(out) >= max_variants:
            break
        if method in seen:
            continue
        seen.add(method)
        out.append(Preparation(method=method, cut_class=authored.cut_class,
                               water_ratio=authored.water_ratio,
                               liquid_retained_frac=authored.liquid_retained_frac,
                               time_min=authored.time_min, temp_c=authored.temp_c))
    return out
