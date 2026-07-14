# NECTAR Platform Data Contract

**The shared interface between NutriScrape and NECTAR**

Version 1.0 · Author: Ronald Rodriguez, MD, PhD · UT Health San Antonio
Status: Draft for review

> This is the single source of truth for the Neo4j hybrid (graph + vector) schema, the knowledge-base structures, the confidence and provenance conventions, and the one write-back path. NutriScrape writes this schema. NECTAR reads it. Neither program redefines it. Changes here are versioned (Section 9) and ripple to both programs by design.

---

## 0. Why a standalone contract

NutriScrape and NECTAR are built and versioned independently. The only thing they share is the database. If the schema lived inside either program, the other would depend on a moving internal detail. Pulling it out means both programs depend on a named version of this document, and either can change internally without breaking the other as long as the contract holds.

**The dependency direction is fixed.** NutriScrape produces patient-independent facts and knowledge. NECTAR composes them per patient. NECTAR writes back only through the single gated path in Section 8. No other mutation of the shared graph by NECTAR is permitted.

---

## 1. Conventions

### 1.1 Every derived value carries metadata

Any value that was computed, estimated, matched, or extracted (not read verbatim from an authoritative source) MUST carry:

| Field | Meaning |
|---|---|
| `source` | Origin: FDC id, dataset id, guideline id, transform id, or `estimated` |
| `confidence` | 0..1, calibrated |
| `evidence_tier` | `A` measured, `B` mechanistic/indirect, `C` hypothesis (where applicable) |
| `computed_by` | Pipeline stage or model id + version |
| `contract_version` | Version of this document the value was written under |

`confidence` propagates downstream: a value derived from low-confidence inputs cannot have higher confidence than its inputs.

### 1.2 Canonical units [INVARIANT]

The graph stores one canonical unit per quantity. Mass in grams, volume in milliliters, energy in kcal, temperature in degrees Celsius, all nutrient amounts on a per-serving basis. User-facing unit systems (US/metric, F/C) are a presentation concern in NECTAR and never change what is stored.

### 1.3 Evidence tiers [INVARIANT]

`A` and `B` may reach a patient. `C` is research-only and MUST NOT surface as a patient recommendation or remediation. Promotion between tiers happens only through Section 8.

---

## 2. Node Labels

### 2.1 Food and recipe side (recipe-intrinsic, patient-independent)

| Label | Represents | Key properties |
|---|---|---|
| `:Dish` | Abstract dish concept | dish_id, canonical_name, cluster_confidence |
| `:Recipe` | One authored version | recipe_id, title, source_id, license, servings, confidence |
| `:RecipeVariant` | A (recipe, preparation) evaluation unit | variant_id, is_as_authored, confidence |
| `:Food` | Canonical FDC food | fdc_id, description, data_type, source_tier |
| `:Nutrient` | Speciated nutrient | nutrient_id, name, unit, form |
| `:Compound` | Bioactive or process compound | compound_id, name, class |
| `:FoodAttribute` | Attribute, allergen, or provenance tag | attribute_id, name, family |
| `:Preparation` | Method + cut + parameters | prep_id, method, cut_class, sa_v_mult, water_ratio, liquid_retained_frac, time_min, temp_c |
| `:Method` | Reference cooking method | method_id, name |

`form` on `:Nutrient` speciates totals: fat as saturated/mono/poly/trans/EPA+DHA, sugar as added/intrinsic, fiber as soluble/insoluble/fermentable, sodium and potassium as intrinsic/additive, plus named amino acids where clinically relevant (phenylalanine).

### 2.2 Clinical knowledge side (patient-independent reference knowledge)

| Label | Represents | Key properties |
|---|---|---|
| `:Condition` | A disease / PMH factor | condition_id, name, icd10 |
| `:Medication` | A drug factor | medication_id, name, rxnorm |
| `:Goal` | A nutritional goal factor | goal_id, name |
| `:Allergy` | An allergy / intolerance factor | allergy_id, name |
| `:PhysiologicState` | A derived state | state_id, name |
| `:DietaryRule` | A reified constraint | rule_id, direction, severity, threshold, unit, safety_critical, basis |
| `:InterventionClass` | A remediation mechanism class | class_id, name, mechanism |
| `:HypothesisTransform` | A Tier C research hypothesis | hyp_id, protocol, predicted_direction, status |
| `:Guideline` | An embedded guideline passage | guideline_id, org, title, year, chunk, embedding |

