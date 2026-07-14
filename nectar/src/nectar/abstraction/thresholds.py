"""Lab-trigger thresholds loaded from config. [INVARIANT] No clinical threshold literal in code.

The numeric cutoffs that switch on a physiologic state (hyperkalemia, neutropenia, anemia) live in
config/equations.yaml, not in code. This loader reads them into a typed value object the
deterministic derivation consumes. See ../../docs/PDD.md Section 5.2, root CLAUDE.md invariants.
"""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class LabThresholds:
    hyperkalemia_k: float        # serum K above this tightens the potassium ceiling
    neutropenia_anc: float       # ANC below this activates the raw-food safety exclusion
    anemia_hgb: float            # Hgb below this pulls in iron-bioavailability rules


def _equations_path() -> Path:
    return Path(__file__).resolve().parents[3] / "config" / "equations.yaml"


def load_lab_thresholds(path: str | Path | None = None) -> LabThresholds:
    """Read the lab_triggers block from config/equations.yaml. Raises if a required key is absent,
    so a missing threshold fails loudly rather than defaulting to a hidden literal."""
    p = Path(path) if path is not None else _equations_path()
    with open(p, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    triggers = data.get("lab_triggers")
    if not isinstance(triggers, dict):
        raise ValueError(f"lab_triggers block missing from {p}")
    return LabThresholds(
        hyperkalemia_k=float(triggers["hyperkalemia_mmol_l"]),
        neutropenia_anc=float(triggers["neutropenia_anc"]),
        anemia_hgb=float(triggers["anemia_hgb_g_dl"]),
    )
