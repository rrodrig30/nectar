"""Unit tests for the bulk FDC CSV parser and importer (a tiny FDC-format fixture, no network/DB)."""
from pathlib import Path
from typing import Any

from nutriscrape.pipeline import _import_fdc_bulk
from nutriscrape.resolution.fdc_bulk import iter_bulk_foods

_FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "fdc"


class _CaptureClient:
    def __init__(self) -> None:
        self.writes: list[tuple[str, dict[str, Any]]] = []

    def run_write(self, cypher: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        self.writes.append((cypher, params))
        return []


def test_iter_bulk_foods_builds_raw_vectors():
    foods = {food.fdc_id: food for food in iter_bulk_foods(_FIXTURE)}
    # the unmappable food (only an FDC number absent from fdc_nutrient_map.yaml) is skipped
    assert set(foods) == {"170026", "173468"}

    potato = foods["170026"]
    assert potato.description == "Potatoes, flesh and skin, raw"
    assert potato.data_type == "sr_legacy_food"
    assert potato.raw_per_100g == {"potassium": 425.0, "sodium": 6.0, "energy": 77.0}

    assert foods["173468"].raw_per_100g == {"sodium": 38758.0}


def test_import_fdc_bulk_writes_food_and_raw_vectors():
    client = _CaptureClient()
    written = _import_fdc_bulk(str(_FIXTURE), client)
    assert written == 2

    merged_foods = {p["fdc_id"] for c, p in client.writes if "MERGE (f:Food" in c}
    assert merged_foods == {"170026", "173468"}

    raw = {(p["fdc_id"], p["nutrient_id"]): p["amount_per_100g"]
           for c, p in client.writes if "HAS_NUTRIENT_RAW" in c}
    assert raw[("170026", "potassium")] == 425.0
    assert raw[("173468", "sodium")] == 38758.0
    # the contract :Nutrient vocabulary is merged up front so HAS_NUTRIENT_RAW can match it
    assert any("MERGE (n:Nutrient" in c for c, _ in client.writes)
