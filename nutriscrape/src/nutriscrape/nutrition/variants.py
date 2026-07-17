"""Selective variant generation. Pure, no I/O.

The as-authored variant is always materialized. Alternative preparation variants are generated
selectively, not as a full cross-product, and only for methods physically valid for the food (from
the transform table's method coverage). Broad remediation variants are generated lazily by NECTAR at
query time, not precomputed here. See PDD Section 6, SDD Section 8.
"""
from __future__ import annotations
from collections.abc import Iterable, Mapping

from nutriscrape.nutrition.transform import Preparation

# a small, culinarily sane cap so eager materialization stays bounded
MAX_EAGER_VARIANTS = 4

# The bounded alternative-method set per recipe for eager materialization (PDD Section 6). Kept here
# as the single source of truth so the transactional materialize (pipeline.py) and the corpus-scale
# bulk-materialize (bulk/materialize.py) select the identical set and produce mergeable variants.
MAX_EAGER_ALT_METHODS = 3


def alternative_methods(
    food_classes: Iterable[str],
    authored_methods: Iterable[str],
    coverage: Mapping[str, list[str]],
    cap: int = MAX_EAGER_ALT_METHODS,
) -> list[str]:
    """The bounded set of alternative cooking methods for a recipe: the union of its food classes'
    culinarily-valid methods (from config/method_coverage.yaml), minus the methods the as-authored
    preparation already uses, sorted for determinism and capped. Pure; no I/O."""
    classes = set(food_classes)
    authored = set(authored_methods)
    candidates = {method for food_class in classes for method in coverage.get(food_class, [])}
    return sorted(candidates - authored)[:cap]


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
