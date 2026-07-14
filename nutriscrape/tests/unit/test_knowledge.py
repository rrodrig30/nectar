"""Unit tests for the knowledge-base loaders and the LLM drafter's review gate.

Two concerns, both pure (no network, no Neo4j):
- ``load_rules`` parses disease-rule YAML into typed :class:`DietaryRule` models with provenance.
- ``promote_to_live`` refuses to move a draft into live authority without a named reviewer, the
  governance invariant from DATA_CONTRACT.md Section 8 applied to initial authoring.
"""
from pathlib import Path

import pytest

from nutriscrape.knowledge.draft import (
    DraftEntry,
    ReviewGateError,
    parse_draft_response,
    promote_to_live,
)
from nutriscrape.knowledge.loaders import DietaryRule, load_transforms

_CONDITION_YAML = """
disease_id: ckd
name: Chronic Kidney Disease
guideline_org: KDOQI
constraints:
  - {nutrient: potassium, type: restrict, unit: mg, max_per_serving: 700, hard_limit: 1000, safety_critical: true, basis: "individualized", guideline_id: kdoqi-potassium}
  - {nutrient: fiber_total, type: target, unit: g, goal: 8, basis: "increase", guideline_id: kdoqi-fiber}
"""


def _write_conditions(tmp_path: Path) -> Path:
    conditions = tmp_path / "conditions"
    conditions.mkdir()
    (conditions / "ckd.yaml").write_text(_CONDITION_YAML, encoding="utf-8")
    return tmp_path


def test_load_rules_parses_yaml_into_typed_models(tmp_path):
    from nutriscrape.knowledge.loaders import load_rules

    config_dir = _write_conditions(tmp_path)
    rules = load_rules(config_dir)

    assert len(rules) == 2
    assert all(isinstance(rule, DietaryRule) for rule in rules)

    potassium = next(rule for rule in rules if rule.acts_on == "potassium")
    assert potassium.direction == "limit"          # "restrict" maps to the limit direction
    assert potassium.threshold == 700.0
    assert potassium.unit == "mg"
    assert potassium.safety_critical is True
    assert potassium.severity == "strong"          # a configured hard_limit is a firm ceiling
    assert potassium.rule_id == "ckd:potassium:limit"
    # Provenance (contract Section 1.1) rides on every produced record.
    assert potassium.provenance.source == "kdoqi-potassium"
    assert potassium.provenance.computed_by == "knowledge.loaders"
    assert potassium.provenance.contract_version

    fiber = next(rule for rule in rules if rule.acts_on == "fiber_total")
    assert fiber.direction == "target"
    assert fiber.threshold == 8.0                   # target reads the goal, not a max
    assert fiber.safety_critical is False
    assert fiber.severity == "moderate"


def test_load_transforms_from_real_config():
    config_dir = Path(__file__).resolve().parents[2] / "config"
    coeffs = load_transforms(config_dir)

    assert coeffs, "retention.yaml should yield transform coefficients"
    potassium = next(coeff for coeff in coeffs if coeff.target == "potassium")
    assert potassium.channel == "leaching"
    assert potassium.L_base == 0.30
    assert potassium.provenance.evidence_tier == "A"


def test_promote_to_live_requires_named_reviewer():
    draft = DraftEntry(kind="rule", payload={"nutrient": "sodium"}, drafted_by="m", confidence=0.4)
    # By construction a fresh draft is queued for review, never authoritative.
    assert draft.status == "pending_review"
    assert draft.reviewer is None

    with pytest.raises(ReviewGateError):
        promote_to_live(draft, None)
    with pytest.raises(ReviewGateError):
        promote_to_live(draft, "")
    with pytest.raises(ReviewGateError):
        promote_to_live(draft, "   ")

    approved = promote_to_live(draft, "Dr. Rodriguez")
    assert approved.status == "approved"
    assert approved.reviewer == "Dr. Rodriguez"
    # The original stays pending: promotion returns a copy, it does not mutate the queue entry.
    assert draft.status == "pending_review"
    assert draft.reviewer is None


def test_parse_draft_response_discards_model_supplied_status_and_reviewer():
    raw = (
        '[{"payload": {"medication": "warfarin", "target": "vitamin_k"},'
        ' "citations": [{"source": "Flockhart CYP table"}],'
        ' "confidence": 0.6, "evidence_tier": "B",'
        ' "status": "approved", "reviewer": "the model itself"}]'
    )
    entries = parse_draft_response(raw, "interaction", "llm-test")

    assert len(entries) == 1
    entry = entries[0]
    assert entry.status == "pending_review"    # [INVARIANT] model status ignored
    assert entry.reviewer is None              # [INVARIANT] model reviewer ignored
    assert entry.evidence_tier == "B"
    assert entry.citations[0].source == "Flockhart CYP table"
