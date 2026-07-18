// TypeScript mirror of the NECTAR API wire contract (nectar/src/nectar/api/schemas.py).
// These shapes are the JSON the API sends and expects; keep them in sync with schemas.py.

export type Direction = 'avoid' | 'limit' | 'target' | 'maintain' | 'prefer';
export type Sex = 'M' | 'F';
export type ActivityLevel = 'sedentary' | 'light' | 'moderate' | 'active';

// --- Patient abstraction (abstraction/derive.py, confirm.py) ---

export interface ClinicalSnapshot {
  pmh: string[];
  metabolic_panel: Record<string, number>;
  cbc: Record<string, number>;
  medications: string[];
  allergies: string[];
  age: number;
  sex: Sex;
  weight_kg: number;
  height_cm: number;
  activity_level: ActivityLevel;
  goal: string;
}

export interface DerivedConstraint {
  source_signal: string;
  direction: Direction;
  target: string;
  severity: string;
  value: number | null;
  unit: string | null;
  formula: string | null;
  guideline_id: string | null;
  confirmed: boolean;
}

export interface ReviewItem {
  index: number;
  source_signal: string;
  target: string;
  direction: string;
  severity: string;
  value: number | null;
  unit: string | null;
  formula: string | null;
}

export interface DeriveResponse {
  constraints: DerivedConstraint[];
  review_items: ReviewItem[];
}

export interface ConfirmResponse {
  confirmed: DerivedConstraint[];
}

// --- Catalog lookups (common/contract_client.py) ---

export interface DishSummary {
  dish_id: string;
  canonical_name: string | null;
}

export interface DishStat {
  nutrient: string;
  minimum: number | null;
  median: number | null;
  maximum: number | null;
  count: number | null;
}

export interface BrowseDish {
  dish_id: string;
  canonical_name: string | null;
  stats: DishStat[];
}

export interface Condition {
  condition_id: string;
  name: string | null;
}

export interface Guideline {
  guideline_id: string;
  org: string | null;
  title: string | null;
  year: number | null;
  chunk: string | null;
}

export interface NutrientInfo {
  nutrient_id: string;
  name: string | null;
  unit: string | null;
}

export interface Ingredient {
  food: string | null;
  amount: number | null;
  method: string | null;
  cut_class: string | null;
}

export interface RecipeDetail {
  recipe_id: string;
  title: string | null;
  servings: number | null;
  source_id: string | null;
  license: string | null;
  serving_mass_g: number | null;
  energy_kcal: number | null;
  fluid_ml: number | null;
  ingredients: Ingredient[];
}

// --- Recommendation (engine/*, present/disclaimer.py) ---

export interface NutrientValue {
  nutrient: string;
  value: number;
  measured: boolean;
  disclaimer: string;
}

export interface Evaluation {
  variant_id: string;
  dish_id: string;
  admissible: boolean;
  score: number;
  contraindicated: boolean;
  reasons: string[];
  nutrients: NutrientValue[];
}

export interface DishNutrientStat {
  nutrient: string;
  unit: string;
  count: number;
  minimum: number;
  maximum: number;
  mean: number;
  median: number;
  stdev: number;
}

export interface DishRanking {
  dish_id: string;
  best: Evaluation | null;
  versions: Evaluation[];
  nutrient_stats: Record<string, DishNutrientStat>;
}

export interface ConflictNote {
  nutrient: string;
  kind: string;
  resolution: string;
  winning_rule: string;
  guideline_ids: string[];
}

export interface RecommendResponse {
  rankings: DishRanking[];
  conflicts: ConflictNote[];
  gaps: string[];
  boundary: string;
}

// --- Meal plan (plan/mealplan.py, /plan/week) ---

export interface Meal {
  variant_id: string;
  dish_id: string;
  nutrients: Record<string, number>;
}

export interface MaintainRule {
  nutrient: string;
  band: number;
}

export interface PlanRequest {
  pool: Meal[];
  energy_min: number;
  energy_max: number;
  fluid_max_ml: number | null;
  protein_min: number | null;
  maintain: MaintainRule[];
  days: number;
  meals_per_day: number;
}

export interface DayPlan {
  meals: Meal[];
  totals: Record<string, number>;
}

export interface PlanResponse {
  days: DayPlan[];
  violations: string[];
  boundary: string;
}

// --- Interaction (interact/qa.py, explain.py) ---

export interface AskRequest {
  request: string;
  allowed_citations: string[];
  allowed_dishes: string[];
  ranking_summary: string;
}

export interface AskResponse {
  intent: string;
  dishes: string[];
  exclude: string[];
  free_text: string;
  narration: string;
}

// --- Runtime settings (common/runtime_settings.py) ---

export type Backend = 'ollama' | 'anthropic' | 'openai';
export type UnitSystem = 'us' | 'metric';
export type TempScale = 'F' | 'C';

export interface Settings {
  backend: string;
  base_url: string;
  generation_model: string;
  temperature: number;
  context_window: number;
  embedding_model: string;
  unit_system: string;
  temp_scale: string;
  overridden: string[];
}

export interface SettingsUpdate {
  backend?: Backend;
  base_url?: string;
  generation_model?: string;
  temperature?: number;
  context_window?: number;
  embedding_model?: string;
  unit_system?: UnitSystem;
  temp_scale?: TempScale;
}
