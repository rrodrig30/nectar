"""End-to-end clinical golden for the ingest slice. [INVARIANT] Must pass in CI.

Drives the whole ingest path offline (fake FDC resolve/fetch, but the REAL deterministic parsers,
the real FDC->contract nutrient mapping, the real four-channel transform, and the real graph
writers) and proves a genuine cooked per-serving potassium value is written to HAS_NUTRIENT, and
that boiling-and-draining leaches it below the soup version that keeps the liquid. This is the
recipe-corpus analogue of the transform golden (tests/clinical/test_transform.py).
"""
from typing import Any

from nutriscrape.acquisition.adapters.base import RawRecipe
from nutriscrape.common.config import default_config_dir
from nutriscrape.knowledge.loaders import load_transforms
from nutriscrape.pipeline import IngestDeps, ResolvedFood, _ingest_recipe, _load_nutrient_vocab

# Illustrative FDC records (per 100 g), shaped like a real /food/{id} response.
_POTATO_FDC: dict[str, Any] = {
    "foodNutrients": [
        {"nutrient": {"number": "306", "name": "Potassium, K", "unitName": "MG"}, "amount": 425.0},
        {"nutrient": {"number": "307", "name": "Sodium, Na", "unitName": "MG"}, "amount": 6.0},
        {"nutrient": {"number": "208", "name": "Energy", "unitName": "KCAL"}, "amount": 77.0},
    ]
}
_SALT_FDC: dict[str, Any] = {
    "foodNutrients": [
        {"nutrient": {"number": "307", "name": "Sodium, Na", "unitName": "MG"}, "amount": 38758.0},
    ]
}


def _fake_resolve(food_str: str) -> ResolvedFood | None:
    text = food_str.lower()
    if "potato" in text:
        return ResolvedFood("170026", "Potatoes, flesh and skin, raw", "sr_legacy_food")
    if "salt" in text:
        return ResolvedFood("173468", "Salt, table", "sr_legacy_food")
    return None


def _fake_fetch(fdc_id: str) -> dict[str, Any]:
    return _POTATO_FDC if fdc_id == "170026" else _SALT_FDC


class _CaptureClient:
    """A fake GraphClient that records every parameterized write instead of hitting Neo4j."""

    def __init__(self) -> None:
        self.writes: list[tuple[str, dict[str, Any]]] = []

    def run_write(self, cypher: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        self.writes.append((cypher, params))
        return []


def _deps() -> IngestDeps:
    return IngestDeps(resolve=_fake_resolve, fetch_food=_fake_fetch,
                      transforms=load_transforms(default_config_dir()),
                      nutrient_vocab=_load_nutrient_vocab())


def _potassium_per_serving(client: _CaptureClient) -> float:
    # a cooked HAS_NUTRIENT edge carries amount_per_serving; HAS_NUTRIENT_RAW carries amount_per_100g
    for _cypher, params in client.writes:
        if params.get("nutrient_id") == "potassium" and "amount_per_serving" in params:
            return float(params["amount_per_serving"])
    raise AssertionError("no cooked potassium HAS_NUTRIENT was written")


_INGREDIENTS = ("2 pounds potatoes, peeled and cubed", "1 teaspoon salt")


def _drained_recipe() -> RawRecipe:
    return RawRecipe(
        recipe_id="r_drained", title="Boiled and Drained Potatoes", source_id="test",
        license="test", servings=4.0, ingredient_lines=_INGREDIENTS,
        preparation_steps=("Boil the cubed potatoes in salted water for 15 minutes.",
                           "Drain the potatoes well.", "Serve."))


def _soup_recipe() -> RawRecipe:
    return RawRecipe(
        recipe_id="r_soup", title="Potato Soup", source_id="test", license="test", servings=4.0,
        ingredient_lines=_INGREDIENTS,
        preparation_steps=("Boil the cubed potatoes in broth for 15 minutes.",
                           "Serve as a potato soup."))


def test_ingest_writes_a_real_cooked_potassium_value():
    client = _CaptureClient()
    _ingest_recipe(_drained_recipe(), _deps(), client)
    k = _potassium_per_serving(client)
    assert k > 0.0                                   # a real number, from FDC through the transform
    # the as-authored variant and its cooked HAS_NUTRIENT edge were both written
    assert any("RecipeVariant" in c and "is_as_authored" in c for c, _ in client.writes)
    cooked = [(c, p) for c, p in client.writes if "amount_per_serving" in p]
    assert cooked and cooked[0][1]["source"].startswith("transform")
    # and the intrinsic raw vector was persisted on the Food for later re-cooking
    assert any("HAS_NUTRIENT_RAW" in c and "amount_per_100g" in p for c, p in client.writes)


def test_boiling_and_draining_leaches_potassium_below_soup():
    drained_client, soup_client = _CaptureClient(), _CaptureClient()
    _ingest_recipe(_drained_recipe(), _deps(), drained_client)
    _ingest_recipe(_soup_recipe(), _deps(), soup_client)
    drained_k = _potassium_per_serving(drained_client)
    soup_k = _potassium_per_serving(soup_client)
    assert drained_k < soup_k                        # draining discards the leached potassium
    # the soup keeps essentially all the raw potassium: 425 mg/100g * 907 g / 4 servings
    assert soup_k > 900.0
