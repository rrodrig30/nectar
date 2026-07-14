# NutriScrape Program Design Document

**Implementation specification for the data engine**

Version 1.0 · Companion to [`SDD.md`](./SDD.md). Schema: [`../../contract/DATA_CONTRACT.md`](../../contract/DATA_CONTRACT.md).

> Build from this directly in Claude Code. Schema names come from the contract and are not redefined here. Items marked [INVARIANT] must not be relaxed.

---

## 1. Repository Layout

Monorepo. NutriScrape is one program; the contract is a shared package both programs pin.

```
nectar-platform/
├── CLAUDE.md                      # root map + invariants; @imports contract
├── contract/
│   ├── DATA_CONTRACT.md
│   ├── schema/schema.cypher       # canonical DDL from contract Section 4
│   └── nectar_contract/           # shared pydantic types + node/rel name constants
├── nutriscrape/
│   ├── CLAUDE.md                  # program map (Appendix A)
│   ├── docs/{SDD.md,PDD.md}
│   ├── pyproject.toml
│   ├── Makefile
│   ├── config/
│   │   ├── sources.yaml           # adapters, trust tiers, license gates
│   │   ├── nutrients.yaml         # speciated nutrient vocabulary
│   │   ├── transforms/            # TRANSFORM coefficients by food/class × method
│   │   ├── interactions/          # drug-food interaction table (curated)
│   │   └── attributes.yaml        # food attribute / allergen / provenance tags
│   ├── src/nutriscrape/
│   │   ├── common/                # config, confidence, provenance, units
│   │   ├── acquisition/adapters/  # datasets.py, structured.py, base.py
│   │   ├── extraction/
│   │   │   ├── ingredients.py     # tier-1 model + escalation
│   │   │   ├── preparation.py     # step parser + ingredient linkage [critical]
│   │   │   └── models.py          # two-tier model client + confidence
│   │   ├── resolution/            # fdc_client.py, matcher.py (normalize→validate)
│   │   ├── nutrition/
│   │   │   ├── normalize.py       # → canonical units
│   │   │   ├── transform.py       # four-channel operator [INVARIANT]
│   │   │   └── variants.py        # variant generation (selective)
│   │   ├── clustering/
│   │   │   ├── fingerprint.py
│   │   │   ├── blocking.py
│   │   │   ├── score.py
│   │   │   └── resolve.py         # LLM only at threshold
│   │   ├── knowledge/
│   │   │   ├── draft.py           # LLM-drafted candidate entries → review queue
│   │   │   └── loaders.py         # rules, interactions, transforms, guidelines
│   │   └── graph/                 # client.py, schema.py, writers.py
│   └── tests/{unit,clinical,integration,fixtures}/
└── nectar/                        # separate program (own PDD)
```

---

## 2. Environment and Commands

Python 3.11+, Neo4j 5.x, Prefect (or Airflow), `neo4j` driver, Pydantic v2, `ruff`, `mypy`, `pytest`, `testcontainers`. Extraction models served locally (fine-tuned tier-1) with a hosted or larger local tier-2.

```
make schema        # apply contract/schema/schema.cypher (idempotent)
make ingest        # acquisition → extraction → resolution → nutrition
make cluster       # dish clustering (batch); make cluster-inc for incremental
make knowledge     # load rules/interactions/transforms/guidelines from config
make check         # ruff + mypy + pytest  (run before declaring a task done)
```

`.env`: `NEO4J_*`, `FDC_API_KEY`, `EXTRACT_MODEL_TIER1`, `EXTRACT_MODEL_TIER2`, `EMBEDDING_MODEL`, `CONTRACT_VERSION`.

---

## 3. Coding Conventions

- Type everything (Pydantic v2 at boundaries), `mypy` clean.
- Pure transform and clustering-score logic, no I/O. I/O in `graph/`, `acquisition/`, `resolution/`.
- [INVARIANT] No nutrient value is ever produced by a language model. Models emit structured extraction fields only.
- [INVARIANT] Every written value carries the contract Section 1.1 metadata.
- All Cypher parameterized, in `graph/`.
- American spellings, no em-dashes in comments and docs.
- A phase is done only when `make check` passes and its acceptance criterion is met.

---

## 4. Key Data Models

```python
class ParsedIngredient(BaseModel):
    quantity: float | None
    unit: str | None
    food: str
    prep_ref: str | None            # links to a preparation step
    qualifiers: list[str] = []
    parse_confidence: float

class ParsedPreparation(BaseModel):  # [critical path]
    method: str
    cut_class: str | None
    water_ratio: float | None
    liquid_retained_frac: float      # drain=0.0, soup=1.0 — flips leaching
    time_min: float | None
    temp_c: float | None
    applies_to: list[str]            # ingredient refs this step acts on
    parse_confidence: float

class TransformCoeff(BaseModel):
    target: str                      # nutrient_id or compound_id
    channel: Literal["concentration","leaching","degradation","formation"]
    D: float | None = None
    L_base: float | None = None
    formation_rate: float | None = None
    mechanism: str
    source: str
    confidence: float
    evidence_tier: Literal["A","B","C"]
```

---

## 5. The Four-Channel Transform (`nutrition/transform.py`) [INVARIANT]

