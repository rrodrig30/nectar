import { useState } from 'react';
import { api, ApiError } from '../api';
import type { AskResponse, RecommendResponse } from '../types';

interface Props {
  result: RecommendResponse;
}

// The natural-language touchpoint at the end of the query path. The question is grounded in the
// current ranking: the model may only reference these dishes, and it narrates - it never emits a
// nutrient number or a clinical limit (those come from the graph, shown in Results).
export function AskPanel({ result }: Props): JSX.Element {
  const [question, setQuestion] = useState('');
  const [answer, setAnswer] = useState<AskResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const dishIds = result.rankings.map((r) => r.dish_id);
  const summary = result.rankings
    .map((r) => `${r.dish_id}: ${r.best ? `best score ${r.best.score}` : 'no admissible version'}`)
    .join('; ');

  const ask = async (): Promise<void> => {
    const q = question.trim();
    if (!q) return;
    setLoading(true);
    setErr(null);
    try {
      setAnswer(
        await api.ask({
          request: q,
          allowed_citations: [],
          allowed_dishes: dishIds,
          ranking_summary: summary,
        }),
      );
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="card">
      <h2>Ask about these recommendations</h2>
      <p className="card-hint">
        Grounded narration over the ranking above. The model stays within these dishes and cannot
        introduce a nutrient value.
      </p>
      <div style={{ display: 'flex', gap: '0.5rem' }}>
        <input
          value={question}
          placeholder="e.g. Which option is lowest in sodium, and why?"
          onChange={(e) => setQuestion(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter') void ask(); }}
        />
        <button className="btn-primary" onClick={() => void ask()} disabled={loading || !question.trim()}>
          {loading ? 'Asking…' : 'Ask'}
        </button>
      </div>

      {err && <div className="notice err">{err}</div>}

      {answer && (
        <div style={{ marginTop: '0.8rem' }}>
          <div className="narration">{answer.narration || <span className="muted">(no narration returned)</span>}</div>
          <p className="muted" style={{ fontSize: '0.78rem', marginTop: '0.4rem' }}>
            parsed intent: <code>{answer.intent}</code>
            {answer.dishes.length > 0 && <> · dishes: {answer.dishes.join(', ')}</>}
            {answer.exclude.length > 0 && <> · exclude: {answer.exclude.join(', ')}</>}
          </p>
        </div>
      )}
    </div>
  );
}
