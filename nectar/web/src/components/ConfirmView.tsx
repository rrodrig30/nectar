import { useMemo, useState } from 'react';
import type { DerivedConstraint } from '../types';

interface Props {
  constraints: DerivedConstraint[];
  onConfirm: (approvals: Record<number, boolean>, overrides: Record<number, DerivedConstraint>) => void;
  onBack: () => void;
  loading: boolean;
}

// The confirmation gate (SDD Section 3.3, INVARIANT): no derived constraint reaches the engine
// until the physician confirms it. Each row can be approved/unapproved and its numeric value
// overridden; only approved rows are sent, and an edited value is sent as an override.
export function ConfirmView({ constraints, onConfirm, onBack, loading }: Props): JSX.Element {
  const [approvals, setApprovals] = useState<Record<number, boolean>>(() =>
    Object.fromEntries(constraints.map((_, i) => [i, true])),
  );
  const [edited, setEdited] = useState<Record<number, string>>({});

  const approvedCount = useMemo(
    () => Object.values(approvals).filter(Boolean).length,
    [approvals],
  );

  const toggle = (i: number): void =>
    setApprovals((prev) => ({ ...prev, [i]: !prev[i] }));

  const setValue = (i: number, v: string): void =>
    setEdited((prev) => ({ ...prev, [i]: v }));

  const confirm = (): void => {
    const overrides: Record<number, DerivedConstraint> = {};
    constraints.forEach((c, i) => {
      const raw = edited[i];
      if (raw === undefined) return;
      const n = Number(raw);
      const original = c.value ?? null;
      if (raw.trim() !== '' && !Number.isNaN(n) && n !== original) {
        overrides[i] = { ...c, value: n };
      }
    });
    onConfirm(approvals, overrides);
  };

  return (
    <div className="card">
      <h2>2 &middot; Confirm derived constraints</h2>
      <p className="card-hint">
        The system proposes; the clinician owns. Review each constraint, its source signal and
        formula, then approve or override. Unapproved constraints are dropped and never evaluated.
      </p>

      {constraints.length === 0 ? (
        <p className="muted">No constraints were derived from this snapshot.</p>
      ) : (
        <div style={{ overflowX: 'auto' }}>
          <table>
            <thead>
              <tr>
                <th>Approve</th>
                <th>Target</th>
                <th>Direction</th>
                <th>Severity</th>
                <th>Value</th>
                <th>Source signal</th>
                <th>Formula</th>
              </tr>
            </thead>
            <tbody>
              {constraints.map((c, i) => (
                <tr key={i} style={{ opacity: approvals[i] ? 1 : 0.5 }}>
                  <td>
                    <input
                      type="checkbox"
                      style={{ width: 'auto' }}
                      checked={approvals[i] ?? false}
                      onChange={() => toggle(i)}
                      aria-label={`approve ${c.target}`}
                    />
                  </td>
                  <td><code>{c.target}</code></td>
                  <td><span className={`tag ${c.direction}`}>{c.direction}</span></td>
                  <td><span className="tag sev">{c.severity}</span></td>
                  <td>
                    {c.value === null ? (
                      <span className="muted">—</span>
                    ) : (
                      <span style={{ display: 'inline-flex', gap: '0.3rem', alignItems: 'center' }}>
                        <input
                          style={{ width: '5.5rem' }}
                          inputMode="decimal"
                          value={edited[i] ?? String(c.value)}
                          onChange={(e) => setValue(i, e.target.value)}
                        />
                        <span className="muted">{c.unit ?? ''}</span>
                      </span>
                    )}
                  </td>
                  <td className="muted">{c.source_signal}</td>
                  <td className="muted">{c.formula ?? '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="btn-row">
        <button className="btn-ghost" onClick={onBack} disabled={loading}>
          Back
        </button>
        <button className="btn-primary" onClick={confirm} disabled={loading}>
          {loading ? 'Confirming…' : `Confirm ${approvedCount} constraint${approvedCount === 1 ? '' : 's'}`}
        </button>
      </div>
    </div>
  );
}