```python
def cooked_amount(raw: float, coeffs: list[TransformCoeff], prep: ParsedPreparation) -> Fact:
    D = product(c.D for c in coeffs if c.channel == "degradation") or 1.0
    L = leach_fraction(coeffs, prep)          # scales with prep.cut_class SA:V, water, time, temp
    kept = prep.liquid_retained_frac
    reduced = raw * D * (1 - L * (1 - kept))
    formed = sum(formation(c, prep) for c in coeffs if c.channel == "formation")
    conf = min(c.confidence for c in coeffs) if coeffs else 0.5
    return Fact(value=reduced + formed, confidence=conf, source=provenance(coeffs, prep))

def leach_fraction(coeffs, prep) -> float:
    base = next((c.L_base for c in coeffs if c.channel == "leaching"), 0.0)
    geo = SA_V_MULT[prep.cut_class]           # whole ~1.0 … grated ~6+
    return clamp(base * geo * medium_factor(prep.water_ratio, prep.time_min, prep.temp_c), 0.0, L_MAX)
```

Mass balance (`cooked_mass_g` vs `raw_mass_g`) is applied for the concentration channel and drives per-gram values. Formation is a separate additive term so a method can create a compound (`HAS_COMPOUND` on the variant) the raw food never had.

---

## 6. Variant Generation (`nutrition/variants.py`)

The as-authored variant is always materialized. Alternative preparation variants are generated selectively, not as a full cross-product, and only for methods physically valid for the food (from the transform table's method coverage). Broad remediation variants are generated lazily by NECTAR at query time, not precomputed here. Bound the eager set to a small, culinarily sane method list per food.

---

## 7. Clustering (`clustering/`)

```python
def cluster_corpus():
    fps = [fingerprint(r) for r in recipes()]         # core FDC foods, proportions, method
    for block in block_by_core_signature(fps):        # avoids quadratic comparison
        for a, b in pairs(block):
            s = score(a, b)                            # weighted Jaccard + proportion + method + title-embed
            if s >= HIGH: union(a, b)
            elif s >= LOW: queue_llm_judgment(a, b)    # LLM only at the boundary
    for cluster in unions(): write_dish(cluster, membership_confidence=...)
```

Write dish-level nutrient distributions onto each `:Dish`. Granularity favors the finer split.

---

## 8. Knowledge Loaders (`knowledge/`)

`loaders.py` reads `config/` into the contract's rule, interaction, transform, and guideline structures. `draft.py` runs the LLM drafter that proposes candidate entries with citations into a review queue; nothing from the drafter is written live without a named reviewer.

---

## 9. Testing

- Unit: fingerprinting, blocking, `score`, `leach_fraction`, mass balance.
- [INVARIANT] Clinical golden tests: boiled-drained vs baked vs soup potato potassium; formation channel adds acrylamide under high-heat starch; cubed vs whole leaching ratio; a preparation parse where "drain" three steps later sets `liquid_retained_frac = 0`.
- Preparation-parser golden tests own the drain/no-drain case as the first regression guard.
- Integration: ephemeral Neo4j via testcontainers; ingest a fixture corpus; assert contract-conformant writes with metadata.

---

## 10. Phased Task Plan

Each phase done when `make check` passes and the criterion is met.

- **Phase 0 — Scaffolding.** Monorepo, contract package, `make schema` applies the DDL idempotently.
- **Phase 1 — Acquisition + extraction.** Adapters; two-tier ingredient and preparation parsers with per-field confidence. Done when a fixture corpus extracts with the drain/no-drain golden test passing.
- **Phase 2 — Resolution + nutrition.** FDC matcher; canonical normalization; four-channel transform. Done when variant nutrient vectors are written with transform provenance and the potato golden tests pass.
- **Phase 3 — Clustering.** Fingerprint, block, score, resolve; dish statistics. Done when a fixture corpus clusters into dishes with membership confidence and finer-split granularity honored.
- **Phase 4 — Knowledge bases.** Loaders and the LLM drafter into a review queue. Done when rules, interactions, transforms, and guidelines load contract-conformant and drafts never reach live authority without review.
- **Phase 5 — Scale + incremental.** Batch DAGs, incremental clustering, selective variant materialization. Done when the pipeline runs restartable at corpus scale within cost bounds.

---

## Appendix A — Suggested `nutriscrape/CLAUDE.md`

```markdown
# NutriScrape

Batch data engine. Builds the shared Neo4j hybrid database. No interactive user.

## Specs
- Architecture: @docs/SDD.md
- Implementation: @docs/PDD.md
- Shared schema (do not redefine): @../contract/DATA_CONTRACT.md

## Invariants
- No nutrient value ever comes from a language model. Models do extraction only.
- Every written value carries source, confidence, evidence_tier, computed_by, contract_version.
- The four-channel transform is the only path to a cooked nutrient value.
- Writes conform to the pinned contract version. Nothing patient-specific is written here.

## Commands
- make schema · make ingest · make cluster · make knowledge
- Verify before done: make check

## Style
American spellings, no em-dashes. No secrets in config; only .env.example is committed.
```

---

*Schema: [`../../contract/DATA_CONTRACT.md`](../../contract/DATA_CONTRACT.md).*
