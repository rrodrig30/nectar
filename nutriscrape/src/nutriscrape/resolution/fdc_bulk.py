"""Bulk USDA FoodData Central importer: stream the FDC CSV bulk export into per-food raw nutrient
vectors, so food composition lives in the local graph and resolution needs no per-food API call.

The FDC "Full Download" CSV export (https://fdc.nal.usda.gov/download-datasets) ships normalized
files: `food.csv` (fdc_id, description, data_type), `nutrient.csv` (the nutrient dictionary), and
`food_nutrient.csv` (per-food amounts). This module joins them and reuses `nutrient_map` for the
FDC-number -> contract nutrient_id mapping and unit conversion, so there is one mapping code path.
File I/O only; writing to the graph is the caller's concern (pipeline.run_fdc_import).

`food_nutrient.csv` is streamed grouped by fdc_id (the export is sorted by fdc_id), so memory stays
O(one food's nutrients); `nutrient.csv` (~500 rows) and `food.csv` are held in memory. food.csv is
small for the Foundation / SR Legacy / FNDDS data types recipe ingredients resolve to; the
multi-million-row Branded export is heavier and usually unnecessary for recipe resolution.
"""
from __future__ import annotations

import csv
from collections.abc import Iterator
from dataclasses import dataclass
from itertools import groupby
from pathlib import Path
from typing import Any

from nutriscrape.resolution.nutrient_map import (
    load_contract_units,
    load_fdc_nutrient_map,
    raw_vector_from_fdc,
)


@dataclass(frozen=True)
class BulkFood:
    fdc_id: str
    description: str
    data_type: str
    raw_per_100g: dict[str, float]


def _fdc_id_of(row: dict[str, str]) -> str:
    return (row.get("fdc_id") or "").strip()


def _load_nutrient_dictionary(path: Path) -> dict[str, tuple[str, str]]:
    """FDC nutrient PK -> (nutrient_nbr, unit_name), from nutrient.csv."""
    out: dict[str, tuple[str, str]] = {}
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            pk = (row.get("id") or "").strip()
            number = (row.get("nutrient_nbr") or "").strip()
            unit = (row.get("unit_name") or "").strip()
            if pk and number:
                out[pk] = (number, unit)
    return out


def _load_foods(path: Path) -> dict[str, tuple[str, str]]:
    """fdc_id -> (description, data_type), from food.csv."""
    out: dict[str, tuple[str, str]] = {}
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            fdc_id = _fdc_id_of(row)
            if fdc_id:
                out[fdc_id] = ((row.get("description") or "").strip(),
                               (row.get("data_type") or "").strip())
    return out


def _food_nutrient_entries(
    path: Path, nutrient_dict: dict[str, tuple[str, str]]
) -> Iterator[tuple[str, list[dict[str, Any]]]]:
    """Stream food_nutrient.csv grouped by fdc_id, yielding (fdc_id, entries) where each entry is
    shaped like an FDC API foodNutrient ({"nutrient": {"number", "unitName"}, "amount"}) so
    `raw_vector_from_fdc` can consume it. Assumes the file is sorted by fdc_id (the FDC export is)."""
    with path.open(encoding="utf-8", newline="") as handle:
        for fdc_id, rows in groupby(csv.DictReader(handle), key=_fdc_id_of):
            if not fdc_id:
                continue
            entries: list[dict[str, Any]] = []
            for row in rows:
                mapping = nutrient_dict.get((row.get("nutrient_id") or "").strip())
                amount = (row.get("amount") or "").strip()
                if mapping is None or not amount:
                    continue
                number, unit = mapping
                entries.append({"nutrient": {"number": number, "unitName": unit}, "amount": amount})
            yield fdc_id, entries


def iter_bulk_foods(csv_dir: str | Path, config_dir: str | Path | None = None) -> Iterator[BulkFood]:
    """Stream the FDC CSV bulk export at `csv_dir` into `BulkFood` records, each with a raw per-100g
    contract-nutrient vector. Foods whose vector is empty after mapping are skipped."""
    directory = Path(csv_dir)
    nutrient_dict = _load_nutrient_dictionary(directory / "nutrient.csv")
    foods = _load_foods(directory / "food.csv")
    nutrient_map = load_fdc_nutrient_map(config_dir)
    contract_units = load_contract_units(config_dir)

    for fdc_id, entries in _food_nutrient_entries(directory / "food_nutrient.csv", nutrient_dict):
        food = foods.get(fdc_id)
        if food is None:
            continue
        vector = raw_vector_from_fdc({"foodNutrients": entries}, nutrient_map=nutrient_map,
                                     contract_units=contract_units)
        if not vector:
            continue
        description, data_type = food
        yield BulkFood(fdc_id=fdc_id, description=description, data_type=data_type,
                       raw_per_100g=vector)


__all__ = ["BulkFood", "iter_bulk_foods"]
