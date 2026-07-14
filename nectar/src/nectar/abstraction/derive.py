"""Patient abstraction: labs + factors -> constraints. [INVARIANT] DETERMINISTIC.

The LLM may parse free-text history into factors (see parse_history.py). This module turns factors
and labs into constraints using validated formulas from config/equations.yaml only. No model call
produces a number. Every DerivedConstraint starts confirmed=False and cannot enter the engine until
the physician confirms it (see confirm.py). See ../../docs/PDD.md Section 5, SDD Section 3.
"""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml

from nectar.abstraction.thresholds import LabThresholds, load_lab_thresholds
from nectar.common.config import nectar_config_dir

Direction = Literal["avoid", "limit", "target", "maintain", "prefer"]


def _config_dir() -> Path:
    return nectar_config_dir()


def _load_equations(path: str | Path | None = None) -> dict[str, Any]:
    p = Path(path) if path is not None else _config_dir() / "equations.yaml"
    with open(p, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data if isinstance(data, dict) else {}


@dataclass
class ClinicalSnapshot:
    """De-identified, transient. Not persisted with identity."""
    pmh: list[str]
    metabolic_panel: dict[str, float]      # e.g. {"K": 5.4, "Cr": 1.8, "glucose": 142}
    cbc: dict[str, float]                  # e.g. {"Hgb": 10.1, "ANC": 900}
    medications: list[str]
    allergies: list[str]
    age: int
    sex: Literal["M", "F"]
    weight_kg: float
    height_cm: float
    activity_level: Literal["sedentary", "light", "moderate", "active"]
    goal: str


@dataclass
class DerivedConstraint:
    source_signal: str                     # "serum K 5.4", "eGFR 34 -> CKD 3b", "ANC 900"
    direction: Direction
    target: str
    severity: str
    value: float | None = None
    unit: str | None = None
    formula: str | None = None
    guideline_id: str | None = None
    confirmed: bool = False                # [INVARIANT] physician must set True


def egfr_ckd_epi_2021(creatinine: float, age: int, sex: str) -> float:
    """CKD-EPI 2021 (creatinine, race-free). Validated formula, not a model output."""
    k = 0.7 if sex == "F" else 0.9
    a = -0.241 if sex == "F" else -0.302
    sex_factor = 1.012 if sex == "F" else 1.0
    scr_k = creatinine / k
    egfr = 142 * (min(scr_k, 1.0) ** a) * (max(scr_k, 1.0) ** -1.200) * (0.9938 ** age) * sex_factor
    return float(egfr)


def ckd_stage_from_egfr(egfr: float, path: str | Path | None = None) -> str:
    """Map eGFR to a CKD stage using the config table (equations.yaml), not a literal in code."""
    table = _load_equations(path).get("ckd_stage_from_egfr", [])
    for row in table:
        lo = row.get("min")
        hi = row.get("max")
        if (lo is None or egfr >= lo) and (hi is None or egfr <= hi):
            return str(row.get("stage", "?"))
    return "?"


def state_from_labs(s: ClinicalSnapshot,
                    thresholds: LabThresholds | None = None) -> list[DerivedConstraint]:
    """Deterministic labs -> constraints. Thresholds come from config (equations.yaml), never a
    literal in code and never a model output. [INVARIANT]"""
    t = thresholds if thresholds is not None else load_lab_thresholds()
    out: list[DerivedConstraint] = []
    k = s.metabolic_panel.get("K")
    if k is not None and k > t.hyperkalemia_k:
        out.append(DerivedConstraint(
            source_signal=f"serum K {k}", direction="limit", target="potassium",
            severity="strong", formula="serum K > hyperkalemia threshold",
            guideline_id="kdoqi-potassium"))
    cr = s.metabolic_panel.get("Cr")
    if cr is not None:
        egfr = egfr_ckd_epi_2021(cr, s.age, s.sex)
        stage = ckd_stage_from_egfr(egfr)
        out.append(DerivedConstraint(
            source_signal=f"eGFR {egfr:.0f} -> CKD {stage}", direction="limit",
            target="renal_panel", severity="strong", value=round(egfr, 1),
            unit="mL/min/1.73m2", formula="CKD-EPI 2021"))
    anc = s.cbc.get("ANC")
    if anc is not None and anc < t.neutropenia_anc:
        out.append(DerivedConstraint(
            source_signal=f"ANC {anc}", direction="avoid", target="raw_animal_protein",
            severity="absolute", formula="ANC < neutropenia threshold"))
    hgb = s.cbc.get("Hgb")
    if hgb is not None and hgb < t.anemia_hgb:
        out.append(DerivedConstraint(
            source_signal=f"Hgb {hgb}", direction="prefer", target="iron_bioavailability",
            severity="soft", formula="Hgb < anemia threshold"))
    return out


_TYPE_TO_DIRECTION: dict[str, Direction] = {"restrict": "limit", "limit": "limit",
                                            "target": "target", "avoid": "avoid",
                                            "maintain": "maintain", "prefer": "prefer"}


def rules_for_conditions(factors: list[str],
                         config_dir: str | Path | None = None) -> list[DerivedConstraint]:
    """Conditions become disease :DietaryRule sets, read from config/conditions/*.yaml (the local
    mirror of the contract KB). Numbers are config, never a model output. A factor matches a file by
    its disease_id or name. See SDD Section 3.2."""
    base = Path(config_dir) if config_dir is not None else _config_dir()
    conditions_dir = base / "conditions"
    if not conditions_dir.is_dir():
        return []
    wanted = {f.strip().lower() for f in factors}
    out: list[DerivedConstraint] = []
    for path in sorted(conditions_dir.glob("*.yaml")):
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        if not isinstance(data, dict):
            continue
        disease_id = str(data.get("disease_id", path.stem)).lower()
        name = str(data.get("name", "")).lower()
        if disease_id not in wanted and name not in wanted:
            continue
        for c in data.get("constraints", []) or []:
            ctype = str(c.get("type", "limit"))
            direction = _TYPE_TO_DIRECTION.get(ctype, "limit")
            value = c.get("goal") if direction == "target" else c.get("max_per_serving")
            severity = "absolute" if c.get("safety_critical") else (
                "strong" if c.get("hard_limit") is not None else "moderate")
            out.append(DerivedConstraint(
                source_signal=f"condition {disease_id}", direction=direction,
                target=str(c.get("nutrient", "unknown")), severity=severity,
                value=_as_float(value), unit=_opt_str(c.get("unit")),
                formula=f"{data.get('guideline_org', 'guideline')} disease rule",
                guideline_id=_opt_str(c.get("guideline_id"))))
    return out


def rules_for_medications(medications: list[str],
                          config_dir: str | Path | None = None) -> list[DerivedConstraint]:
    """Medications become interaction rules, read from config/interactions/*.yaml. The curated
    interaction table is not yet populated (contract Section 3.3), so this returns the interactions
    that exist today and no fabricated rule. See SDD Section 3.2."""
    base = Path(config_dir) if config_dir is not None else _config_dir()
    interactions_dir = base / "interactions"
    if not interactions_dir.is_dir():
        return []
    wanted = {m.strip().lower() for m in medications}
    out: list[DerivedConstraint] = []
    for path in sorted(interactions_dir.glob("*.yaml")):
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        if not isinstance(data, dict):
            continue
        for entry in data.get("interactions", []) or []:
            if str(entry.get("medication", "")).lower() not in wanted:
                continue
            out.append(DerivedConstraint(
                source_signal=f"medication {entry.get('medication')}",
                direction=_TYPE_TO_DIRECTION.get(str(entry.get("direction", "limit")), "limit"),
                target=str(entry.get("target", "unknown")),
                severity=str(entry.get("severity", "moderate")),
                value=_as_float(entry.get("threshold")), unit=_opt_str(entry.get("unit")),
                formula=str(entry.get("mechanism", "food-drug interaction"))))
    return out


def energy_protein_envelope(s: ClinicalSnapshot,
                            path: str | Path | None = None) -> list[DerivedConstraint]:
    """Objective data and goal set the energy and protein envelope via the Mifflin-St Jeor equation
    and config factors. All coefficients and adjustments come from equations.yaml. These are
    plan-level: energy is a maintain rule, protein a target. See SDD Section 3.2, PDD Section 7."""
    eq = _load_equations(path)
    energy_cfg = eq.get("energy", {})
    protein_cfg = eq.get("protein", {})
    factors = energy_cfg.get("activity_factor", {})
    factor = _as_float(factors.get(s.activity_level)) or 1.2
    sex_term = 5 if s.sex == "M" else -161
    bmr = 10 * s.weight_kg + 6.25 * s.height_cm - 5 * s.age + sex_term
    tdee = bmr * factor
    goal = s.goal.lower()
    adjustments = energy_cfg.get("goal_adjustment_kcal", {})
    key = "loss" if "loss" in goal else "gain" if "gain" in goal else "maintenance"
    target_kcal = tdee + (_as_float(adjustments.get(key)) or 0.0)
    protein_g = (_as_float(protein_cfg.get("g_per_kg")) or 0.0) * s.weight_kg
    return [
        DerivedConstraint(source_signal=f"energy target ({key})", direction="maintain",
                          target="energy", severity="moderate", value=round(target_kcal, 0),
                          unit="kcal", formula="Mifflin-St Jeor x activity factor"),
        DerivedConstraint(source_signal="protein target", direction="target", target="protein",
                          severity="moderate", value=round(protein_g, 1), unit="g",
                          formula="g/kg x weight"),
    ]


def derive(snapshot: ClinicalSnapshot, factors: list[str] | None = None,
           thresholds: LabThresholds | None = None) -> list[DerivedConstraint]:
    """Assemble the unconfirmed constraint set from labs, conditions, medications, allergies, and the
    energy/protein envelope. `factors` come from parse_history (LLM, text->factors); when omitted, the
    coded PMH entries are used. Every number comes from config or a validated formula, never a model.
    All returned constraints are confirmed=False. See PDD Section 5.2, SDD Section 3.2.
    """
    condition_factors = factors if factors is not None else [p.strip().lower() for p in snapshot.pmh]
    out: list[DerivedConstraint] = []
    out += state_from_labs(snapshot, thresholds)
    out += rules_for_conditions(condition_factors)
    out += rules_for_medications(snapshot.medications)
    out += energy_protein_envelope(snapshot)
    # allergies -> absolute avoid filters (Stage 1 hard exclusions)
    for a in snapshot.allergies:
        out.append(DerivedConstraint(source_signal=f"allergy {a}", direction="avoid",
                                     target=a, severity="absolute"))
    return out  # all confirmed=False


def _as_float(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float, str)):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _opt_str(value: object) -> str | None:
    return None if value is None else str(value)
