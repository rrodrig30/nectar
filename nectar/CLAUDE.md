# NECTAR

Clinician-facing application. Reads the shared Neo4j database; composes per patient.
Primary user: a primary care physician with a complex multimorbid patient.

## Specs
- Architecture: @docs/SDD.md
- Implementation: @docs/PDD.md
- Shared schema (read-only, do not redefine): @../contract/DATA_CONTRACT.md

## Invariants
- The patient abstraction derives constraints DETERMINISTICALLY from validated formulas
  (config/equations.yaml). The LLM parses free-text history into factors only, never a number.
- No derived constraint drives a recommendation until the physician confirms it (confirmed=True).
- The LLM never sets or evaluates a clinical limit. It parses at intake, narrates at output.
- Two-stage evaluation and conflict precedence are code, never the model. Safety dominates goals.
- Hard-limit breaches produce a contraindication, not a low score.
- Canonical units are stored; US/metric and C/F are display-time only.
- Every nutrient value shows the calculated-not-measured disclaimer.
- The only write to the shared graph is research/verify.py via the gated service (C->B->A).
- Tier C hypotheses never enter the patient recommendation path.

## Commands
- make api        run the API (uvicorn --reload)
- make web        run the frontend dev server
- make check      ruff + mypy + pytest  (before declaring a task done)
- make test-int   integration against ephemeral neo4j

## Style
American spellings, no em-dashes. De-identified, transient profiles only; no patient records
persisted. Numeric clinical values in config are ILLUSTRATIVE placeholders pending dietitian review.
