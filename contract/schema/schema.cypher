// Canonical schema DDL from DATA_CONTRACT.md Section 4. Idempotent. Applied by `make schema`.

CREATE CONSTRAINT dish_id      IF NOT EXISTS FOR (d:Dish)          REQUIRE d.dish_id IS UNIQUE;
CREATE CONSTRAINT recipe_id    IF NOT EXISTS FOR (r:Recipe)        REQUIRE r.recipe_id IS UNIQUE;
CREATE CONSTRAINT variant_id   IF NOT EXISTS FOR (v:RecipeVariant) REQUIRE v.variant_id IS UNIQUE;
CREATE CONSTRAINT food_id      IF NOT EXISTS FOR (f:Food)          REQUIRE f.fdc_id IS UNIQUE;
CREATE CONSTRAINT nutrient_id  IF NOT EXISTS FOR (n:Nutrient)      REQUIRE n.nutrient_id IS UNIQUE;
CREATE CONSTRAINT compound_id  IF NOT EXISTS FOR (c:Compound)      REQUIRE c.compound_id IS UNIQUE;
CREATE CONSTRAINT rule_id      IF NOT EXISTS FOR (dr:DietaryRule)  REQUIRE dr.rule_id IS UNIQUE;

CREATE INDEX variant_glycemic IF NOT EXISTS FOR (v:RecipeVariant) ON (v.glycemic_load);
CREATE INDEX variant_fluid    IF NOT EXISTS FOR (v:RecipeVariant) ON (v.fluid_ml);

// full-text index on food descriptions, for resolving recipe ingredients against the locally
// imported :Food graph (NutriScrape fdc-import + ingest local resolver) without an FDC API call.
CREATE FULLTEXT INDEX food_fulltext IF NOT EXISTS FOR (f:Food) ON EACH [f.description];

CREATE VECTOR INDEX recipe_embed IF NOT EXISTS
FOR (r:Recipe) ON (r.embedding)
OPTIONS { indexConfig: { `vector.dimensions`: 384, `vector.similarity_function`: 'cosine' } };

CREATE VECTOR INDEX guideline_embed IF NOT EXISTS
FOR (g:Guideline) ON (g.embedding)
OPTIONS { indexConfig: { `vector.dimensions`: 384, `vector.similarity_function`: 'cosine' } };
