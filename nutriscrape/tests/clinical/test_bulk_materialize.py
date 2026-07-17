"""End-to-end clinical golden: the bulk-materialize path generates alternative-preparation variants
offline, matching the transactional materialize. [INVARIANT] Must pass in CI.

Drives `export_alt_variants` (the compute half of bulk-materialize) over an in-memory FDC index for
a boiled-and-drained potato recipe and reads the alt-variant CSVs. It asserts the alternative-method
variants carry `<recipe>:variant:<method>` ids (never the as-authored one), and that a non-draining
method (bake) RETAINS the potassium that boiling-and-draining leaches away, exactly as
tests/clinical/test_materialize_slice.py asserts for the transactional path. Same variant_id and same
`nutrition.variants.alternative_methods` selection, so the two paths are interchangeable/mergeable.
See bulk/materialize.py, PDD Section 6, DATA_CONTRACT Section 3.1.
"""
import csv

from nutriscrape.acquisition.adapters.base import RawRecipe
from nutriscrape.bulk.export import ExportStats, _Writers
from nutriscrape.bulk.food_index import FoodIndex
from nutriscrape.bulk.materialize import _ALT_FILES, _load_method_coverage, export_alt_variants
from nutriscrape.common.config import default_config_dir
from nutriscrape.knowledge.loaders import load_transforms

_UNITS = {"potassium": "mg", "sodium": "mg"}


def _index() -> FoodIndex:
    idx = FoodIndex()
    idx._add("170026", "Potatoes, flesh and skin, raw", "sr_legacy_food",
             {"potassium": 425.0, "sodium": 6.0})
    idx._add("173468", "Salt, table", "sr_legacy_food", {"sodium": 38758.0})
    return idx


def _raw() -> RawRecipe:
    return RawRecipe(
        recipe_id="pot", title="Boiled Potatoes", source_id="recipenlg", license="x", servings=4.0,
        ingredient_lines=("2 pounds potatoes, cubed", "1 teaspoon salt"),
        preparation_steps=("Boil the potatoes.", "Drain the potatoes."),
    )


def _export(tmp_path) -> dict[str, list[dict[str, str]]]:
    transforms = load_transforms(default_config_dir())
    coverage = _load_method_coverage()
    stats = ExportStats()
    with _Writers(tmp_path, _ALT_FILES) as writers:
        export_alt_variants(_raw(), _index(), transforms, _UNITS, coverage, writers.writers, stats)
    out: dict[str, list[dict[str, str]]] = {}
    for name in _ALT_FILES:
        with (tmp_path / f"{name}.csv").open(encoding="utf-8") as handle:
            out[name] = list(csv.DictReader(handle))
    return out


def test_bulk_materialize_writes_alternative_variants(tmp_path):
    rows = _export(tmp_path)
    variant_ids = {r["variant_id"] for r in rows["alt_variants"]}
    assert variant_ids                                             # at least one alt variant
    # the bounded alternative set (config/method_coverage.yaml), minus the as-authored boil
    assert "pot:variant:bake" in variant_ids
    assert "pot:variant:boil" not in variant_ids                  # as-authored method excluded
    assert "pot:variant:0:as_authored" not in variant_ids         # that is the ingest/bulk-load path


def test_bulk_materialize_bake_retains_potassium_that_draining_leaches(tmp_path):
    rows = _export(tmp_path)
    baked_k = [
        float(r["amount_per_serving"]) for r in rows["alt_has_nutrient"]
        if r["variant_id"] == "pot:variant:bake" and r["nutrient_id"] == "potassium"
    ]
    assert baked_k, "no potassium row for the baked variant"
    # bake has no leaching coefficient, so potassium passes through: 425 mg/100g * 900 g / 4 servings
    assert baked_k[0] > 900.0                                      # retained, unlike boil-and-drain
