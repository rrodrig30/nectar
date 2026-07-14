# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

# NECTAR Platform

Monorepo. Two programs that share one database contract.
- NutriScrape (`nutriscrape/`): batch data engine, builds the Neo4j graph. No user.
- NECTAR (`nectar/`): clinician-facing app, reads the graph, composes per patient.

Ronald owns clinical intent. Claude implements against the specs and does not relax invariants.

## Specs (read before implementing)
- Shared schema, the source of truth: @contract/DATA_CONTRACT.md
- NutriScrape: @nutriscrape/docs/SDD.md and @nutriscrape/docs/PDD.md
- NECTAR: @nectar/docs/SDD.md and @nectar/docs/PDD.md
- Deployment: @deploy/README.md

## Platform invariants (never violate)
- No nutrient value ever comes from a language model. Models do extraction, parsing, ranking,
  and narration only. Nutrient numbers are read from the graph, always.
- No clinical threshold literals in code. They live in config (conditions, transforms, sources).
- Deterministic clinical derivation. Labs-to-constraints uses validated formulas, not the model.
  No derived constraint drives a recommendation until the physician confirms it.
- Never average opposing constraints across conditions. The safety-dominant restriction wins and
  a conflict note is emitted. Safety dominates goals.
- Hard-limit breaches produce a contraindication, not a low score.
- Evidence tiers: A/B may reach a patient, C is research-only. Promotion only via the gated path.
- Every recommendation carries citations and the intended-use boundary. No citations means the
  verifier rejected it; do not return it.
- NECTAR writes the shared graph only through the gated write-back service. Everything else reads.
- Every written value carries source, confidence, evidence_tier, computed_by, contract_version.

## Boundaries
- Pure logic (no I/O): scoring/, engine/, nutrition/transform.py. Unit-tested in isolation.
- I/O: graph/, acquisition/, resolution/, api/.
- All Cypher is parameterized and lives in the graph modules.
- Clinical golden tests must always pass in CI (potassium conflict, contraindication-not-low-score,
  boiled-vs-baked potassium, drain/no-drain parse, lab-derivation, verifier rejection).

## Commands
There is no root Makefile. Each program is a separate Python package (its own `pyproject.toml`,
`Makefile`, and `tests/`); run `make` from inside `nutriscrape/` or `nectar/`.

- `cd nutriscrape && make check` — ruff + mypy (strict) + unit/clinical pytest. Run before done.
- `cd nectar && make check` — same for the app.
- `make test` runs `tests/unit tests/clinical`; `make test-int` runs `tests/integration`
  (ephemeral Neo4j via testcontainers, needs a container runtime).
- Single test: `cd nectar && pytest tests/clinical/test_conflicts.py::test_name -q`.
- NutriScrape batch stages: `make schema | ingest | cluster | knowledge | materialize`
  (dispatched by `python -m nutriscrape <stage>`).
- NECTAR runtime: `cd nectar && make api` (uvicorn) and `make web` (Vite/React in `web/`).
- mypy is `strict` and ruff `line-length = 100` in both packages; keep both clean.

## Repository state and code map
The specs (contract, SDDs, PDDs) and clinical invariants are complete, and every `src/` module is
now implemented and unit/clinical-tested: `make check` is green in both packages (~109 tests, ruff +
mypy --strict clean). Build order and per-phase acceptance criteria live in each `docs/PDD.md`
Section 10. The pure-logic cores (four-channel transform, scoring/conflicts, engine, abstraction,
clustering, meal plan) carry the invariants and have golden tests; the I/O layers (graph, resolution,
extraction, contract client, LLM backends, API, gated write-back) are wired and tested against fakes.

What is genuinely NOT done yet (external data / infra, tracked to PDD phases, not fake code):
- NutriScrape acquisition adapters (`acquisition/adapters/*`) are still 4-line stubs (PDD Phase 1):
  no dataset/schema.org scraping, so `run_ingest` has no corpus to pull.
- No FDC nutrient-number to contract `nutrient_id` mapping yet, so cooked `HAS_NUTRIENT` vectors are
  not written by `run_ingest` (PDD Phase 2). `run_cluster`/`run_materialize` need corpus graph-read
  helpers that do not exist yet, so they no-op with a warning against a populated graph.
- `nectar/web/` is a placeholder (`main.tsx` only); no frontend is built.
- Nothing has been exercised against a live Neo4j / Ollama / FDC in-repo; "wired" means import- and
  type-level plus fake-backed tests, not runtime-verified against real services.
`make schema` and `make knowledge` are fully functional against a configured Neo4j; the other batch
stages run every real function that exists and log the specific missing upstream piece.

- `contract/` — source of truth. `DATA_CONTRACT.md`, `schema/schema.cypher` (the DDL `make schema`
  applies), and `nectar_contract/` (shared Pydantic types + node/relationship name constants both
  programs import). Never redefine schema names outside here.
- `nutriscrape/src/nutriscrape/` — pure logic in `nutrition/` (transform math, no I/O) and
  `clustering/score.py`; I/O in `graph/`, `acquisition/`, `resolution/`, `extraction/`. All Cypher
  is parameterized and lives in `graph/`.
- `nectar/src/nectar/` — pure logic in `scoring/`, `engine/`, `present/units.py`; I/O in `api/`,
  `common/contract_client.py` (read-only Neo4j, all Cypher here), `research/verify.py` (the one
  gated write path). `abstraction/` is the highest-scrutiny component (labs -> constraints).
- Clinical values are config, not code: `nutriscrape/config/` (nutrients, sources, transforms,
  retention, attributes) and `nectar/config/` (equations.yaml, derivation/, conditions/).

## rules.txt [ENFORCED]
The engineering charter is @rules.txt (imported here, so it is in context on every task). It is a
strict "no placeholders / no mock code / no fallbacks / everything functions as designed" contract.
It is binding, not aspirational.

**Enforcement (every task):**
- Ship only real, working code. No placeholder, mock, demo, simplified, stubbed, or partially
  functioning implementations; no silent fallbacks or emergency bypasses; no orphan, duplicate, or
  dead endpoints. If a piece cannot be built for real yet, do not fake it: state the missing
  upstream dependency plainly (see "What is genuinely NOT done yet" above) and stop there.
- Configuration is environment-driven: values come from `.env` / `config/`, never hardcoded in code.
- Refactoring uses the charter's Chain-of-Thought and Tree-of-Thought discipline (root-cause first,
  then evaluate solutions on reliability, efficiency, completeness, scalability, compliance).
- A task is done only when `cd <program> && make check` is green (ruff + mypy --strict + pytest,
  clinical golden tests included) and the phase acceptance criterion is met. The compliance-enforcer
  and honest-broker subagents gate against this charter; do not claim completion around them.

**Reconcile with reality (this is not a loophole):** the empty `src/` stubs are the intended
phased-build starting point, and the numeric clinical/config values are deliberately ILLUSTRATIVE
pending clinician review. Implement real logic when building a phase; do not "fix" the scaffold to
look finished, and do not invent clinical numbers to satisfy the rule. Building the real thing is
compliance; faking completeness is the violation the charter exists to prevent.

## Style
American spellings, no em-dashes in code comments and docs. No secrets committed; only *.env.example.
Numeric clinical values in config are ILLUSTRATIVE placeholders pending dietitian review.
