"""Cluster fingerprints into dishes. Pure except for an optional injected judge callable.

Union-find over pairs scoring above HIGH. Near-threshold pairs (LOW..HIGH) are referred to an
injected judge (the language model, promoted only at the boundary) so the granularity call is made
where it matters. Every member carries a membership confidence, and granularity favors the finer
split: a clinically distinct version stays separate rather than being averaged into a parent.
See SDD Section 5, PDD Section 7.
"""
from __future__ import annotations
from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from nutriscrape.clustering.blocking import block_by_core_signature
from nutriscrape.clustering.fingerprint import Fingerprint
from nutriscrape.clustering.score import score

HIGH = 0.75
LOW = 0.55

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


def cluster(fingerprints: Sequence[Fingerprint], judge: Judge | None = None,
            high: float = HIGH, low: float = LOW, top_n: int = 3) -> list[Cluster]:
    clusters: list[Cluster] = []
    for block in block_by_core_signature(fingerprints, top_n).values():
        clusters.extend(cluster_block(block, judge, high, low))
    return clusters
