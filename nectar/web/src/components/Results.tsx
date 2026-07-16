import type { DishRanking, Evaluation, NutrientValue, RecommendResponse } from '../types';

function fmt(n: number): string {
  if (!Number.isFinite(n)) return String(n);
  const abs = Math.abs(n);
  if (abs !== 0 && (abs < 0.01 || abs >= 100000)) return n.toExponential(2);
  return n.toLocaleString(undefined, { maximumFractionDigits: 2 });
}

function Nutrients({ items }: { items: NutrientValue[] }): JSX.Element {
  if (items.length === 0) return <span className="muted">no disclosed nutrients</span>;
  return (
    <div>
      {items.map((nv) => (
        // The disclaimer (calculated-not-measured, with source + confidence) is on every value.
        <span className="nutrient" key={nv.nutrient} title={nv.disclaimer}>
          <span className="n-name">{nv.nutrient}</span>
          <span className="n-val">{fmt(nv.value)}</span>
          {!nv.measured && <span className="calc-note">calc</span>}
        </span>
      ))}
    </div>
  );
}

function EvalRow({ e, label }: { e: Evaluation; label: string }): JSX.Element {
  return (
    <div>
      <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'baseline', flexWrap: 'wrap' }}>
        <span className="muted">{label}</span>
        <code className="dish-id">{e.variant_id}</code>
        {e.contraindicated ? (
          <span className="badge-bad">contraindicated</span>
        ) : e.admissible ? (
          <span className="badge-ok">admissible</span>
        ) : (
          <span className="muted">not admissible</span>
        )}
        <span className="score-pill">score {fmt(e.score)}</span>
      </div>
      {e.reasons.length > 0 && (
        <ul className="muted" style={{ margin: '0.3rem 0', fontSize: '0.82rem' }}>
          {e.reasons.map((r, i) => <li key={i}>{r}</li>)}
        </ul>
      )}
      <Nutrients items={e.nutrients} />
    </div>
  );
}

function DishCard({ r }: { r: DishRanking }): JSX.Element {
  const contra = r.best?.contraindicated ?? false;
  const stats = Object.values(r.nutrient_stats);
  return (
    <div className={`dish${contra ? ' contra' : ''}`}>
      <div className="dish-head">
        <span className="dish-name">{r.dish_id}</span>
        {r.best && <span className="score-pill">best {fmt(r.best.score)}</span>}
      </div>

      {r.best ? (
        <EvalRow e={r.best} label="Best version" />
      ) : (
        <p className="muted">No admissible version for this patient.</p>
      )}

      {r.versions.length > 1 && (
        <details>
          <summary>{r.versions.length} versions evaluated</summary>
          <div style={{ marginTop: '0.5rem', display: 'grid', gap: '0.6rem' }}>
            {r.versions.map((v, i) => <EvalRow key={v.variant_id} e={v} label={`Version ${i + 1}`} />)}
          </div>
        </details>
      )}

      {stats.length > 0 && (
        <details>
          <summary>Version spread across this dish ({stats[0]?.count ?? 0} versions)</summary>
          <div style={{ overflowX: 'auto', marginTop: '0.4rem' }}>
            <table>
              <thead>
                <tr><th>Nutrient</th><th>Min</th><th>Median</th><th>Max</th><th>Mean</th><th>SD</th></tr>
              </thead>
              <tbody>
                {stats.map((s) => (
                  <tr key={s.nutrient}>
                    <td>{s.nutrient} <span className="muted">({s.unit})</span></td>
                    <td>{fmt(s.minimum)}</td>
                    <td>{fmt(s.median)}</td>
                    <td>{fmt(s.maximum)}</td>
                    <td>{fmt(s.mean)}</td>
                    <td>{fmt(s.stdev)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      )}
    </div>
  );
}

interface Props {
  result: RecommendResponse;
}

export function Results({ result }: Props): JSX.Element {
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
        result.rankings.map((r) => <DishCard key={r.dish_id} r={r} />)
      )}

      <div className="notice info" style={{ marginTop: '0.8rem' }}>
        <strong>Boundary:</strong> {result.boundary}
      </div>
    </div>
  );
}
