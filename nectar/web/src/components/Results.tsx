import { useEffect, useState } from 'react';
import { api } from '../api';
import type { DishRanking, Evaluation, NutrientInfo, RecipeDetail, RecommendResponse } from '../types';
import { fmt } from '../nutrients';
import { NutritionPanel } from './NutritionPanel';
import { RecipeView } from './RecipeView';

function StatusBadge({ e }: { e: Evaluation | null }): JSX.Element {
  if (!e) return <span className="muted">no admissible version</span>;
  if (e.contraindicated) return <span className="pill bad">Contraindicated</span>;
  if (e.admissible) return <span className="pill ok">Admissible</span>;
  return <span className="pill neutral">Not admissible</span>;
}

function DishCard({ r, vocab }: { r: DishRanking; vocab: Map<string, NutrientInfo> }): JSX.Element {
  const [recipe, setRecipe] = useState<RecipeDetail | null>(null);
  const [recipeState, setRecipeState] = useState<'loading' | 'ok' | 'none'>('loading');

  useEffect(() => {
    let live = true;
    setRecipeState('loading');
    api
      .recipe(r.dish_id)
      .then((rc) => { if (live) { setRecipe(rc); setRecipeState('ok'); } })
      .catch(() => { if (live) { setRecipe(null); setRecipeState('none'); } });
    return () => { live = false; };
  }, [r.dish_id]);

  const best = r.best;
  const contra = best?.contraindicated ?? false;
  const title = recipe?.title ?? r.dish_id.replace(/^dish:/, '');
  const stats = Object.values(r.nutrient_stats);

  return (
    <div className={`dish-card${contra ? ' contra' : ''}`}>
      <div className="dc-head">
        <div>
          <div className="dc-title">{title}</div>
          <code className="dc-id">{r.dish_id}</code>
        </div>
        <div className="dc-status">
          <StatusBadge e={best} />
          {best && <span className="score-pill" title="Higher is a better fit for the confirmed constraints">score {fmt(best.score)}</span>}
        </div>
      </div>

      {best && best.reasons.length > 0 && (
        <ul className="reasons">
          {best.reasons.map((rz, i) => <li key={i}>{rz}</li>)}
        </ul>
      )}

      <div className="dc-body">
        <div className="dc-col">
          <h3 className="col-h">Ingredients &amp; preparation</h3>
          {recipeState === 'loading' && <p className="spinner">Loading recipe…</p>}
          {recipeState === 'none' && <p className="muted">No recipe record for this dish.</p>}
          {recipeState === 'ok' && recipe && <RecipeView recipe={recipe} />}
        </div>
        <div className="dc-col">
          {best ? (
            <NutritionPanel nutrients={best.nutrients} vocab={vocab} />
          ) : (
            <p className="muted">No admissible version, so no per-serving facts are shown.</p>
          )}
        </div>
      </div>

      {r.versions.length > 1 && (
        <details>
          <summary>{r.versions.length} versions evaluated</summary>
          <table className="mini">
            <thead><tr><th>Variant</th><th>Status</th><th className="num">Score</th></tr></thead>
            <tbody>
              {r.versions.map((v) => (
                <tr key={v.variant_id}>
                  <td><code>{v.variant_id}</code></td>
                  <td><StatusBadge e={v} /></td>
                  <td className="num">{fmt(v.score)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </details>
      )}

      {stats.length > 0 && (
        <details>
          <summary>Version spread across this dish ({stats[0]?.count ?? 0} versions)</summary>
          <table className="mini">
            <thead><tr><th>Nutrient</th><th className="num">Min</th><th className="num">Median</th><th className="num">Max</th></tr></thead>
            <tbody>
              {stats.map((s) => (
                <tr key={s.nutrient}>
                  <td>{s.nutrient} <span className="muted">({s.unit})</span></td>
                  <td className="num">{fmt(s.minimum)}</td>
                  <td className="num">{fmt(s.median)}</td>
                  <td className="num">{fmt(s.maximum)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </details>
      )}
    </div>
  );
}

interface Props {
  result: RecommendResponse;
  vocab: Map<string, NutrientInfo>;
}

export function Results({ result, vocab }: Props): JSX.Element {
  return (
    <div className="card">
      <h2>Recommendations</h2>

      {result.conflicts.length > 0 && (
        <div className="notice conflict">
          <strong>Conflicts resolved by precedence (never averaged):</strong>
          <ul style={{ margin: '0.3rem 0 0' }}>
            {result.conflicts.map((c, i) => (
              <li key={i}>
                <code>{c.nutrient}</code> — {c.kind}: {c.resolution} (winner: {c.winning_rule})
                {c.guideline_ids.length > 0 && <span className="muted"> · cites {c.guideline_ids.join(', ')}</span>}
              </li>
            ))}
          </ul>
        </div>
      )}

      {result.gaps.length > 0 && (
        <div className="notice info">
          No admissible corpus version for: {result.gaps.map((g) => <code key={g}>{g}</code>)}. A
          remediation suggestion would be labeled as such, not shown as an existing recipe.
        </div>
      )}

      {result.rankings.length === 0 ? (
        <p className="muted">No dishes ranked.</p>
      ) : (
        result.rankings.map((r) => <DishCard key={r.dish_id} r={r} vocab={vocab} />)
      )}

      <div className="notice info" style={{ marginTop: '0.8rem' }}>
        <strong>Boundary:</strong> {result.boundary}
      </div>
    </div>
  );
}
