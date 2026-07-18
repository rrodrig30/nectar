import { useMemo, useState } from 'react';
import { api, ApiError } from '../api';
import { fmt } from '../nutrients';
import type {
  DerivedConstraint,
  Meal,
  NutrientInfo,
  PlanResponse,
  RecommendResponse,
} from '../types';

interface Props {
  result: RecommendResponse | null;
  confirmed: DerivedConstraint[];
  vocab: Map<string, NutrientInfo>;
  plan: PlanResponse | null;
  setPlan: (p: PlanResponse | null) => void;
  onGoCompose: () => void;
}

// Flatten the recommend result into an admissible meal pool the planner selects from: every
// non-contraindicated, admissible version, carrying its per-serving nutrient vector.
function poolFromResult(result: RecommendResponse | null): Meal[] {
  if (!result) return [];
  const pool: Meal[] = [];
  for (const ranking of result.rankings) {
    for (const v of ranking.versions) {
      if (!v.admissible || v.contraindicated) continue;
      const nutrients: Record<string, number> = {};
      for (const n of v.nutrients) nutrients[n.nutrient] = n.value;
      pool.push({ variant_id: v.variant_id, dish_id: v.dish_id, nutrients });
    }
  }
  return pool;
}

// A confirmed constraint's numeric value for a target and any of the given directions, or null. The
// energy/protein/fluid envelope is sourced from the abstraction layer, never hardcoded here.
function confirmedValue(
  confirmed: DerivedConstraint[],
  target: string,
  directions: string[],
): number | null {
  for (const c of confirmed) {
    if (c.target === target && c.value != null && directions.includes(c.direction)) return c.value;
  }
  return null;
}

