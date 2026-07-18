// Canonical schema DDL from DATA_CONTRACT.md Section 4. Idempotent. Applied by `make schema`.

CREATE CONSTRAINT dish_id      IF NOT EXISTS FOR (d:Dish)          REQUIRE d.dish_id IS UNIQUE;
CREATE CONSTRAINT recipe_id    IF NOT EXISTS FOR (r:Recipe)        REQUIRE r.recipe_id IS UNIQUE;
CREATE CONSTRAINT variant_id   IF NOT EXISTS FOR (v:RecipeVariant) REQUIRE v.variant_id IS UNIQUE;
CREATE CONSTRAINT food_id      IF NOT EXISTS FOR (f:Food)          REQUIRE f.fdc_id IS UNIQUE;
CREATE CONSTRAINT nutrient_id  IF NOT EXISTS FOR (n:Nutrient)      REQUIRE n.nutrient_id IS UNIQUE;
CREATE CONSTRAINT compound_id  IF NOT EXISTS FOR (c:Compound)      REQUIRE c.compound_id IS UNIQUE;
CREATE CONSTRAINT rule_id      IF NOT EXISTS FOR (dr:DietaryRule)  REQUIRE dr.rule_id IS UNIQUE;
// prep_id is unique per (recipe, food); without this MERGE (:Preparation {prep_id}) full-scans,
// which is O(n^2) at corpus scale (the bulk-load and ingest both MERGE a preparation per ingredient).
CREATE CONSTRAINT prep_id      IF NOT EXISTS FOR (p:Preparation)   REQUIRE p.prep_id IS UNIQUE;

CREATE INDEX variant_glycemic IF NOT EXISTS FOR (v:RecipeVariant) ON (v.glycemic_load);
CREATE INDEX variant_fluid    IF NOT EXISTS FOR (v:RecipeVariant) ON (v.fluid_ml);

// full-text index on food descriptions, for resolving recipe ingredients against the locally
// imported :Food graph (NutriScrape fdc-import + ingest local resolver) without an FDC API call.
CREATE FULLTEXT INDEX food_fulltext IF NOT EXISTS FOR (f:Food) ON EACH [f.description];

// full-text index on dish names, for NECTAR's recipe browser (name lookup over ~1M dishes without a
// full-corpus CONTAINS scan; the browser then refines the bounded candidate pool by nutrient ceilings).
CREATE FULLTEXT INDEX dish_name IF NOT EXISTS FOR (d:Dish) ON EACH [d.canonical_name];

CREATE VECTOR INDEX recipe_embed IF NOT EXISTS
FOR (r:Recipe) ON (r.embedding)
OPTIONS { indexConfig: { `vector.dimensions`: 384, `vector.similarity_function`: 'cosine' } };

CREATE VECTOR INDEX guideline_embed IF NOT EXISTS
FOR (g:Guideline) ON (g.embedding)
OPTIONS { indexConfig: { `vector.dimensions`: 384, `vector.similarity_function`: 'cosine' } };
