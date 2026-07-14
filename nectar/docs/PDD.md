# NECTAR Program Design Document

**Implementation specification for the clinical application**

Version 1.0 · Companion to [`SDD.md`](./SDD.md). Schema: [`../../contract/DATA_CONTRACT.md`](../../contract/DATA_CONTRACT.md).

> Build from this directly in Claude Code. Schema names come from the contract. Items marked [INVARIANT] must not be relaxed. The patient abstraction layer (Section 5) is the highest-scrutiny component.

---

## 1. Repository Layout

```
nectar-platform/
├── contract/                      # shared, pinned (see contract PDD)
└── nectar/
    ├── CLAUDE.md                  # program map (Appendix A)
    ├── docs/{SDD.md,PDD.md}
    ├── pyproject.toml
    ├── Makefile
    ├── .env.example
    ├── config/
    │   ├── settings.yaml          # LLM backends, hyperparams, context window
    │   ├── derivation/            # validated formulas + lab→state thresholds
    │   └── equations.yaml         # energy/protein equations, eGFR, BMI
    ├── src/nectar/
    │   ├── common/                # config, provenance, contract client
    │   ├── abstraction/           # [highest scrutiny]
    │   │   ├── intake.py          # structured profile ingest
    │   │   ├── parse_history.py   # LLM: free-text PMH → structured factors
    │   │   ├── derive.py          # DETERMINISTIC labs+factors → constraints
    │   │   └── confirm.py         # physician confirmation contract
    │   ├── engine/
    │   │   ├── constraints.py     # assemble + resolve (conflicts) [INVARIANT]
    │   │   ├── evaluate.py        # two-stage: filter + score
    │   │   ├── rank.py            # within-dish and across-dish ranking
    │   │   └── remediate.py       # mechanism→intervention, re-score all
    │   ├── plan/
    │   │   └── mealplan.py        # weekly plan; plan-level maintain rules
    │   ├── present/
    │   │   ├── units.py           # canonical → US/metric, C/F
    │   │   ├── serving.py         # standardized servings
    │   │   └── disclaimer.py      # calculated-not-measured, per value
    │   ├── interact/
    │   │   ├── qa.py              # LLM: request → structured query
    │   │   ├── explain.py         # LLM: grounded, cited narration (GraphRAG)
    │   │   └── modify.py          # taste/equipment → constraint rerun
    │   ├── research/
    │   │   ├── hypotheses.py      # surface Tier C, generate study stub
    │   │   └── verify.py          # submit measurement → gated write-back client
    │   ├── llm/
    │   │   └── backends.py        # Ollama | Anthropic | OpenAI behind one interface
    │   └── api/
    │       ├── app.py             # FastAPI factory
    │       ├── deps.py            # auth, contract session, settings
    │       ├── schemas.py
    │       └── routes/            # profile, recommend, plan, ask, modify, research
    ├── web/                       # React + TypeScript
    └── tests/{unit,clinical,integration,fixtures}/
```

---

## 2. Environment and Commands

Python 3.11+, FastAPI, Pydantic v2, `neo4j` driver, React/Vite frontend. LLM backends pluggable.

```
make api           # uvicorn --reload
make web           # frontend dev server
make check         # ruff + mypy + pytest  (before declaring a task done)
make test-int      # integration against ephemeral neo4j + fixture graph
```

`.env`: `NEO4J_*` (read role), `LLM_BACKEND` (ollama|anthropic|openai), `LLM_MODEL`, `LLM_TEMPERATURE`, `LLM_CONTEXT_WINDOW`, `CONTRACT_VERSION`, `WRITEBACK_SERVICE_URL`.

---

## 3. Coding Conventions

- Type everything; `mypy` clean.
- Pure engine logic (constraints, evaluate, rank, remediate) is I/O-free and unit-tested in isolation.
- [INVARIANT] The LLM never sets or evaluates a clinical limit and never emits a nutrient number. It parses at intake and narrates at output. Thresholds and scoring are code.
- [INVARIANT] No numeric constraint literals in code; they come from the contract knowledge base and `config/derivation/`.
- [INVARIANT] NECTAR writes the shared graph only through `research/verify.py` to the gated service. No other graph writes.
- American spellings, no em-dashes in comments and docs.