export function MealPlanner({
  result,
  confirmed,
  vocab,
  plan,
  setPlan,
  onGoCompose,
}: Props): JSX.Element {
  const pool = useMemo(() => poolFromResult(result), [result]);

  // Envelope defaults sourced from the confirmed constraints; every field stays editable so the
  // clinician owns the plan window (the band around the derived daily energy target, etc.).
  const energyTarget = confirmedValue(confirmed, 'energy', ['target']);
  const proteinTarget = confirmedValue(confirmed, 'protein', ['target', 'limit']);
  const fluidLimit = confirmedValue(confirmed, 'fluid', ['limit', 'maintain']);
  const maintainRules = confirmed.filter((c) => c.direction === 'maintain' && c.target !== 'fluid');

  const [energyMin, setEnergyMin] = useState(energyTarget ? String(Math.round(energyTarget * 0.9)) : '');
  const [energyMax, setEnergyMax] = useState(energyTarget ? String(Math.round(energyTarget * 1.1)) : '');
  const [proteinMin, setProteinMin] = useState(proteinTarget ? String(Math.round(proteinTarget)) : '');
  const [fluidMax, setFluidMax] = useState(fluidLimit ? String(Math.round(fluidLimit)) : '');
  const [days, setDays] = useState('7');
  const [mealsPerDay, setMealsPerDay] = useState('3');

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [names, setNames] = useState<Map<string, string>>(new Map());

  const label = (nutrient: string): string => vocab.get(nutrient)?.name ?? nutrient;
  const unit = (nutrient: string): string => vocab.get(nutrient)?.unit ?? '';

  const generate = async (): Promise<void> => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.planWeek({
        pool,
        energy_min: Number(energyMin),
        energy_max: Number(energyMax),
        fluid_max_ml: fluidMax.trim() === '' ? null : Number(fluidMax),
        protein_min: proteinMin.trim() === '' ? null : Number(proteinMin),
        maintain: maintainRules.map((c) => ({ nutrient: c.target, band: c.value ?? 0 })),
        days: Number(days),
        meals_per_day: Number(mealsPerDay),
      });
      setPlan(res);
      // Fetch a readable title for each unique dish in the plan (a bounded set).
      const dishIds = [...new Set(res.days.flatMap((d) => d.meals.map((m) => m.dish_id)))];
      const entries = await Promise.all(
        dishIds.map(async (id): Promise<[string, string]> => {
          try {
            const r = await api.recipe(id);
            return [id, r.title ?? id];
          } catch {
            return [id, id];
          }
        }),
      );
      setNames(new Map(entries));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  };

  const envelopeValid = energyMin.trim() !== '' && energyMax.trim() !== '' && Number(energyMax) >= Number(energyMin);

  if (!result) {
    return (
      <div className="card">
        <h2>Meal planner</h2>
        <p className="card-hint">
          The weekly plan is a constrained selection across the dishes admissible for this patient.
          Run a recommendation first so the planner has an admissible meal pool to draw from.
        </p>
        <button className="btn-primary" onClick={onGoCompose}>
          Go to Compose
        </button>
      </div>
    );
  }

  return (
    <div className="card">
      <h2>Meal planner</h2>
      <p className="card-hint">
        A weekly plan drawn only from the <b>{pool.length}</b> admissible version
        {pool.length === 1 ? '' : 's'} in the current recommendation. Daily energy and protein
        envelopes and the plan-level maintain rules (e.g. vitamin K consistency) are evaluated across
        the week. Defaults come from the confirmed constraints and stay editable.
      </p>

      {pool.length === 0 && (
        <div className="notice warn">
          No admissible versions in the current recommendation, so there is nothing to plan. Adjust
          the constraints or dishes in Compose.
        </div>
      )}

      <div className="grid">
        <div className="field">
          <label>Daily energy min (kcal)</label>
          <input inputMode="numeric" value={energyMin} onChange={(e) => setEnergyMin(e.target.value)} />
        </div>
        <div className="field">
          <label>Daily energy max (kcal)</label>
          <input inputMode="numeric" value={energyMax} onChange={(e) => setEnergyMax(e.target.value)} />
        </div>
        <div className="field">
          <label>Daily protein min (g)</label>
          <input inputMode="numeric" value={proteinMin} onChange={(e) => setProteinMin(e.target.value)} placeholder="optional" />
        </div>
        <div className="field">
          <label>Daily fluid max (mL)</label>
          <input inputMode="numeric" value={fluidMax} onChange={(e) => setFluidMax(e.target.value)} placeholder="optional" />
        </div>
        <div className="field">
          <label>Days</label>
          <input inputMode="numeric" value={days} onChange={(e) => setDays(e.target.value)} />
        </div>
        <div className="field">
          <label>Meals per day</label>
          <input inputMode="numeric" value={mealsPerDay} onChange={(e) => setMealsPerDay(e.target.value)} />
        </div>
      </div>

      {maintainRules.length > 0 && (
        <p className="card-hint">
          Plan-level maintain rules applied:{' '}
          {maintainRules.map((c) => `${label(c.target)} (±${c.value ?? 0} ${unit(c.target)})`).join(', ')}.
        </p>
      )}

      <div className="btn-row">
        <button
          className="btn-primary"
          onClick={() => void generate()}
          disabled={loading || pool.length === 0 || !envelopeValid}
        >
          {loading ? 'Planning…' : 'Generate weekly plan'}
        </button>
      </div>

      {error && <div className="notice err">{error}</div>}

      {plan && (
        <div className="plan-out">
          {plan.violations.length > 0 && (
            <div className="notice warn">
              <b>Plan notes:</b>
              <ul>
                {plan.violations.map((v, i) => (
                  <li key={i}>{v}</li>
                ))}
              </ul>
            </div>
          )}
          <div className="plan-grid">
            {plan.days.map((day, i) => (
              <div className="plan-day" key={i}>
                <div className="plan-day-head">Day {i + 1}</div>
                <ul className="plan-meals">
                  {day.meals.map((m, j) => (
                    <li key={j}>{names.get(m.dish_id) ?? m.dish_id}</li>
                  ))}
                </ul>
                <div className="plan-totals">
                  {['energy', 'protein', 'sodium', 'potassium'].map((n) =>
                    day.totals[n] != null ? (
                      <span className="plan-total" key={n} title={label(n)}>
                        <span className="pt-label">{label(n).slice(0, 4)}</span>
                        {fmt(day.totals[n])}
                        <span className="pt-unit">{unit(n)}</span>
                      </span>
                    ) : null,
                  )}
                </div>
              </div>
            ))}
          </div>
          <p className="calc-note">{plan.boundary}</p>
        </div>
      )}
    </div>
  );
}
