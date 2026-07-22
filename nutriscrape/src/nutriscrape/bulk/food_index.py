"""In-memory FDC food resolver for the bulk-load path.

The transactional ingest resolves each ingredient with a Neo4j full-text query. That round trip is
the single-thread throughput wall (~0.6 rec/s) and forces the parallelism that deadlocks on the
shared :Nutrient supernodes. The FDC bulk export is small (~8k foods), so the bulk path loads it
once into memory, builds a token inverted index, and ranks candidates with the SAME
`matcher.best_match` scorer the graph path uses. No Neo4j, no per-ingredient round trip: resolution
becomes a dict lookup plus a small in-memory rank, so the compute stage is CPU-bound and trivially
parallel. It never asserts a nutrient value; it only identifies a canonical FDC id whose raw vector
the four-channel transform reads verbatim.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from nutriscrape.acquisition.parse import normalize_food_query
from nutriscrape.common.config import load_config
from nutriscrape.resolution.fdc_bulk import iter_bulk_foods
from nutriscrape.resolution.fdc_client import FdcCandidate
from nutriscrape.resolution.matcher import best_match, stem

_TOKEN_RE = re.compile(r"[a-z0-9]+")
# Cap candidate generation: a common token ("cheese") posts to many foods; ranking them all is
# wasted work when the top match is decided by token overlap. Bounds per-lookup cost at scale.
_MAX_CANDIDATES = 400


@dataclass(frozen=True)
class ResolvedFood:
    """The identity of a resolved FDC food (mirror of pipeline.ResolvedFood, kept local so the bulk
    path has no dependency on the transactional pipeline module)."""

    fdc_id: str
    description: str
    data_type: str


class FoodIndex:
    """Token-indexed, in-memory view of the FDC bulk export for fast candidate-and-rank resolution."""

    def __init__(self) -> None:
        self._desc: dict[str, tuple[str, str]] = {}          # fdc_id -> (description, data_type)
        self._vectors: dict[str, dict[str, float]] = {}      # fdc_id -> raw per-100g vector
        self._postings: dict[str, list[str]] = {}            # token -> [fdc_id]
        self._cache: dict[str, ResolvedFood | None] = {}     # normalized query -> resolution
        self._aliases: dict[str, str] = {}                   # ambiguous staple -> canonical query
        self._modifiers: frozenset[str] = frozenset()        # prep-state words to strip before match

    @classmethod
    def from_fdc_csv(
        cls, csv_dir: str | Path, config_dir: str | Path | None = None
    ) -> "FoodIndex":
        """Build the index from the FDC CSV bulk export (food.csv / nutrient.csv / food_nutrient.csv),
        reusing `iter_bulk_foods` so nutrient mapping and unit handling match the graph fdc-import."""
        index = cls()
        index._aliases, index._modifiers = _load_alias_config(config_dir)
        for food in iter_bulk_foods(csv_dir, config_dir=config_dir):
            index._add(food.fdc_id, food.description, food.data_type, food.raw_per_100g)
        return index

    def _add(
        self, fdc_id: str, description: str, data_type: str, raw_vector: dict[str, float]
    ) -> None:
        self._desc[fdc_id] = (description, data_type)
        self._vectors[fdc_id] = raw_vector
        # Post under stemmed tokens so a singular/plural query reaches this food (query "egg" and
        # "eggs" both find "Eggs, ..."; matcher.stem is the same stemmer the scorer uses).
        for token in {stem(t) for t in _TOKEN_RE.findall(description.lower())}:
            self._postings.setdefault(token, []).append(fdc_id)

    def __len__(self) -> int:
        return len(self._desc)

    def raw_vector(self, fdc_id: str) -> dict[str, float]:
        return self._vectors.get(fdc_id, {})

    def resolve(self, food_str: str) -> ResolvedFood | None:
        """Resolve a raw ingredient food string to its best FDC food, or None below threshold.

        Normalizes the string (drops quantity/unit/packaging noise), gathers candidate foods that
        share a token, and ranks them with `matcher.best_match` (token overlap + data-type
        preference), memoized on the normalized key so repeated ingredients cost one dict hit.
        """
        key = normalize_food_query(food_str) or food_str.strip().lower()
        cached = self._cache.get(key, _MISS)
        if cached is not _MISS:
            return cached  # type: ignore[return-value]

        # Strip preparation-state words ("melted butter" -> "butter") then expand an ambiguous staple
        # to its canonical query, so a modified staple still reaches the base food. Cache stays keyed
        # on the original normalized string; if stripping removes everything, fall back to it.
        stripped = " ".join(t for t in key.split() if t not in self._modifiers) or key
        query = self._aliases.get(stripped, stripped)
        tokens = [stem(t) for t in _TOKEN_RE.findall(query)]
        candidate_ids: list[str] = []
        seen: set[str] = set()
        for tok in tokens:
            for fid in self._postings.get(tok, ()):
                if fid not in seen:
                    seen.add(fid)
                    candidate_ids.append(fid)
            if len(candidate_ids) >= _MAX_CANDIDATES:
                break

        candidates = [
            FdcCandidate(fdc_id=int(fid), description=self._desc[fid][0],
                         data_type=self._desc[fid][1], score=0.0)
            for fid in candidate_ids
        ]
        best = best_match(query, candidates)   # score against the (possibly aliased) query, not key
        resolved = (
            None if best is None
            else ResolvedFood(fdc_id=str(best.candidate.fdc_id),
                              description=best.candidate.description,
                              data_type=best.candidate.data_type)
        )
        self._cache[key] = resolved
        return resolved


def _load_alias_config(
    config_dir: str | Path | None,
) -> tuple[dict[str, str], frozenset[str]]:
    """Load config/food_aliases.yaml into (aliases, modifiers). Aliases map a normalized staple word
    to a canonical query; modifiers are prep-state words stripped before the match. Keys/values are
    lowercased and whitespace-collapsed to match `normalize_food_query` output. Missing or malformed
    config yields empties (resolution still works, just without aliases/modifiers)."""
    try:
        cfg = load_config("food_aliases", config_dir)
    except FileNotFoundError:
        return {}, frozenset()
    raw_aliases = cfg.get("aliases", {})
    aliases: dict[str, str] = {}
    if isinstance(raw_aliases, dict):
        for key, value in raw_aliases.items():
            k = " ".join(str(key).lower().split())
            v = " ".join(str(value).lower().split())
            if k and v:
                aliases[k] = v
    raw_modifiers = cfg.get("modifiers", []) or []
    modifiers = frozenset(
        str(m).lower().strip() for m in raw_modifiers if str(m).strip()
    ) if isinstance(raw_modifiers, list) else frozenset()
    return aliases, modifiers


# Sentinel so a cached None (a real "no confident match") is distinguished from an absent key.
_MISS: object = object()
