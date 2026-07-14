"""Unit tests for the clinical-KB graph writers: parameterized Cypher, correct params, no live DB."""
from typing import Any

import pytest

from nectar_contract.types import Provenance
from nutriscrape.graph.writers import (
    link_imposes,
    merge_dietary_rule,
    merge_guideline,
    write_interacts_with,
    write_transform,
)
from nutriscrape.knowledge.loaders import DietaryRule, Guideline, Interaction, TransformCoeff

_PROV = Provenance(source="kdoqi", confidence=0.7, evidence_tier=None,
                   computed_by="test", contract_version="1.0")


class _FakeClient:
    def __init__(self) -> None:
        self.writes: list[tuple[str, dict[str, Any]]] = []

    def run_write(self, cypher: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        self.writes.append((cypher, params))
        return []


def test_merge_dietary_rule_carries_provenance_and_is_parameterized():
    c = _FakeClient()
    rule = DietaryRule(rule_id="ckd:potassium:limit", direction="limit", severity="absolute",
                       threshold=1000.0, unit="mg", safety_critical=True, basis="x",
                       acts_on="potassium", guideline_id="kdoqi-potassium", provenance=_PROV)
    merge_dietary_rule(c, rule=rule)
    assert len(c.writes) == 1
    cypher, params = c.writes[0]
    assert ":DietaryRule" in cypher and "$rule_id" in cypher
    assert params["rule_id"] == "ckd:potassium:limit" and params["safety_critical"] is True
    assert params["source"] == "kdoqi" and params["contract_version"] == "1.0"


def test_write_transform_merges_method_and_uses_stable_transform_id():
    c = _FakeClient()
    coeff = TransformCoeff(food_class=None, food_id="171705", method="boil", target="potassium",
                           channel="leaching", D=None, L_base=0.3, formation_rate=None,
                           mechanism="leach", provenance=_PROV)
    write_transform(c, coeff=coeff)
    assert len(c.writes) == 2                       # merge_method, then the TRANSFORM edge
    method_cypher, _ = c.writes[0]
    tx_cypher, tx_params = c.writes[1]
    assert ":Method" in method_cypher
    assert ":TRANSFORM" in tx_cypher and "transform_id: $transform_id" in tx_cypher
    # this key is what the gated write-back promotes against (DATA_CONTRACT Section 8)
    assert tx_params["transform_id"] == "171705:boil:potassium:leaching"


def test_link_imposes_rejects_an_unknown_factor_label():
    c = _FakeClient()
    link_imposes(c, factor_label="Condition", factor_id="ckd", rule_id="r1")
    assert c.writes and ":Condition" in c.writes[0][0]
    with pytest.raises(ValueError):
        link_imposes(c, factor_label="Robert'); DROP", factor_id="x", rule_id="r1")


def test_write_interacts_with_and_merge_guideline():
    c = _FakeClient()
    inter = Interaction(medication="warfarin", target="vitamin_k", mechanism="antagonism",
                        effect="reduced INR", severity="strong", direction="maintain",
                        threshold=None, provenance=_PROV)
    write_interacts_with(c, interaction=inter)
    assert ":INTERACTS_WITH" in c.writes[-1][0] and c.writes[-1][1]["medication_id"] == "warfarin"
    g = Guideline(guideline_id="kdoqi-potassium", org="KDOQI", title="t", year=2020, url=None,
                  chunk=None, provenance=_PROV)
    merge_guideline(c, guideline=g)
    assert ":Guideline" in c.writes[-1][0] and c.writes[-1][1]["year"] == 2020