`direction` on `:DietaryRule` is one of `avoid | limit | target | maintain | prefer`. `severity` is one of `absolute | strong | moderate | soft`. `maintain` rules are plan-level, not single-recipe (see Section 6.3).

---

## 3. Relationships

### 3.1 Recipe composition and computed facts

```
(:Dish)-[:HAS_VERSION]->(:Recipe)
(:Recipe)-[:CONTAINS {raw_mass_g, prep_id}]->(:Food)
(:Recipe)-[:HAS_VARIANT]->(:RecipeVariant)
(:RecipeVariant)-[:USES]->(:Preparation)
(:RecipeVariant)-[:HAS_NUTRIENT {amount_per_serving, unit, source, confidence}]->(:Nutrient)
(:RecipeVariant)-[:HAS_COMPOUND {source, confidence}]->(:Compound)     // includes formation-created
(:RecipeVariant)-[:HAS_ATTRIBUTE {source, confidence}]->(:FoodAttribute) // prep-resolved (raw flips, etc.)
```

`:RecipeVariant` also carries `fluid_ml`, `texture_class`, `glycemic_load`, `serving_mass_g`, `energy_kcal` as properties. Every recipe has exactly one `is_as_authored = true` variant. Additional variants are generated selectively (see NutriScrape SDD). All variant facts are cooked, as-eaten values.

### 3.2 Food-level intrinsic facts and transforms

```
(:Food)-[:HAS_NUTRIENT_RAW {amount_per_100g, source, confidence}]->(:Nutrient)
(:Food)-[:CONTAINS_COMPOUND {source, confidence}]->(:Compound)
(:Food)-[:HAS_ATTRIBUTE {source, confidence}]->(:FoodAttribute)
(:Food|:FoodClass)-[:TRANSFORM {
    target,            // nutrient_id or compound_id
    channel,           // concentration | leaching | degradation | formation
    D, L_base, formation_rate,
    mechanism, source, confidence, evidence_tier
}]->(:Method)
```

The four channels compose per NutriScrape's nutrition model. `formation` adds a compound the raw food never carried (acrylamide, heterocyclic amines).

### 3.3 Clinical rules, interactions, evidence

```
(:Condition|:Medication|:Goal|:Allergy|:PhysiologicState)-[:IMPOSES]->(:DietaryRule)
(:DietaryRule)-[:ACTS_ON]->(:Nutrient|:Food|:FoodAttribute|:Compound)
(:DietaryRule)-[:EVIDENCED_BY]->(:Guideline)
(:Medication)-[:INTERACTS_WITH {mechanism, effect, severity, direction, threshold}]->(:Compound|:FoodAttribute|:Nutrient|:Food)
(:Guideline)-[:GOVERNS]->(:Condition)
```

Drug rules may be authored declaratively as `IMPOSES` edges, or derived from `INTERACTS_WITH` edges at composition time. Both resolve to `:DietaryRule` semantics.

### 3.4 Remediation and hypotheses

```
(:Nutrient|:Compound)-[:ADDRESSED_BY]->(:InterventionClass)
(:InterventionClass)-[:IMPLEMENTED_BY]->(:Method|:HypothesisTransform)
(:HypothesisTransform)-[:TARGETS]->(:Nutrient|:Compound)
```

`ADDRESSED_BY` links a failing target's mechanism to the intervention classes that address it, which is how the remediation engine proposes techniques from mechanism rather than a lookup.

---

## 4. Indexes and Constraints

