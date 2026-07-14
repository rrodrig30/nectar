"""Unit tests for per-dish nutrient distribution statistics."""
import pytest

from nutriscrape.nutrition.distribution import distribution


def test_distribution_summary():
    d = distribution([300.0, 600.0, 900.0])
    assert d.count == 3 and d.minimum == 300.0 and d.maximum == 900.0
    assert d.mean == 600.0 and d.median == 600.0
    assert d.stdev == pytest.approx(244.949, abs=0.01)


def test_single_version_has_zero_spread():
    d = distribution([500.0])
    assert d.count == 1 and d.minimum == d.maximum == 500.0 and d.stdev == 0.0


def test_empty_distribution_raises():
    with pytest.raises(ValueError):
        distribution([])
