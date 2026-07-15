"""Cluster fingerprints into dishes. Pure except for an optional injected judge callable.

Union-find over pairs scoring above HIGH. Near-threshold pairs (LOW..HIGH) are referred to an
injected judge (the language model, promoted only at the boundary) so the granularity call is made
where it matters. Every member carries a membership confidence, and granularity favors the finer
split: a clinically distinct version stays separate rather than being averaged into a parent.
See SDD Section 5, PDD Section 7.
"""
from __future__ import annotations
import logging
from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from nutriscrape.clustering.blocking import block_by_core_signature
from nutriscrape.clustering.fingerprint import Fingerprint
from nutriscrape.clustering.score import score

logger = logging.getLogger(__name__)

HIGH = 0.75
LOW = 0.55

# Within-block scoring is O(n^2). At corpus scale a top-3 signature block for a common food combo
# (flour/sugar/butter) can hold tens of thousands of recipes, so an uncapped block would run for
# hours. Above this size a block is sub-blocked by its exact core-food set (a finer key) and, if a
# sub-block is still larger, scored in windows -- with a logged warning, never a silent cap.
MAX_BLOCK = 2000

# The LLM boundary: for a near-threshold pair, are these the same dish? Used only for LOW..HIGH.
Judge = Callable[[Fingerprint, Fingerprint], bool]


@dataclass
class Cluster:
    dish_id: str
    members: list[str]
    membership_confidence: dict[str, float]


class _UnionFind:
    def __init__(self, ids: Sequence[str]) -> None:
        self._parent: dict[str, str] = {i: i for i in ids}

    def find(self, x: str) -> str:
        root = x
        while self._parent[root] != root:
            root = self._parent[root]
        while self._parent[x] != root:      # path compression
            self._parent[x], x = root, self._parent[x]
        return root

    def union(self, a: str, b: str) -> None:
        self._parent[self.find(a)] = self.find(b)


def _same_dish(a: Fingerprint, b: Fingerprint, s: float, judge: Judge | None,
               high: float, low: float) -> bool:
    if s >= high:
        return True
    if low <= s < high and judge is not None:
        return judge(a, b)
    return False


def cluster_block(block: Sequence[Fingerprint], judge: Judge | None = None,
                  high: float = HIGH, low: float = LOW) -> list[Cluster]:
    ids = [fp.recipe_id for fp in block]
    uf = _UnionFind(ids)
    # incident edge scores per recipe, to set a membership confidence
    incident: dict[str, list[float]] = defaultdict(list)
    for i in range(len(block)):
        for j in range(i + 1, len(block)):
            a, b = block[i], block[j]
            s = score(a, b)
            if _same_dish(a, b, s, judge, high, low):
                uf.union(a.recipe_id, b.recipe_id)
                incident[a.recipe_id].append(s)
                incident[b.recipe_id].append(s)

    groups: dict[str, list[str]] = defaultdict(list)
    for rid in ids:
        groups[uf.find(rid)].append(rid)

    clusters: list[Cluster] = []
    for members in groups.values():
        members_sorted = sorted(members)
        confidence = {
            rid: (max(incident[rid]) if incident[rid] else 1.0)    # a singleton is trivially its own dish
            for rid in members_sorted
        }
        clusters.append(Cluster(dish_id=f"dish:{members_sorted[0]}", members=members_sorted,
                                membership_confidence=confidence))
    return clusters


def _cluster_bounded(block: Sequence[Fingerprint], judge: Judge | None, high: float, low: float,
                     max_block: int) -> list[Cluster]:
    """Cluster one block, keeping the O(n^2) pairwise bounded. Small blocks score in full. A block
    over `max_block` is sub-blocked by its exact core-food set; a sub-block still over `max_block`
    (many recipes with identical core foods) is scored in fixed windows, logging that cross-window
    pairs are not compared -- a bounded, disclosed approximation rather than a silent cap or a hang."""
    if len(block) <= max_block:
        return cluster_block(block, judge, high, low)

    finer: dict[frozenset[str], list[Fingerprint]] = defaultdict(list)
    for fp in block:
        finer[fp.core_foods].append(fp)
    if len(finer) > 1:
        out: list[Cluster] = []
        for sub in finer.values():
            out.extend(_cluster_bounded(sub, judge, high, low, max_block))
        return out

    logger.warning(
        "cluster: %d recipes share identical core foods; scoring in windows of %d "
        "(cross-window pairs not compared)", len(block), max_block,
    )
    windowed: list[Cluster] = []
    for start in range(0, len(block), max_block):
        windowed.extend(cluster_block(block[start:start + max_block], judge, high, low))
    return windowed


def cluster(fingerprints: Sequence[Fingerprint], judge: Judge | None = None,
            high: float = HIGH, low: float = LOW, top_n: int = 3,
            max_block: int = MAX_BLOCK) -> list[Cluster]:
    blocks = block_by_core_signature(fingerprints, top_n)
    logger.info("cluster: %d recipes in %d blocks; scoring (cap %d/block)",
                len(fingerprints), len(blocks), max_block)
    clusters: list[Cluster] = []
    for i, block in enumerate(blocks.values(), start=1):
        clusters.extend(_cluster_bounded(block, judge, high, low, max_block))
        if i % 20_000 == 0:
            logger.info("cluster: %d/%d blocks scored, %d dishes so far",
                        i, len(blocks), len(clusters))
    return clusters
