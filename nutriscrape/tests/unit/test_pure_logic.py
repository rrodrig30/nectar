"""Unit tests for the NutriScrape pure logic: units, confidence, normalize, variants, clustering."""
import pytest

from nutriscrape.common import units
from nutriscrape.common.confidence import propagate, penalize
from nutriscrape.nutrition.normalize import to_canonical
from nutriscrape.nutrition.variants import select_variants
from nutriscrape.nutrition.transform import Preparation
from nutriscrape.clustering.fingerprint import RecipeInput, fingerprint
from nutriscrape.clustering.blocking import block_by_core_signature, signature
from nutriscrape.clustering.score import jaccard, score
from nutriscrape.clustering.resolve import cluster


def test_unit_conversions():
    assert units.to_grams(1.0, "kg") == 1000.0
    assert round(units.to_grams(1.0, "oz"), 3) == 28.350
    assert units.to_milliliters(1.0, "cup") == pytest.approx(236.588, abs=0.01)
    assert units.to_celsius(212.0, "F") == pytest.approx(100.0)
    with pytest.raises(units.UnitError):
        units.to_grams(1.0, "furlong")


def test_confidence_never_increases_downstream():
    assert propagate([0.9, 0.4, 0.7]) == 0.4          # min wins
    assert penalize(0.8, 0.5) == pytest.approx(0.4)   # penalty only lowers
    assert propagate([]) == 0.5                        # neutral floor, not higher


def test_to_canonical_mass_and_volume():
    m = to_canonical(2.0, "kg")
    assert m.value == 2000.0 and m.unit == "g"
    v = to_canonical(1.0, "cup")
    assert v.unit == "ml"
    vg = to_canonical(1.0, "cup", density_g_per_ml=1.03)
    assert vg.unit == "g" and vg.value == pytest.approx(243.7, abs=0.5)


def test_select_variants_bounded_and_authored_first():
    authored = Preparation(method="boil", cut_class="cubed", liquid_retained_frac=0.0)
    got = select_variants(authored, ["bake", "boil", "fry", "steam", "roast"], max_variants=3)
    assert got[0] is authored                          # as-authored always first
    assert len(got) == 3                               # bounded, not a full cross-product
    assert "boil" not in [p.method for p in got[1:]]   # authored method not repeated


def test_fingerprint_and_blocking():
    r1 = RecipeInput("r1", {"potato": 300.0, "butter": 20.0, "salt": 2.0}, "boil", "mashed potato")
    r2 = RecipeInput("r2", {"potato": 280.0, "milk": 40.0, "salt": 3.0}, "boil", "potato mash")
    f1, f2 = fingerprint(r1), fingerprint(r2)
    assert "potato" in f1.core_foods
    blocks = block_by_core_signature([f1, f2], top_n=1)
    # both are potato-dominant, so they share a block
    assert len(blocks) == 1 and signature(f1, 1) == signature(f2, 1)


def test_jaccard_and_score_bounds():
    assert jaccard(frozenset("ab"), frozenset("ab")) == 1.0
    assert jaccard(frozenset("a"), frozenset("b")) == 0.0
    f1 = fingerprint(RecipeInput("r1", {"potato": 300.0}, "boil"))
    f2 = fingerprint(RecipeInput("r2", {"potato": 300.0}, "boil"))
    assert 0.0 <= score(f1, f2) <= 1.0


def test_clustering_favors_finer_split_without_judge():
    # two clearly-same potato mashes cluster; a clinically distinct dairy-free version stays separate
    # when no LLM judge is provided for the near-threshold call.
    same_a = RecipeInput("a", {"potato": 300.0, "butter": 20.0}, "boil")
    same_b = RecipeInput("b", {"potato": 300.0, "butter": 22.0}, "boil")
    distinct = RecipeInput("c", {"potato": 300.0, "olive_oil": 20.0}, "roast")
    fps = [fingerprint(r) for r in (same_a, same_b, distinct)]
    clusters = cluster(fps, judge=None)
    members = sorted(sorted(c.members) for c in clusters)
    assert ["a", "b"] in members                       # the two same versions merged
    assert ["c"] in members                            # the distinct version stayed its own dish
    # membership confidence recorded for every member
    assert all(0.0 <= v <= 1.0 for c in clusters for v in c.membership_confidence.values())
