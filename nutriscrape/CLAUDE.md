# NutriScrape

Batch data engine. Builds the shared Neo4j hybrid database. No interactive user.

## Specs
- Architecture: @docs/SDD.md
- Implementation: @docs/PDD.md
- Shared schema (do not redefine): @../contract/DATA_CONTRACT.md

## Invariants
- No nutrient value ever comes from a language model. Models do extraction only (ingredient lines,
  preparation steps). They emit structured fields and hand off.
- The four-channel transform (nutrition/transform.py) is the only path to a cooked nutrient value.
- Every written value carries source, confidence, evidence_tier, computed_by, contract_version.
- Writes conform to the pinned contract version. Nothing patient-specific is written here.
- The preparation parser is on the critical path: a wrong liquid_retained_frac flips potassium
  between leached and retained. It owns the drain/no-drain golden test.

## Commands (use verbatim)
- make schema   apply the contract DDL (idempotent)
- make ingest   acquisition -> extraction -> resolution -> nutrition
- make cluster  dish clustering
- make knowledge load rules/interactions/transforms/guidelines from config
- make check    ruff + mypy + pytest  (run before declaring a task done)

## Style
American spellings, no em-dashes. No secrets in config; only .env.example is committed.
Numeric transform coefficients are ILLUSTRATIVE placeholders pending review.
