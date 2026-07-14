"""Clinical golden tests for the deterministic patient abstraction. [INVARIANT] Must pass in CI.

Covers lab-derivation (serum K, eGFR/CKD, ANC neutropenia, Hgb anemia), the de-identification
guard, the confirmation gate, and that parse_history never emits a number.
See nectar/docs/PDD.md Section 12.
"""
import pytest

from nectar.abstraction.derive import (
    ClinicalSnapshot,
    derive,
    egfr_ckd_epi_2021,
    energy_protein_envelope,
    rules_for_conditions,
    state_from_labs,
)
from nectar.abstraction.parse_history import parse_history
from nectar.abstraction.intake import IdentifierRejected, ingest
from nectar.abstraction.confirm import confirm, as_review_items


def _snapshot(**over):
    base = dict(pmh=["ckd", "htn"], metabolic_panel={"K": 5.4, "Cr": 1.8},
                cbc={"Hgb": 10.1, "ANC": 900}, medications=["lisinopril"], allergies=["peanut"],
                age=67, sex="M", weight_kg=80.0, height_cm=175.0, activity_level="sedentary",
                goal="cardiovascular improvement")
    base.update(over)
    return ClinicalSnapshot(**base)


def test_serum_potassium_tightens_potassium():
    cons = state_from_labs(_snapshot())
    k = [c for c in cons if c.target == "potassium"]
    assert k and k[0].direction == "limit" and "5.4" in k[0].source_signal


def test_egfr_and_ckd_stage_derivation():
    # Cr 1.8, age 67, male -> eGFR ~41 -> CKD 3b; formula and stage table are code/config, not a model
    egfr = egfr_ckd_epi_2021(1.8, 67, "M")
    assert 25.0 < egfr < 50.0
    cons = state_from_labs(_snapshot())
    renal = [c for c in cons if c.target == "renal_panel"]
    assert renal and renal[0].formula == "CKD-EPI 2021"
    assert "CKD 3b" in renal[0].source_signal        # stage from config table, not hardcoded


def test_conditions_become_dietary_rules_from_config():
    # pmh includes ckd -> KDOQI renal constraints are pulled from config/conditions/ckd.yaml
    cons = rules_for_conditions(["ckd"])
    targets = {c.target for c in cons}
    assert {"potassium", "sodium", "phosphorus"} <= targets
    k = [c for c in cons if c.target == "potassium"][0]
    assert k.severity == "absolute" and k.guideline_id == "kdoqi-potassium"   # safety_critical
    assert all(not c.confirmed for c in cons)


def test_energy_protein_envelope_from_config_formula():
    env = energy_protein_envelope(_snapshot())
    energy = [c for c in env if c.target == "energy"][0]
    protein = [c for c in env if c.target == "protein"][0]
    assert energy.direction == "maintain" and energy.value and energy.value > 1000
    assert protein.direction == "target" and protein.value == 80.0   # 1.0 g/kg x 80 kg (config)


def test_anc_900_activates_raw_food_exclusion():
    cons = state_from_labs(_snapshot())
    raw = [c for c in cons if c.target == "raw_animal_protein"]
    assert raw and raw[0].direction == "avoid" and raw[0].severity == "absolute"


def test_allergy_becomes_absolute_avoid():
    cons = derive(_snapshot())
    peanut = [c for c in cons if c.target == "peanut"]
    assert peanut and peanut[0].direction == "avoid" and peanut[0].severity == "absolute"


def test_all_derived_constraints_start_unconfirmed():
    assert all(not c.confirmed for c in derive(_snapshot()))


def test_intake_rejects_direct_identifiers():
    with pytest.raises(IdentifierRejected):
        ingest({"name": "Jane Doe", "age": 67, "sex": "F", "weight_kg": 70, "height_cm": 165,
                "activity_level": "light", "goal": "weight loss"})


def test_confirmation_gate_drops_unconfirmed():
    cons = derive(_snapshot())
    items = as_review_items(cons)
    assert len(items) == len(cons)
    # physician approves only index 0
    confirmed = confirm(cons, approvals={0: True})
    assert len(confirmed) == 1 and confirmed[0].confirmed is True


def test_parse_history_emits_no_number():
    # coded short items become factors; the long free-text item needs the LLM parser, none given here
    factors = parse_history(["ckd", "htn", "type 2 diabetes mellitus on metformin"])
    assert "ckd" in factors.conditions and "htn" in factors.conditions
    blob = " ".join(factors.conditions + factors.medications + factors.notes)
    assert not any(ch.isdigit() for ch in blob)   # [INVARIANT] the factor output carries no number


def test_parse_history_delegates_free_text_to_injected_parser():
    def fake_llm(_text: str) -> dict[str, list[str]]:
        return {"conditions": ["t2dm"], "medications": ["metformin"]}

    factors = parse_history("longstanding type 2 diabetes, on metformin", parser=fake_llm)
    assert "t2dm" in factors.conditions and "metformin" in factors.medications
