import { useEffect, useMemo, useState } from 'react';
import { api } from '../api';
import type { DerivedConstraint, Guideline, RecommendResponse } from '../types';

interface Props {
  confirmed: DerivedConstraint[];
  result: RecommendResponse;
}

// The evidence behind the ranking: which guideline each confirmed constraint cites, how each
// direction conflict was resolved (by precedence, never averaged), and any guideline passage text
// the knowledge base holds for the cited ids. Passage text is often absent (KB curation lags the
// citations); that is surfaced honestly rather than hidden.
export function EvidencePanel({ confirmed, result }: Props): JSX.Element {
  const citedIds = useMemo(() => {
    const ids = new Set<string>();
    for (const c of confirmed) if (c.guideline_id) ids.add(c.guideline_id);
    for (const cf of result.conflicts) for (const g of cf.guideline_ids) ids.add(g);
    return [...ids];
  }, [confirmed, result]);

  const [passages, setPassages] = useState<Guideline[]>([]);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    let live = true;
    setLoaded(false);
    api
      .guidelines(citedIds)
      .then((g) => { if (live) { setPassages(g); setLoaded(true); } })
      .catch(() => { if (live) { setPassages([]); setLoaded(true); } });
    return () => { live = false; };
  }, [citedIds]);

  const withGuideline = confirmed.filter((c) => c.guideline_id);
  const passageById = new Map(passages.map((p) => [p.guideline_id, p]));
  const idsWithoutText = citedIds.filter((id) => !passageById.get(id)?.chunk);

  return (
    <div className="card">
      <h2>Evidence &amp; citations</h2>
      <p className="card-hint">
        The basis behind each constraint and conflict. Nutrient numbers come from the graph, not the
        model; guideline text is shown when the knowledge base holds it.
      </p>

      {withGuideline.length > 0 && (
        <>
          <h3>Constraint basis</h3>
          <div style={{ overflowX: 'auto' }}>
            <table>
              <thead>
                <tr><th>Target</th><th>Derived from</th><th>Formula</th><th>Cites</th></tr>
              </thead>
              <tbody>
                {withGuideline.map((c, i) => (
                  <tr key={i}>
                    <td><code>{c.target}</code></td>
                    <td className="muted">{c.source_signal}</td>
                    <td className="muted">{c.formula ?? '—'}</td>
                    <td><code>{c.guideline_id}</code></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      {result.conflicts.length > 0 && (
        <>
          <h3 style={{ marginTop: '0.8rem' }}>Conflict resolutions</h3>
          <ul style={{ margin: '0.3rem 0', fontSize: '0.86rem' }}>
            {result.conflicts.map((c, i) => (
              <li key={i}>
                <code>{c.nutrient}</code> — {c.resolution}. Winning rule: <code>{c.winning_rule}</code>.
                {c.guideline_ids.length > 0 && <span className="muted"> Cites {c.guideline_ids.join(', ')}.</span>}
              </li>
            ))}
          </ul>
        </>
      )}

      <h3 style={{ marginTop: '0.8rem' }}>Guideline passages</h3>
      {citedIds.length === 0 ? (
        <p className="muted">No guideline citations attached to this recommendation.</p>
      ) : !loaded ? (
        <p className="spinner">Loading passages…</p>
      ) : (
        <>
          {passages.filter((p) => p.chunk).map((p) => (
            <div key={p.guideline_id} className="narration" style={{ marginBottom: '0.5rem' }}>
              <strong>{p.title ?? p.guideline_id}</strong>
              {p.org && <span className="muted"> · {p.org}</span>}
              {p.year && <span className="muted"> · {p.year}</span>}
              <div style={{ marginTop: '0.3rem' }}>{p.chunk}</div>
            </div>
          ))}
          {idsWithoutText.length > 0 && (
            <div className="notice info">
              Cited but no passage text loaded yet:{' '}
              {idsWithoutText.map((id) => <code key={id} style={{ marginRight: '0.4rem' }}>{id}</code>)}
              <div className="muted" style={{ marginTop: '0.25rem', fontSize: '0.78rem' }}>
                Guideline-passage curation is a standing knowledge-base effort (NutriScrape Phase 4);
                the citation is recorded, the passage text is pending load.
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
