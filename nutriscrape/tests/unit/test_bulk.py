"""Unit tests for the bulk-load path: in-memory resolution and CSV export.

These exercise the compute half offline (no Neo4j): the `FoodIndex` resolver and `export_recipe`'s
parse -> resolve -> cook -> CSV-row path, plus shard concatenation.
"""
from nutriscrape.acquisition.adapters.base import RawRecipe
from nutriscrape.bulk.export import (
    ExportStats,
    _concatenate_shards,
    _Writers,
    export_recipe,
)
from nutriscrape.bulk.food_index import FoodIndex
from nutriscrape.common.config import default_config_dir
from nutriscrape.knowledge.loaders import load_transforms


def _index() -> FoodIndex:
    idx = FoodIndex()
    idx._add("170026", "Potatoes, flesh and skin, raw", "sr_legacy_food",
             {"potassium": 425.0, "sodium": 6.0})
    idx._add("173468", "Salt, table", "sr_legacy_food", {"sodium": 38758.0})
    return idx


def test_food_index_resolves_noisy_string_and_serves_vector():
    # the parser splits qualifiers on the comma first, so the food it hands resolution is "potatoes"
    idx = _index()
    resolved = idx.resolve("2 pounds potatoes")
    assert resolved is not None and resolved.fdc_id == "170026"
    assert idx.raw_vector("170026") == {"potassium": 425.0, "sodium": 6.0}


def test_food_index_normalizes_packaging_noise():
    # "(16 oz.) can potatoes" normalizes to "potatoes" and still resolves
    assert idx_resolve(_index(), "(16 oz.) can potatoes") == "170026"


def test_food_index_returns_none_below_threshold():
    assert _index().resolve("xyzzy nonexistent") is None


def idx_resolve(idx: FoodIndex, s: str) -> str | None:
    r = idx.resolve(s)
    return None if r is None else r.fdc_id


def test_export_recipe_writes_cooked_nutrient_rows(tmp_path):
    transforms = load_transforms(default_config_dir())
    units = {"potassium": "mg", "sodium": "mg"}
    raw = RawRecipe(
        recipe_id="r:0", title="Boiled Potatoes", source_id="recipenlg", license="x",
        servings=4.0,
        ingredient_lines=("2 pounds potatoes, cubed", "1 teaspoon salt"),
        preparation_steps=("Boil the potatoes.", "Drain the potatoes."),
    )
    stats = ExportStats()
    with _Writers(tmp_path) as writers:
        export_recipe(raw, _index(), transforms, units, writers.writers, stats)

    assert stats.recipes_written == 1
    has_nutrient = (tmp_path / "has_nutrient.csv").read_text(encoding="utf-8")
    assert "r:0:variant:0:as_authored" in has_nutrient
    assert "potassium" in has_nutrient           # a cooked nutrient row was written
    assert "Boiled Potatoes" in (tmp_path / "recipes.csv").read_text(encoding="utf-8")


def test_export_recipe_skips_when_no_ingredient_resolves(tmp_path):
    stats = ExportStats()
    raw = RawRecipe(recipe_id="r:1", title="Mystery", source_id="s", license="x", servings=2.0,
                    ingredient_lines=("qwerty widgets",), preparation_steps=())
    with _Writers(tmp_path) as writers:
        export_recipe(raw, _index(), [], {}, writers.writers, stats)
    assert stats.recipes_written == 0 and stats.recipes_skipped == 1


def test_concatenate_shards_merges_with_one_header(tmp_path):
    header = "recipe_id,title,source_id,license,servings,confidence"
    for i, rid in enumerate(("a", "b")):
        shard = tmp_path / f"shard_{i}"
        shard.mkdir()
        (shard / "recipes.csv").write_text(f"{header}\n{rid},T,s,l,4,0.6\n", encoding="utf-8")

    _concatenate_shards(tmp_path, [tmp_path / "shard_0", tmp_path / "shard_1"])

    lines = (tmp_path / "recipes.csv").read_text(encoding="utf-8").splitlines()
    assert sum(1 for line in lines if line.startswith("recipe_id")) == 1   # header once
    assert any(line.startswith("a,") for line in lines)
    assert any(line.startswith("b,") for line in lines)


def test_alias_maps_ambiguous_staple_to_base_food():
    """A bare "sugar" must resolve to granulated sugar, not a specialty that shares the word
    ("Sugar-apples"). The config alias expands it to a fuller query that is still validated against
    the food set (normalize-then-validate). Without the alias the specialty can win on the raw
    preference; with it, scoring against "granulated sugar" picks the base food."""
    idx = FoodIndex()
    idx._add("1", "Sugars, granulated", "sr_legacy_food", {"potassium": 2.0, "energy": 387.0})
    idx._add("2", "Sugar-apples, (sweetsop), raw", "sr_legacy_food", {"potassium": 247.0})
    # no alias: the specialty (raw, shares the exact token) is picked
    assert idx.resolve("sugar").fdc_id == "2"
    # with the alias, the base food wins
    idx._aliases = {"sugar": "granulated sugar"}
    idx._cache.clear()
    assert idx.resolve("sugar").fdc_id == "1"


def test_alias_only_fires_on_exact_normalized_string():
    idx = FoodIndex()
    idx._add("1", "Sugars, granulated", "sr_legacy_food", {"potassium": 2.0})
    idx._add("2", "Cookies, sugar, commercially prepared", "sr_legacy_food", {"potassium": 60.0})
    idx._aliases = {"sugar": "granulated sugar"}
    # "sugar cookies" is not the bare staple, so the alias must not fire (stays a cookie)
    assert idx.resolve("sugar cookies").fdc_id == "2"


def test_prep_modifiers_stripped_but_identity_words_kept():
    """A preparation-state word ("melted", "chopped") is stripped so a modified staple reaches the
    base food, but an identity word ("brown") is not, so "brown sugar" stays brown sugar."""
    idx = FoodIndex()
    idx._add("1", "Butter, salted", "sr_legacy_food", {"energy": 717.0})
    idx._add("2", "Sugars, granulated", "sr_legacy_food", {"potassium": 2.0})
    idx._add("3", "Sugars, brown", "sr_legacy_food", {"potassium": 133.0})
    idx._aliases = {"butter": "butter salted", "sugar": "granulated sugar",
                    "brown sugar": "sugars brown"}
    idx._modifiers = frozenset({"melted", "chopped", "sifted"})
    # "melted butter" -> strip "melted" -> "butter" -> base butter
    assert idx.resolve("melted butter").fdc_id == "1"
    # "sifted brown sugar" -> strip "sifted", keep "brown" -> brown sugar (not granulated)
    assert idx.resolve("sifted brown sugar").fdc_id == "3"


def test_load_alias_config_reads_aliases_and_modifiers():
    from nutriscrape.bulk.food_index import _load_alias_config

    aliases, modifiers = _load_alias_config(None)   # real config/food_aliases.yaml
    assert aliases.get("sugar") == "granulated sugar"
    assert aliases.get("ketchup") == "catsup"
    assert "melted" in modifiers and "chopped" in modifiers
    assert "brown" not in modifiers and "sour" not in modifiers   # identity words never stripped
