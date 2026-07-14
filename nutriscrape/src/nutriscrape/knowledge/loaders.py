"""Load rules / interactions / transforms / guidelines from ``config/`` into typed structures
that mirror the contract knowledge base (DATA_CONTRACT.md Sections 2.2, 3.2, 3.3, 3.4).

These loaders are pure: YAML in, typed pydantic models out. They do NOT write to Neo4j; a graph
writer is a separate concern (``graph/writers.py``). Every produced record carries the contract
Section 1.1 provenance block (source, confidence, evidence_tier where applicable) so a downstream
writer never has to synthesize it.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel

from nectar_contract.types import EvidenceTier, Provenance

# Contract version every produced record is stamped with. Overridable via the environment so a
# batch run pins the same version it writes under.
CONTRACT_VERSION = os.environ.get("CONTRACT_VERSION", "1.0")
_COMPUTED_BY = "knowledge.loaders"
# Curated illustrative rules do not ship a per-entry confidence; use a calibrated placeholder.
_DEFAULT_RULE_CONFIDENCE = 0.7

Direction = Literal["avoid", "limit", "target", "maintain", "prefer"]
Severity = Literal["absolute", "strong", "moderate", "soft"]
Channel = Literal["concentration", "leaching", "degradation", "formation"]


# ----------------------------------------------------------------------------- models


class DietaryRule(BaseModel):
    """A reified constraint (contract :DietaryRule). ``acts_on`` names the nutrient / food /
    attribute / compound the rule constrains (contract ACTS_ON)."""

    rule_id: str
    direction: Direction
    severity: Severity
    threshold: float | None
    unit: str | None
    safety_critical: bool
    basis: str | None
    acts_on: str
    guideline_id: str | None
    provenance: Provenance


class Interaction(BaseModel):
    """A food-drug interaction (contract :Medication-[:INTERACTS_WITH]->target)."""

    medication: str
    target: str
    mechanism: str
    effect: str | None
    severity: Severity
    direction: Direction
    threshold: float | None
    provenance: Provenance


class TransformCoeff(BaseModel):
    """One four-channel transform coefficient (contract :Food|:FoodClass-[:TRANSFORM]->:Method).

    ``food_class`` / ``food_id`` name the left side of the TRANSFORM edge; ``method`` names the
    right side. source / confidence / evidence_tier live in ``provenance``.
    """

    food_class: str | None
    food_id: str | None
    method: str
    target: str
    channel: Channel
    D: float | None
    L_base: float | None
    formation_rate: float | None
    mechanism: str
    provenance: Provenance


class Guideline(BaseModel):
    """A guideline passage (contract :Guideline). Loaded here from the source manifest as a stub;
    ``chunk`` and embeddings are populated later by the guideline ingest, not by config."""

    guideline_id: str
    org: str | None
    title: str | None
    year: int | None
    url: str | None
    chunk: str | None
    provenance: Provenance


# ----------------------------------------------------------------------------- public loaders


def load_rules(config_dir: Path) -> list[DietaryRule]:
    """Parse disease-rule YAML (``<config_dir>/conditions/*.yaml``) into :class:`DietaryRule`.

    If no ``conditions/`` subdirectory exists, top-level ``*.yaml`` files are scanned and any file
    without a ``constraints`` key is skipped, so passing a mixed config directory is safe.
    """
    root = Path(config_dir)
    condition_dir = root / "conditions"
    if condition_dir.is_dir():
        files = sorted(condition_dir.glob("*.yaml"))
    else:
        files = sorted(root.glob("*.yaml"))
    rules: list[DietaryRule] = []
    for path in files:
        data = _read_yaml(path)
        if not isinstance(data, dict) or "constraints" not in data:
            continue
        disease_id = str(data.get("disease_id") or path.stem)
        guideline_org = _opt_str(data.get("guideline_org"))
        for constraint in data["constraints"] or []:
            rules.append(_rule_from_constraint(disease_id, guideline_org, constraint))
    return rules


def load_interactions(config_dir: Path) -> list[Interaction]:
    """Parse curated food-drug interactions (``<config_dir>/interactions/*.yaml``).

    Each file is expected to carry a top-level ``interactions`` list. The directory is currently
    unpopulated, so this returns ``[]`` until entries are curated.
    """
    root = Path(config_dir) / "interactions"
    if not root.is_dir():
        return []
    out: list[Interaction] = []
    for path in sorted(root.glob("*.yaml")):
        data = _read_yaml(path)
        if not isinstance(data, dict):
            continue
        for entry in data.get("interactions", []) or []:
            out.append(_interaction_from_entry(entry))
    return out


def load_transforms(config_dir: Path) -> list[TransformCoeff]:
    """Parse four-channel transform coefficients from ``<config_dir>/retention.yaml`` and any
    ``<config_dir>/transforms/*.yaml`` shards. Each entry carries source, confidence, evidence_tier.
    """
    root = Path(config_dir)
    files = [root / "retention.yaml"]
    transforms_dir = root / "transforms"
    if transforms_dir.is_dir():
        files.extend(sorted(transforms_dir.glob("*.yaml")))
    out: list[TransformCoeff] = []
    for path in files:
        if not path.is_file():
            continue
        data = _read_yaml(path)
        if not isinstance(data, dict):
            continue
        for entry in data.get("transforms", []) or []:
            out.append(_transform_from_entry(entry))
    return out


def load_guidelines(config_dir: Path) -> list[Guideline]:
    """Parse the guideline manifest from ``<config_dir>/sources.yaml`` (``guidelines`` section)."""
    path = Path(config_dir) / "sources.yaml"
    if not path.is_file():
        return []
    data = _read_yaml(path)
    if not isinstance(data, dict):
        return []
    guidelines = data.get("guidelines", {}) or {}
    if not isinstance(guidelines, dict):
        return []
    out: list[Guideline] = []
    for guideline_id, meta in guidelines.items():
        out.append(_guideline_from_entry(str(guideline_id), meta))
    return out


# ----------------------------------------------------------------------------- builders


def _rule_from_constraint(
    disease_id: str, guideline_org: str | None, constraint: Any
) -> DietaryRule:
    ctype = str(constraint.get("type", "limit"))
    direction = _DIRECTION_FROM_TYPE.get(ctype, "limit")
    nutrient = str(constraint.get("nutrient", "unknown"))
    hard_limit = constraint.get("hard_limit")
    safety_critical = bool(constraint.get("safety_critical", False))
    if direction == "target":
        threshold = constraint.get("goal")
    else:
        threshold = constraint.get("max_per_serving", hard_limit)
    # A configured hard limit is a firm ceiling; otherwise treat curated placeholders as moderate.
    severity: Severity = "strong" if hard_limit is not None else "moderate"
    guideline_id = constraint.get("guideline_id")
    provenance = Provenance(
        source=str(guideline_id or guideline_org or disease_id),
        confidence=_coerce_float(constraint.get("confidence"), _DEFAULT_RULE_CONFIDENCE),
        evidence_tier=None,
        computed_by=_COMPUTED_BY,
        contract_version=CONTRACT_VERSION,
    )
    return DietaryRule(
        rule_id=f"{disease_id}:{nutrient}:{direction}",
        direction=direction,
        severity=severity,
        threshold=_opt_float(threshold),
        unit=_opt_str(constraint.get("unit")),
        safety_critical=safety_critical,
        basis=_opt_str(constraint.get("basis")),
        acts_on=nutrient,
        guideline_id=_opt_str(guideline_id),
        provenance=provenance,
    )


def _interaction_from_entry(entry: Any) -> Interaction:
    provenance = Provenance(
        source=str(entry.get("source") or entry.get("medication") or "curated"),
        confidence=_coerce_float(entry.get("confidence"), _DEFAULT_RULE_CONFIDENCE),
        evidence_tier=_as_tier(entry.get("evidence_tier")),
        computed_by=_COMPUTED_BY,
        contract_version=CONTRACT_VERSION,
    )
    return Interaction(
        medication=str(entry.get("medication", "unknown")),
        target=str(entry.get("target", "unknown")),
        mechanism=str(entry.get("mechanism", "")),
        effect=_opt_str(entry.get("effect")),
        severity=_as_severity(entry.get("severity")),
        direction=_as_direction(entry.get("direction")),
        threshold=_opt_float(entry.get("threshold")),
        provenance=provenance,
    )


def _transform_from_entry(entry: Any) -> TransformCoeff:
    provenance = Provenance(
        source=str(entry.get("source", "estimated")),
        confidence=_coerce_float(entry.get("confidence"), 0.5),
        evidence_tier=_as_tier(entry.get("evidence_tier")),
        computed_by=_COMPUTED_BY,
        contract_version=CONTRACT_VERSION,
    )
    return TransformCoeff(
        food_class=_opt_str(entry.get("food_class")),
        food_id=_opt_str(entry.get("food") or entry.get("food_id")),
        method=str(entry.get("method", "unknown")),
        target=str(entry.get("target", "unknown")),
        channel=_as_channel(entry.get("channel")),
        D=_opt_float(entry.get("D")),
        L_base=_opt_float(entry.get("L_base")),
        formation_rate=_opt_float(entry.get("formation_rate")),
        mechanism=str(entry.get("mechanism", "")),
        provenance=provenance,
    )


def _guideline_from_entry(guideline_id: str, meta: Any) -> Guideline:
    meta_dict = meta if isinstance(meta, dict) else {}
    provenance = Provenance(
        source=guideline_id,
        confidence=1.0,
        evidence_tier=None,
        computed_by=_COMPUTED_BY,
        contract_version=CONTRACT_VERSION,
    )
    return Guideline(
        guideline_id=guideline_id,
        org=_opt_str(meta_dict.get("org")),
        title=_opt_str(meta_dict.get("title")),
        year=_parse_year(meta_dict.get("edition")),
        url=_opt_str(meta_dict.get("url")),
        chunk=None,
        provenance=provenance,
    )


# ----------------------------------------------------------------------------- coercion helpers

_DIRECTION_FROM_TYPE: dict[str, Direction] = {
    "restrict": "limit",
    "limit": "limit",
    "avoid": "avoid",
    "target": "target",
    "maintain": "maintain",
    "prefer": "prefer",
}


def _read_yaml(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def _opt_str(value: object) -> str | None:
    return None if value is None else str(value)


def _opt_float(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float, str)):
        return float(value)
    raise TypeError(f"cannot coerce {value!r} to float")


def _coerce_float(value: object, default: float) -> float:
    if value is None:
        return default
    if isinstance(value, (int, float, str)):
        return float(value)
    return default


def _parse_year(value: object) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        match = re.search(r"\d{4}", value)
        if match is not None:
            return int(match.group())
    return None


def _as_tier(value: object) -> EvidenceTier | None:
    if value is None:
        return None
    text = str(value).strip().upper()
    if text == "A":
        return "A"
    if text == "B":
        return "B"
    if text == "C":
        return "C"
    return None


def _as_severity(value: object) -> Severity:
    text = str(value).strip().lower()
    if text == "absolute":
        return "absolute"
    if text == "strong":
        return "strong"
    if text == "soft":
        return "soft"
    return "moderate"


def _as_direction(value: object) -> Direction:
    text = str(value).strip().lower()
    if text == "avoid":
        return "avoid"
    if text == "target":
        return "target"
    if text == "maintain":
        return "maintain"
    if text == "prefer":
        return "prefer"
    return "limit"


def _as_channel(value: object) -> Channel:
    text = str(value).strip().lower()
    if text == "leaching":
        return "leaching"
    if text == "degradation":
        return "degradation"
    if text == "formation":
        return "formation"
    return "concentration"
