# NutriScrape Software Design Document

**The data engine for the NECTAR platform**

Version 3.0 · Author: Ronald Rodriguez, MD, PhD · UT Health San Antonio
Status: Draft for review

> NutriScrape builds the Neo4j hybrid database. It has no interactive user. This document is architecture and rationale; the schema it writes is defined in [`../../contract/DATA_CONTRACT.md`](../../contract/DATA_CONTRACT.md) and is not repeated here. Implementation shape is in [`PDD.md`](./PDD.md).

---

## 1. Purpose and Scope

NutriScrape turns a raw recipe corpus and a set of reference sources into the patient-independent knowledge asset that NECTAR queries. It owns every fact that does not depend on a patient: recipe-intrinsic composition, the four-channel preparation transforms, dish clustering, and the curated clinical knowledge bases.

**In scope**: acquisition, two-tier LLM extraction, food resolution, canonical normalization, cooked-nutrition computation, dish clustering, knowledge-base curation, and loading all of it into the contract schema with confidence and provenance.

**Out of scope**: anything patient-specific. No patient nodes, no suitability scoring, no recommendation, no presentation. Those are NECTAR's.

---

## 2. Position in the Platform

NutriScrape is the write side of the platform. It runs as batch and incremental jobs, not as a service behind a request. Its output is the shared graph defined by the data contract. It reads external sources; it never reads a patient. The only thing that ever writes back into its knowledge bases is the gated verification path in Section 8 of the contract, operated by NECTAR's research module, not by NutriScrape.

---

## 3. Ingestion Pipeline

Staged, each stage idempotent and restartable, writing versioned facts rather than overwriting.

### 3.1 Acquisition
Source adapters over open datasets (RecipeNLG, Recipe1M+, public dumps) and schema.org structured metadata for permitted sites. License and provenance recorded per record. Source terms checked at configuration time.

### 3.2 Two-tier LLM extraction [INVARIANT: extraction only, never nutrient values]
The ingredient line and the preparation steps are parsed by a language model, because both are messy natural-language-to-structure problems. The preparation parser is on the critical path: it must link a later "drain" step to the ingredient it acts on, because that linkage sets `liquid_retained_frac`, which flips potassium between leached and retained.

Two tiers for cost at corpus scale. A small fine-tuned model handles the common case and emits a calibrated per-field confidence. Low-confidence extractions escalate to a larger model. The model produces structured fields (`mass_g`, `method`, `cut_class`, `liquid_retained_frac`, times, temperatures) and hands off. It never computes a nutrient number.

### 3.3 Food resolution
Candidate-and-rank match of each parsed food to a canonical FDC item. A language model may normalize the food string before lookup (the normalize-then-validate pattern); the match is still validated against FDC, and the model never asserts composition.

### 3.4 Canonical normalization
All quantities converted to the contract's canonical units (grams, milliliters, degrees Celsius, per-serving). This is the internal truth the math runs on and is distinct from NECTAR's user-facing unit toggle.

### 3.5 Cooked-nutrition computation
The core computation, applying the four-channel transform.

---

## 4. The Four-Channel Transform

Preparation is an operator on a food's intrinsic facts, not an annotation. The effective absolute amount of a nutrient under a preparation separates three reduction effects plus one addition:

```
effective = raw × D × (1 − L × (1 − kept_liquid))     (+ formation, for created compounds)

D           degradation survival (heat/oxygen lability)   — not recoverable
L           fraction leached to the cooking medium         — recoverable if liquid kept
kept_liquid fraction of cooking liquid retained            — mass balance
formation   compound created by the method (acrylamide, HCAs)
```

Leaching scales with the cut's surface-area-to-volume ratio, water ratio, time, and temperature, so cut geometry is a transform parameter. A boiled-and-drained cubed potato, a baked potato, and potato soup all fall out of the same formula with different `L`, `kept_liquid`, and mass balance. The coefficients live in the versioned `TRANSFORM` knowledge base in the contract, each with source, confidence, and evidence tier. The formation channel is in from the first version, so an avoid rule can fire on a method-created compound the raw food never had.

Each written value carries its transform provenance and a confidence, because most `(food × cut)` cells are estimates rather than measurements, and the confidence must say so.

---

## 5. Dish Clustering

The corpus already contains the preparation and proportion variants NECTAR needs to rank, scattered as independent recipes. Clustering recognizes them as versions of one dish.

A blocking-then-scoring pipeline, because two million recipes cannot be compared pairwise. Fingerprint each recipe by its resolved core FDC foods, rough proportions, and primary method. Block by shared core-ingredient signature. Score within a block on weighted ingredient overlap, proportion similarity, and method compatibility, with title-embedding similarity as a secondary signal. Cluster above threshold into a `:Dish`.

An embedding-and-blocking funnel does the bulk deterministically; the language model is promoted only for the near-threshold membership calls, where the granularity judgment (is a dairy-free version the same dish or a clinically distinct one) is worth the cost. Every cluster edge carries a membership confidence, and near-threshold cases go to review. Granularity favors the finer split, so a clinically distinct version is kept separate rather than averaged into a parent. Dish-level nutrient distributions are materialized on the `:Dish` node.

---

## 6. Knowledge-Base Curation

NutriScrape builds and maintains the patient-independent clinical knowledge bases the contract defines: factor-to-rule mappings, the food-drug interaction table, the four-channel transform coefficients, the intervention classes, and the guideline corpus. This is the slowest and most consequential part of the project, and it carries the medico-legal weight.

A language model drafts candidate entries with citations (a compound tag, a proposed interaction with mechanism), turning a blank-page problem into a review problem. Drafts flow into a review queue, never into live authority. Human confirmation with a named reviewer is required before an entry can influence anything a patient sees. This is the same governance the contract's write-back path enforces, applied to initial authoring.

---

## 7. Confidence and Provenance

Confidence is tracked from extraction through transform to the stored fact, and never increases downstream of a low-confidence input. Every value records the contract's metadata. Low-confidence recipes and unresolved foods feed a review queue whose corrections write to override tables that improve later runs.

---

## 8. Orchestration and Scale

Staged batch DAGs (Prefect or Airflow). Each stage horizontally parallel by recipe or by block. Clustering runs as a corpus-wide batch stage after ingestion, with an incremental mode that matches new recipes against existing dish fingerprints. Variant materialization is bounded: the as-authored variant is always computed; alternative preparation variants are generated selectively rather than as a full cross-product (see PDD).

---

## 9. Non-Functional Requirements

| Attribute | Requirement |
|---|---|
| Scale | Process millions of recipes in staged, restartable batch |
| Idempotency | Re-running a stage yields the same output for unchanged input |
| Reproducibility | Every fact traces to source, transform coefficients, model version, contract version |
| Cost | Two-tier extraction and reserved-LLM clustering keep model spend bounded |
| Contract fidelity | All writes conform to the pinned contract version |

---

## 10. Risks and Limitations

- Geometry-resolved transform coefficients are mostly estimates; USDA retention factors are method-level, not cut-level.
- Preparation parsing errors corrupt the exact nutrients (potassium, phosphorus) that matter most clinically; the parser needs its own confidence and golden tests.
- Clustering is never perfectly clean; membership confidence and review handle the boundary.
- Knowledge-base curation is a standing effort, not a one-time seed.

---

*Schema: [`../../contract/DATA_CONTRACT.md`](../../contract/DATA_CONTRACT.md). Implementation: [`PDD.md`](./PDD.md).*