```cypher
CREATE CONSTRAINT dish_id     IF NOT EXISTS FOR (d:Dish)         REQUIRE d.dish_id IS UNIQUE;
CREATE CONSTRAINT recipe_id   IF NOT EXISTS FOR (r:Recipe)       REQUIRE r.recipe_id IS UNIQUE;
CREATE CONSTRAINT variant_id  IF NOT EXISTS FOR (v:RecipeVariant) REQUIRE v.variant_id IS UNIQUE;
CREATE CONSTRAINT food_id     IF NOT EXISTS FOR (f:Food)         REQUIRE f.fdc_id IS UNIQUE;
CREATE CONSTRAINT nutrient_id IF NOT EXISTS FOR (n:Nutrient)     REQUIRE n.nutrient_id IS UNIQUE;
CREATE CONSTRAINT compound_id IF NOT EXISTS FOR (c:Compound)     REQUIRE c.compound_id IS UNIQUE;
CREATE CONSTRAINT rule_id     IF NOT EXISTS FOR (dr:DietaryRule) REQUIRE dr.rule_id IS UNIQUE;

// range indexes for Stage 1 hard filters and Stage 2 scoring
CREATE INDEX variant_glycemic IF NOT EXISTS FOR (v:RecipeVariant) ON (v.glycemic_load);
CREATE INDEX variant_fluid    IF NOT EXISTS FOR (v:RecipeVariant) ON (v.fluid_ml);

// vector indexes (dimension is model-dependent; 384 shown)
CREATE VECTOR INDEX recipe_embed IF NOT EXISTS
FOR (r:Recipe) ON (r.embedding)
OPTIONS { indexConfig: { `vector.dimensions`: 384, `vector.similarity_function`: 'cosine' } };

CREATE VECTOR INDEX guideline_embed IF NOT EXISTS
FOR (g:Guideline) ON (g.embedding)
OPTIONS { indexConfig: { `vector.dimensions`: 384, `vector.similarity_function`: 'cosine' } };
```

---

## 5. What NutriScrape Guarantees to Write

NECTAR may assume the following are present and current for any dish it queries:

- Every `:Dish` has at least one `:Recipe` with an `is_as_authored` `:RecipeVariant` carrying a full cooked per-serving nutrient vector, attribute set, compound set, `fluid_ml`, `texture_class`, `glycemic_load`, and `serving_mass_g`.
- Every fact carries the Section 1.1 metadata.
- The clinical knowledge bases (rules, interactions, transforms, intervention classes, guidelines) are loaded and internally consistent.
- Dish-level statistics (nutrient distributions across versions) are materialized on the `:Dish` node.

NutriScrape does NOT compute anything patient-specific. There are no patient nodes and no suitability verdicts in the shared graph.

---

## 6. What NECTAR Reads and Composes (never writes, except Section 8)

### 6.1 Facts NECTAR consumes
Recipe-variant nutrient vectors, attribute sets, compound sets, fluid, texture, glycemic load, serving mass; the rule and interaction knowledge base; transforms; intervention classes; guideline passages and vector indexes.

### 6.2 What NECTAR computes at query time (transient, not persisted)
The resolved patient constraint set, Stage 1 / Stage 2 evaluation, dish and version rankings, remediation proposals, meal plans, explanations. None of this is written to the shared graph.

### 6.3 Plan-level rules
`maintain`-direction rules (warfarin vitamin K consistency, daily fluid and energy totals) are evaluated by NECTAR across a meal plan window, not against a single `:RecipeVariant`. The contract exposes the per-variant facts needed; the windowed evaluation is NECTAR's.

---

## 7. Confidence and the Calculated-Not-Measured Boundary [INVARIANT]

Every nutrient value in the graph is calculated, not laboratory-measured, unless its `source` is an explicit measurement record. NECTAR MUST surface this to the clinician on every displayed value. The contract carries the `confidence` and `source` that make that disclaimer specific rather than generic.

---

## 8. The Write-Back Path (the only NECTAR mutation) [INVARIANT]

NECTAR's research module is the sole writer of one thing: verification of preparation data that promotes evidence tiers.

**Flow.** A lab or clinician submits measured preparation data for a `:TRANSFORM` or `:HypothesisTransform`. The submission is a structured record (measurement, assay, n, method, submitter). A promotion service, not NECTAR directly, validates it and updates `evidence_tier` and `status` under a named-reviewer gate, writing an audit record.

**Rules.**
- No tier promotion without a linked measurement record and a named reviewer.
- `C -> B` or `B -> A` only. No skipping, no automated promotion.
- Every promotion writes an immutable audit entry (who, when, evidence id, prior tier, new tier).
- NECTAR cannot write nodes, recipe facts, rules, or interactions through this or any path. Only tier and status on transform-family nodes, via the gated service.

This is what closes the proposed-to-verified loop while keeping the clinical surface read-only for everything else.

---

## 9. Contract Versioning

- This document carries a semantic version. Both programs pin a minimum contract version.
- Additive changes (new optional property, new node type) bump the minor version and do not break consumers.
- Any change to an existing property's meaning, unit, or a relationship's semantics bumps the major version and requires coordinated release of both programs.
- Every written value records the `contract_version` it was produced under, so a migration can find and reprocess stale facts.

---

*This contract is depended on by `nutriscrape/docs/SDD.md` and `nectar/docs/SDD.md`. Implementation shape is in the respective PDDs.*