---

## 4. Contract Access

`common/contract client` wraps read queries against the pinned contract version and exposes typed accessors: dish and variant facts, rule and interaction lookups, transform and intervention classes, guideline retrieval. All Cypher lives here, parameterized. NECTAR holds a read role on Neo4j; the write-back goes to a separate service endpoint, not a Neo4j write session.

---

## 5. Patient Abstraction Layer (`abstraction/`) [highest scrutiny]

### 5.1 Models

```python
class ClinicalSnapshot(BaseModel):        # de-identified, transient
    pmh: list[str] | str                  # coded or free text
    metabolic_panel: dict[str, float]     # e.g. {"K": 5.4, "Cr": 1.8, "glucose": 142}
    cbc: dict[str, float]                  # e.g. {"Hgb": 10.1, "ANC": 900}
    medications: list[str]                # names or rxnorm
    allergies: list[str]
    age: int; sex: Literal["M","F"]
    weight_kg: float; height_cm: float
    activity_level: Literal["sedentary","light","moderate","active"]
    goal: str

class DerivedConstraint(BaseModel):
    rule_id: str | None                   # existing rule, or synthesized
    source_signal: str                    # "serum K 5.4", "eGFR 34 → CKD 3b", "ANC 900"
    direction: Literal["avoid","limit","target","maintain","prefer"]
    target: str; severity: str
    value: float | None; unit: str | None
    formula: str | None                   # validated equation used
    confirmed: bool = False               # physician must set true [INVARIANT]
```

### 5.2 Derivation is deterministic [INVARIANT]

```python
def derive(snapshot: ClinicalSnapshot) -> list[DerivedConstraint]:
    factors = parse_history(snapshot.pmh)          # LLM: text → structured factors ONLY
    out: list[DerivedConstraint] = []
    out += rules_for_conditions(factors.conditions)     # from contract KB
    out += rules_for_medications(snapshot.medications)  # interaction edges
    out += hard_filters_for_allergies(snapshot.allergies)
    out += state_from_labs(snapshot)               # eGFR, CKD stage, hyperkalemia, neutropenia…
    out += energy_protein_envelope(snapshot)       # validated equations from config
    return out                                     # all confirmed=False
```

`state_from_labs` and `energy_protein_envelope` use only validated formulas from `config/equations.yaml` and thresholds from `config/derivation/`. No model call produces a number. Example bindings: eGFR from creatinine, age, sex; CKD stage from eGFR pulls renal rules; serum K above threshold tightens the potassium ceiling; ANC below threshold activates the raw-food exclusion; Hgb below threshold pulls iron-bioavailability rules.

### 5.3 Confirmation gate [INVARIANT]
`confirm.py` returns the derived set to the physician. No `DerivedConstraint` with `confirmed=False` may enter the engine. The UI shows each constraint, its `source_signal`, and its `formula`, and allows override.

---

## 6. Engine (`engine/`)

Reuses the platform's two-stage model. `constraints.resolve` merges confirmed constraints, groups by target, and applies the safety-dominant precedence (never averages opposing directions). `evaluate` runs Stage 1 filter then Stage 2 score against contract variant facts. `rank` orders versions within a dish and dishes across each other. `remediate` fires only when no admissible version exists: it matches the failing target to `InterventionClass` via `ADDRESSED_BY`, proposes a variant, and re-runs the full constraint set against it.

```python
def recommend(constraints: list[DerivedConstraint], prefs, exclusions) -> Result:
    assert all(c.confirmed for c in constraints)          # [INVARIANT]
    merged, conflicts = resolve(constraints)
    admissible = evaluate(merged, exclusions)             # Stage 1 + Stage 2
    ranked = rank(admissible)
    if not ranked.covers_all_requested_dishes():
        ranked += remediate(merged, gap=ranked.gaps())    # labeled suggestions
    return Result(ranked=ranked, conflicts=conflicts, boundary=BOUNDARY)
```

---

## 7. Meal Plan (`plan/mealplan.py`)

