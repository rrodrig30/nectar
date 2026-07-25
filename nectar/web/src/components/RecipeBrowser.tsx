import { useEffect, useState } from 'react';
import { api, ApiError } from '../api';
import { RecipeView } from './RecipeView';
import { fmt } from '../nutrients';
import type {
  BrowseDish,
  Condition,
  ConditionRule,
  DerivedConstraint,
  NutrientInfo,
  RecipeDetail,
} from '../types';

// Readable names for the knowledge base's condition ids (the :Condition nodes carry no name yet).
const CONDITION_LABELS: Record<string, string> = {
  ckd: 'Chronic kidney disease (CKD)',
  htn: 'High blood pressure (hypertension)',
  cad: 'Heart disease (coronary artery)',
  t2dm: 'Type 2 diabetes',
  transplant: 'Organ transplant',
  oxalate_stones: 'Oxalate kidney stones',
};
const conditionLabel = (c: Condition): string =>
  c.name ?? CONDITION_LABELS[c.condition_id] ?? c.condition_id;

// How firm a rule is, so the browser sorts by the firmest per-serving limit.
const SEVERITY_RANK: Record<string, number> = { absolute: 4, strong: 3, moderate: 2, soft: 1 };

// A condition's rules that cap a nutrient (a ceiling to stay at or below). `target`/`prefer` rules
// (aim for MORE, e.g. fiber, or HTN potassium) are shown as guidance, not applied as a cap, because
// the browser filters on ceilings only.
function limitRules(rules: ConditionRule[]): ConditionRule[] {
  return rules.filter(
    (r) => (r.direction === 'limit' || r.direction === 'avoid') && r.threshold != null,
  );
}
function targetRules(rules: ConditionRule[]): ConditionRule[] {
  return rules.filter(
    (r) => (r.direction === 'target' || r.direction === 'prefer') && r.threshold != null,
  );
}

// The clinically-actionable ceilings a physician browses by: renal electrolytes (potassium,
// phosphorus), the HTN sodium limit, and the weight-goal energy cap. Each is a per-serving max; a
// dish qualifies when at least one of its versions is at or below it.
const FILTERS: { id: string; label: string; unit: string; placeholder: string }[] = [
  { id: 'potassium', label: 'Potassium', unit: 'mg', placeholder: 'e.g. 400' },
  { id: 'sodium', label: 'Sodium', unit: 'mg', placeholder: 'e.g. 600' },
  { id: 'phosphorus', label: 'Phosphorus', unit: 'mg', placeholder: 'e.g. 250' },
  { id: 'energy', label: 'Energy', unit: 'kcal', placeholder: 'e.g. 500' },
];

interface Props {
  vocab: Map<string, NutrientInfo>;
  confirmed: DerivedConstraint[];
}

// A dish's per-nutrient stat, or undefined if the dish carries no distribution for it.
function statFor(dish: BrowseDish, nutrient: string): BrowseDish['stats'][number] | undefined {
  return dish.stats.find((s) => s.nutrient === nutrient);
}

// Pull a per-serving ceiling for `nutrient` out of the confirmed constraints (a limit/avoid/target
// with a numeric value), so "apply patient limits" seeds the browser from the abstraction layer.
function patientCeiling(confirmed: DerivedConstraint[], nutrient: string): number | null {
  for (const c of confirmed) {
    if (c.target === nutrient && c.value != null && ['limit', 'avoid', 'target'].includes(c.direction)) {
      return c.value;
    }
  }
  return null;
}

