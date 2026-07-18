import { useState } from 'react';
import { api, ApiError } from '../api';
import { RecipeView } from './RecipeView';
import { fmt } from '../nutrients';
import type { BrowseDish, DerivedConstraint, NutrientInfo, RecipeDetail } from '../types';

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

  const hasPatientLimits = FILTERS.some((f) => patientCeiling(confirmed, f.id) != null);

  const applyPatientLimits = (): void => {
    const next: Record<string, string> = {};
    for (const f of FILTERS) {
      const v = patientCeiling(confirmed, f.id);
      if (v != null) next[f.id] = String(Math.round(v));
    }
    setCeil(next);
  };

  const numericCeilings = (): Record<string, number> => {
    const out: Record<string, number> = {};
    for (const [k, v] of Object.entries(ceil)) {
      const n = Number(v);
      if (v.trim() !== '' && Number.isFinite(n)) out[k] = n;
    }
    return out;
  };

  const search = async (): Promise<void> => {
    if (q.trim() === '') return;
    setLoading(true);
    setError(null);
    setOpenDish(null);
    setRecipe(null);
    try {
      setResults(await api.browseDishes(q.trim(), numericCeilings(), sort));
      setSearched(true);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setLoading(false);
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
        Browse the {`${(1031099).toLocaleString()}`}-dish corpus for meal ideas that meet a patient's
        needs. Search by name, then cap the per-serving nutrients that matter for this patient. A dish
        qualifies when at least one of its versions is at or below every cap. Values are the version
        spread, calculated not measured.
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
            {FILTERS.map((f) => (
              <option key={f.id} value={f.id}>
                Lowest {f.label.toLowerCase()}
              </option>
            ))}
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
                  {recipe && <RecipeView recipe={recipe} />}
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
