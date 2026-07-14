"""Block by shared core-ingredient signature to avoid quadratic comparison. Pure, no I/O.

Only recipes sharing a core-ingredient signature are scored against each other, so the corpus is
compared within blocks rather than all-pairs. See SDD Section 5, PDD Section 7.
"""
from __future__ import annotations
from collections import defaultdict
from collections.abc import Iterable

from nutriscrape.clustering.fingerprint import Fingerprint


def signature(fp: Fingerprint, top_n: int = 3) -> frozenset[str]:
    """The block key: the top-N core foods by proportion."""
    top = sorted(fp.proportions.items(), key=lambda kv: kv[1], reverse=True)[:top_n]
    return frozenset(fdc_id for fdc_id, _ in top)


def block_by_core_signature(fingerprints: Iterable[Fingerprint],
                            top_n: int = 3) -> dict[frozenset[str], list[Fingerprint]]:
    blocks: dict[frozenset[str], list[Fingerprint]] = defaultdict(list)
    for fp in fingerprints:
        blocks[signature(fp, top_n)].append(fp)
    return dict(blocks)