A constrained weekly selection across admissible dishes. Single-recipe facts come from the engine; the planner adds the plan-level `maintain` evaluation over the window (vitamin K consistency, daily fluid, daily energy and protein envelopes). Solve as a bounded constraint-satisfaction or greedy-with-repair selection; variety and envelopes are objectives, consistency and daily ceilings are constraints.

---

## 8. Presentation (`present/`)

`units.convert(value, system, temp_scale)` renders canonical values to US/metric and C/F at display time. `serving.standardize` maps the canonical per-serving basis to a standardized patient serving. `disclaimer.attach` puts the calculated-not-measured note on every nutrient value, specificity drawn from the contract `confidence` and `source`.

---

## 9. Interaction (`interact/`)

`qa.parse` turns a clinician request into a structured query (LLM at the front). `explain.narrate` produces grounded, cited prose over the engine's ranking (GraphRAG at the back); it may only cite retrieved guideline nodes and reads nutrient numbers from the graph. `modify.apply` turns taste or equipment limits into added preferences or exclusions (no grill, no convection oven, no stand mixer) and reruns the engine.

---

## 10. Research and Write-Back (`research/`)

`hypotheses.surface` returns Tier C items for a target and builds the study stub. `verify.submit` posts a measurement record to the gated promotion service (contract Section 8). [INVARIANT] This is the only write path. It cannot promote without a linked measurement and a named reviewer, and it can only move `C→B` or `B→A`.

---

## 11. API Contract (routes)

| Endpoint | Method | Purpose |
|---|---|---|
| `/profile/derive` | POST | Snapshot in, derived constraints out (unconfirmed) |
| `/profile/confirm` | POST | Physician-confirmed constraint set |
| `/recommend` | POST | Confirmed constraints in, ranked dishes/versions out |
| `/plan/week` | POST | Weekly meal plan with plan-level constraints |
| `/ask` | POST | Natural-language question over the current context |
| `/modify` | POST | Taste/equipment change, re-ranked result |
| `/research/hypotheses` | GET | Tier C items and study stub for a target |
| `/research/verify` | POST | Submit measurement to the gated write-back |

Every recommendation response carries the boundary statement and per-value calculated-not-measured flags.

---

## 12. Testing

- Unit: `resolve` precedence, `evaluate` filter/score, unit conversions, serving standardization.
- [INVARIANT] Clinical golden tests: derivation from a lab panel (serum K 5.4 tightens potassium; Cr+age+sex → eGFR → CKD stage rules; ANC 900 activates raw-food exclusion); potassium conflict CKD+HTN resolves to restriction; remediation that fixes potassium but breaks sodium is flagged; no unconfirmed constraint reaches the engine.
- Integration: fixture graph via testcontainers; full `/profile/derive → confirm → recommend → plan` path; verify write-back rejects promotion without a reviewer.
- Interaction: an `explain` stub that emits an uncited claim or an out-of-set recipe is stripped.

---

## Appendix A — Suggested `nectar/CLAUDE.md`

```markdown
# NECTAR

Clinician-facing application. Reads the shared Neo4j database; composes per patient.
Primary user: a primary care physician with a complex multimorbid patient.

## Specs
- Architecture: @docs/SDD.md
- Implementation: @docs/PDD.md
- Shared schema (read-only, do not redefine): @../contract/DATA_CONTRACT.md

## Invariants
- The patient abstraction derives constraints DETERMINISTICALLY from validated formulas.
  The LLM parses free-text history into factors only. It never produces a number.
- No derived constraint drives a recommendation until the physician confirms it.
- The LLM never sets or evaluates a clinical limit. It parses at intake, narrates at output.
- Two-stage evaluation and conflict precedence are code, never the model. Safety dominates goals.
- Canonical units are stored; US/metric and C/F are display-time only.
- Every nutrient value shows the calculated-not-measured disclaimer.
- The only write to the shared graph is research/verify.py via the gated service (C→B→A).

## Commands
- make api · make web · Verify before done: make check · make test-int

## Style
American spellings, no em-dashes. De-identified, transient profiles only. No patient records persisted.
```

---

*Schema: [`../../contract/DATA_CONTRACT.md`](../../contract/DATA_CONTRACT.md).*