export function RecipeBrowser({ vocab, confirmed }: Props): JSX.Element {
  const [q, setQ] = useState('');
  const [ceil, setCeil] = useState<Record<string, string>>({});
  const [sort, setSort] = useState('');
  const [results, setResults] = useState<BrowseDish[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [searched, setSearched] = useState(false);
  const [openDish, setOpenDish] = useState<string | null>(null);
  const [recipe, setRecipe] = useState<RecipeDetail | null>(null);
  const [recipeErr, setRecipeErr] = useState<string | null>(null);
  const [conditions, setConditions] = useState<Condition[]>([]);
  const [condition, setCondition] = useState('');
  const [conditionRules, setConditionRules] = useState<ConditionRule[]>([]);

  // The conditions the knowledge base can filter for.
  useEffect(() => {
    let live = true;
    api.conditions().then((cs) => { if (live) setConditions(cs); }).catch(() => {});
    return () => { live = false; };
  }, []);

  const hasPatientLimits = FILTERS.some((f) => patientCeiling(confirmed, f.id) != null);

  const applyPatientLimits = (): void => {
    const next: Record<string, string> = {};
    for (const f of FILTERS) {
      const v = patientCeiling(confirmed, f.id);
      if (v != null) next[f.id] = String(Math.round(v));
    }
    setCeil(next);
  };

  // Merge a condition's per-serving ceilings with the manual caps (manual wins). Applies EVERY
  // limited nutrient the condition names, not only the four shown as inputs.
  const numericCeilings = (rules: ConditionRule[], manual: Record<string, string>): Record<string, number> => {
    const out: Record<string, number> = {};
    for (const r of limitRules(rules)) {
      if (r.threshold != null) out[r.nutrient] = Math.min(out[r.nutrient] ?? Infinity, r.threshold);
    }
    for (const [k, v] of Object.entries(manual)) {
      const n = Number(v);
      if (v.trim() !== '' && Number.isFinite(n)) out[k] = n;
    }
    return out;
  };

  const runSearch = async (
    rules: ConditionRule[], manual: Record<string, string>, sortBy: string,
  ): Promise<void> => {
    if (q.trim() === '') return;
    setLoading(true);
    setError(null);
    setOpenDish(null);
    setRecipe(null);
    try {
      setResults(await api.browseDishes(q.trim(), numericCeilings(rules, manual), sortBy));
      setSearched(true);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  };

  const search = (): Promise<void> => runSearch(conditionRules, ceil, sort);

  // Pick a health condition: pull its dietary rules, fill the shown caps + sort by the firmest
  // limit, and re-run the search so results are filtered and sorted for that condition.
  const selectCondition = async (id: string): Promise<void> => {
    setCondition(id);
    if (id === '') {
      setConditionRules([]);
      void runSearch([], ceil, sort);
      return;
    }
    try {
      const rules = await api.conditionRules(id);
      setConditionRules(rules);
      const limits = limitRules(rules);
      const nextCeil: Record<string, string> = { ...ceil };
      for (const f of FILTERS) {
        const r = limits.find((x) => x.nutrient === f.id);
        if (r && r.threshold != null) nextCeil[f.id] = String(Math.round(r.threshold));
      }
      setCeil(nextCeil);
      const firmest = [...limits].sort(
        (a, b) => (SEVERITY_RANK[b.severity ?? ''] ?? 0) - (SEVERITY_RANK[a.severity ?? ''] ?? 0),
      )[0];
      const nextSort = firmest ? firmest.nutrient : sort;
      setSort(nextSort);
      void runSearch(rules, nextCeil, nextSort);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    }
  };

  const toggleRecipe = async (dishId: string): Promise<void> => {
    if (openDish === dishId) {
      setOpenDish(null);
      return;
    }
    setOpenDish(dishId);
    setRecipe(null);
    setRecipeErr(null);
    try {
      setRecipe(await api.recipe(dishId));
    } catch (e) {
      setRecipeErr(e instanceof ApiError ? e.message : String(e));
    }
  };

  const unitFor = (nutrient: string): string =>
    FILTERS.find((f) => f.id === nutrient)?.unit ?? vocab.get(nutrient)?.unit ?? '';
  const label = (nutrient: string): string => vocab.get(nutrient)?.name ?? nutrient;

  return (
    <div className="card">
      <div className="card-title-row">
        <h2>Recipe browser</h2>
        {hasPatientLimits && (
          <button className="btn-ghost btn-sm" onClick={applyPatientLimits}>
            Apply patient limits
          </button>
        )}
      </div>
      <p className="card-hint">
        Browse the corpus for meal ideas that meet a patient's needs. Search by name, then pick a
        health condition to apply its dietary limits (or set the per-serving caps manually). A dish
        qualifies when at least one of its versions is at or below every cap; results sort by the
        firmest limit. Values are the version spread, calculated not measured, and this is an
        exploratory aid &mdash; the full personalized recommendation is the Compose flow.
      </p>

      <div className="field">
        <label>Dish or ingredient</label>
        <div className="browse-search">
          <input
            value={q}
            placeholder="e.g. chicken soup, lentil stew, roasted vegetables"
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') void search();
            }}
          />
          <button className="btn-primary" onClick={() => void search()} disabled={loading || q.trim() === ''}>
            {loading ? 'Searching…' : 'Search'}
          </button>
        </div>
      </div>

      <div className="field">
        <label>Filter for a health condition</label>
        <select value={condition} onChange={(e) => void selectCondition(e.target.value)}>
          <option value="">None &mdash; set caps manually below</option>
          {conditions.map((c) => (
            <option key={c.condition_id} value={c.condition_id}>
              {conditionLabel(c)}
            </option>
          ))}
        </select>
      </div>

      {condition && conditionRules.length > 0 && (
        <div className="condition-rules">
          <span className="cr-label">Applied limits per serving:</span>
          {limitRules(conditionRules).map((r) => (
            <span className="cr-chip limit" key={`l-${r.nutrient}`}>
              {label(r.nutrient)} &le; {r.threshold != null ? fmt(r.threshold) : ''} {r.unit}
            </span>
          ))}
          {targetRules(conditionRules).length > 0 && (
            <>
              <span className="cr-label cr-target">Also aim for:</span>
              {targetRules(conditionRules).map((r) => (
                <span className="cr-chip target" key={`t-${r.nutrient}`}>
                  {label(r.nutrient)} &ge; {r.threshold != null ? fmt(r.threshold) : ''} {r.unit}
                </span>
              ))}
            </>
          )}
        </div>
      )}

      <div className="grid browse-filters">
        {FILTERS.map((f) => (
          <div className="field" key={f.id}>
            <label>
              Max {f.label} ({f.unit})
            </label>
            <input
              inputMode="decimal"
              placeholder={f.placeholder}
              value={ceil[f.id] ?? ''}
              onChange={(e) => setCeil((prev) => ({ ...prev, [f.id]: e.target.value }))}
            />
          </div>
        ))}
        <div className="field">
          <label>Sort by</label>
          <select value={sort} onChange={(e) => setSort(e.target.value)}>
            <option value="">Name relevance</option>
            {[...new Set([...FILTERS.map((f) => f.id), ...limitRules(conditionRules).map((r) => r.nutrient)])].map(
              (id) => (
                <option key={id} value={id}>
                  Lowest {label(id).toLowerCase()}
                </option>
              ),
            )}
          </select>
        </div>
      </div>

      {error && <div className="notice err">{error}</div>}

      {searched && !loading && results.length === 0 && !error && (
        <p className="muted browse-empty">
          No dishes match that name within the selected caps. Try a broader name or relax a cap.
        </p>
      )}

      {results.length > 0 && (
        <ul className="browse-results">
          {results.map((d) => (
            <li key={d.dish_id} className="browse-row">
              <div className="browse-row-head">
                <span className="browse-name">{d.canonical_name ?? d.dish_id}</span>
                <div className="browse-stats">
                  {FILTERS.map((f) => {
                    const s = statFor(d, f.id);
                    if (!s || s.minimum == null || s.maximum == null) return null;
                    return (
                      <span className="browse-stat" key={f.id} title={`${f.label} across versions`}>
                        <span className="bs-label">{f.label.slice(0, 4)}</span>
                        {s.minimum === s.maximum
                          ? fmt(s.minimum)
                          : `${fmt(s.minimum)}–${fmt(s.maximum)}`}
                        <span className="bs-unit">{unitFor(f.id)}</span>
                      </span>
                    );
                  })}
                </div>
                <button className="btn-ghost btn-sm" onClick={() => void toggleRecipe(d.dish_id)}>
                  {openDish === d.dish_id ? 'Hide recipe' : 'View recipe'}
                </button>
              </div>
              {openDish === d.dish_id && (
                <div className="browse-recipe">
                  {recipeErr && <div className="notice err">{recipeErr}</div>}
                  {!recipe && !recipeErr && <p className="spinner">Loading recipe…</p>}
                  {recipe && <RecipeView recipe={recipe} vocab={vocab} />}
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
