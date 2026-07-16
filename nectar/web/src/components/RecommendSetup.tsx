import { useEffect, useState } from 'react';
import { api, ApiError } from '../api';
import type { Condition, DishSummary } from '../types';

interface Props {
  confirmedCount: number;
  onRecommend: (conditionIds: string[], dishIds: string[]) => void;
  onBack: () => void;
  loading: boolean;
}

// Assembles the two remaining inputs to /recommend: which conditions to score against (their
// nutrient rules are pulled from the graph) and which dishes to evaluate (found by name search).
export function RecommendSetup({ confirmedCount, onRecommend, onBack, loading }: Props): JSX.Element {
  const [conditions, setConditions] = useState<Condition[]>([]);
  const [selectedConditions, setSelectedConditions] = useState<Set<string>>(new Set());

  const [query, setQuery] = useState('');
  const [results, setResults] = useState<DishSummary[]>([]);
  const [searching, setSearching] = useState(false);
  const [searchErr, setSearchErr] = useState<string | null>(null);
  const [selectedDishes, setSelectedDishes] = useState<DishSummary[]>([]);

  useEffect(() => {
    let live = true;
    api
      .conditions()
      .then((c) => { if (live) setConditions(c); })
      .catch(() => { /* selector simply stays empty if the lookup fails */ });
    return () => { live = false; };
  }, []);

  const toggleCondition = (id: string): void =>
    setSelectedConditions((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });

  const search = async (): Promise<void> => {
    const q = query.trim();
    if (!q) return;
    setSearching(true);
    setSearchErr(null);
    try {
      setResults(await api.searchDishes(q, 25));
    } catch (e) {
      setSearchErr(e instanceof ApiError ? e.message : String(e));
    } finally {
      setSearching(false);
    }
  };

  const addDish = (d: DishSummary): void => {
    setSelectedDishes((prev) => (prev.some((x) => x.dish_id === d.dish_id) ? prev : [...prev, d]));
  };

  const removeDish = (id: string): void =>
    setSelectedDishes((prev) => prev.filter((d) => d.dish_id !== id));

  const submit = (): void =>
    onRecommend([...selectedConditions], selectedDishes.map((d) => d.dish_id));

  return (
    <div className="card">
      <h2>3 &middot; Choose conditions and dishes</h2>
      <p className="card-hint">
        {confirmedCount} confirmed constraint{confirmedCount === 1 ? '' : 's'} will be applied.
        Conditions add their nutrient rules from the knowledge base; dishes are the corpus recipes
        to evaluate and rank for this patient.
      </p>

      <div className="field">
        <label>Conditions</label>
        {conditions.length === 0 ? (
          <p className="muted">No conditions loaded.</p>
        ) : (
          <div className="chips">
            {conditions.map((c) => {
              const on = selectedConditions.has(c.condition_id);
              return (
                <button
                  key={c.condition_id}
                  type="button"
                  className={on ? 'chip' : 'step-chip'}
                  onClick={() => toggleCondition(c.condition_id)}
                >
                  {on ? '✓ ' : ''}{c.name ?? c.condition_id}
                </button>
              );
            })}
          </div>
        )}
      </div>

      <div className="field">
        <label>Find dishes by name</label>
        <div style={{ display: 'flex', gap: '0.5rem' }}>
          <input
            value={query}
            placeholder="e.g. chicken soup, baked potato, lentil stew"
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') void search(); }}
          />
          <button className="btn-ghost" onClick={() => void search()} disabled={searching || !query.trim()}>
            {searching ? 'Searching…' : 'Search'}
          </button>
        </div>
        {searchErr && <div className="notice err">{searchErr}</div>}
        {results.length > 0 && (
          <div className="search-results">
            {results.map((d) => (
              <button key={d.dish_id} type="button" onClick={() => addDish(d)}>
                {d.canonical_name ?? d.dish_id}
              </button>
            ))}
          </div>
        )}
      </div>

      {selectedDishes.length > 0 && (
        <div className="field">
          <label>Selected dishes ({selectedDishes.length})</label>
          <div className="chips">
            {selectedDishes.map((d) => (
              <span key={d.dish_id} className="chip">
                {d.canonical_name ?? d.dish_id}
                <button type="button" onClick={() => removeDish(d.dish_id)} aria-label="remove">
                  &times;
                </button>
              </span>
            ))}
          </div>
        </div>
      )}

      <div className="btn-row">
        <button className="btn-ghost" onClick={onBack} disabled={loading}>
          Back
        </button>
        <button
          className="btn-primary"
          onClick={submit}
          disabled={loading || selectedDishes.length === 0}
        >
          {loading ? 'Evaluating…' : 'Get recommendations'}
        </button>
      </div>
    </div>
  );
}
