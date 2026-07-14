"""Unit tests for the FDC nutrient-number -> contract nutrient_id mapping.

In-memory FDC food JSON only; no network call. Proves the g -> mg conversion (EPA/DHA reported
in grams), the mg pass-through (sodium, potassium), the kcal pass-through (energy), the EPA+DHA
sum into omega3_epa_dha, and the food_class keyword match.
"""
from __future__ import annotations

from typing import Any

from nutriscrape.resolution.nutrient_map import classify_food, raw_vector_from_fdc

_POTATO_FOOD_JSON: dict[str, Any] = {
    "fdcId": 170026,
    "description": "Potatoes, raw, skin",
    "foodNutrients": [
        {"nutrient": {"number": "306", "name": "Potassium, K", "unitName": "MG"}, "amount": 425.0},
        {"nutrient": {"number": "307", "name": "Sodium, Na", "unitName": "MG"}, "amount": 6.0},
        {"nutrient": {"number": "208", "name": "Energy", "unitName": "KCAL"}, "amount": 77.0},
        # Reported in grams to prove the g -> mg conversion into the canonical omega3 unit.
        {"nutrient": {"number": "629", "name": "EPA", "unitName": "G"}, "amount": 0.001},
        {"nutrient": {"number": "621", "name": "DHA", "unitName": "G"}, "amount": 0.002},
        # A number with no entry in fdc_nutrient_map.yaml: must be skipped, not fabricated.
        {"nutrient": {"number": "999999", "name": "Unmapped", "unitName": "MG"}, "amount": 42.0},
    ],
}


def test_raw_vector_converts_units_and_passes_through_matching_units() -> None:
    vector = raw_vector_from_fdc(_POTATO_FOOD_JSON)

    assert vector["potassium"] == 425.0
    assert vector["sodium"] == 6.0
    assert vector["energy"] == 77.0


def test_raw_vector_sums_epa_and_dha_into_omega3_epa_dha_in_mg() -> None:
    vector = raw_vector_from_fdc(_POTATO_FOOD_JSON)

    # 0.001 g EPA + 0.002 g DHA = 3.0 mg, canonical unit for omega3_epa_dha per nutrients.yaml.
    assert vector["omega3_epa_dha"] == 3.0


def test_raw_vector_skips_unmapped_fdc_numbers() -> None:
    vector = raw_vector_from_fdc(_POTATO_FOOD_JSON)

    assert all(key != "999999" for key in vector)
    assert len(vector) == 4  # potassium, sodium, energy, omega3_epa_dha only


def test_raw_vector_tolerates_alternate_fdc_shape() -> None:
    alt_food_json: dict[str, Any] = {
        "fdcId": 170027,
        "description": "Potatoes, alternate shape",
        "foodNutrients": [
            {"nutrientNumber": "306", "value": 300.0, "unitName": "MG"},
        ],
    }

    vector = raw_vector_from_fdc(alt_food_json)

    assert vector["potassium"] == 300.0


def test_classify_food_matches_root_vegetable_for_potato() -> None:
    tags = classify_food("Potatoes, raw")

    assert "root_vegetable" in tags
    assert "starch" in tags


def test_classify_food_returns_empty_list_for_no_match() -> None:
    tags = classify_food("Grilled chicken breast")

    assert tags == []
