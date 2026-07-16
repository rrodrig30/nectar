import { useState } from 'react';
import type { ActivityLevel, ClinicalSnapshot, Sex } from '../types';

// A key/value lab row in the editor. Kept as strings while editing; parsed to number on submit.
interface LabRow {
  key: string;
  value: string;
}

interface FormState {
  pmh: string;
  medications: string;
  allergies: string;
  metabolic: LabRow[];
  cbc: LabRow[];
  age: string;
  sex: Sex;
  weight_kg: string;
  height_cm: string;
  activity_level: ActivityLevel;
  goal: string;
}

// A realistic multimorbid example (CKD 3b + HTN + T2DM) matching the platform's golden scenarios:
// serum K 5.4 tightens potassium; Cr 1.8 -> eGFR -> CKD stage; ANC 900 activates raw-food exclusion.
const EXAMPLE: FormState = {
  pmh: 'CKD stage 3, hypertension, type 2 diabetes',
  medications: 'lisinopril, metformin',
  allergies: 'shellfish',
  metabolic: [
    { key: 'K', value: '5.4' },
    { key: 'Cr', value: '1.8' },
    { key: 'glucose', value: '142' },
    { key: 'Na', value: '138' },
  ],
  cbc: [
    { key: 'Hgb', value: '10.1' },
    { key: 'ANC', value: '900' },
  ],
  age: '64',
  sex: 'M',
  weight_kg: '82',
  height_cm: '175',
  activity_level: 'light',
  goal: 'cardiovascular improvement',
};

const EMPTY: FormState = {
  pmh: '',
  medications: '',
  allergies: '',
  metabolic: [{ key: '', value: '' }],
  cbc: [{ key: '', value: '' }],
  age: '',
  sex: 'M',
  weight_kg: '',
  height_cm: '',
  activity_level: 'moderate',
  goal: '',
};

function splitList(s: string): string[] {
  return s.split(',').map((x) => x.trim()).filter(Boolean);
}

function labsToRecord(rows: LabRow[]): Record<string, number> {
  const out: Record<string, number> = {};
  for (const { key, value } of rows) {
    const k = key.trim();
    if (!k) continue;
    const n = Number(value);
    if (value.trim() !== '' && !Number.isNaN(n)) out[k] = n;
  }
  return out;
}

interface Props {
  onDerive: (snapshot: ClinicalSnapshot) => void;
  loading: boolean;
}

export function ProfileBuilder({ onDerive, loading }: Props): JSX.Element {
  const [f, setF] = useState<FormState>(EXAMPLE);

  const set = <K extends keyof FormState>(key: K, value: FormState[K]): void =>
    setF((prev) => ({ ...prev, [key]: value }));

  const setLab = (field: 'metabolic' | 'cbc', i: number, patch: Partial<LabRow>): void =>
    setF((prev) => {
      const rows = prev[field].map((r, idx) => (idx === i ? { ...r, ...patch } : r));
      return { ...prev, [field]: rows };
    });

  const addLab = (field: 'metabolic' | 'cbc'): void =>
    setF((prev) => ({ ...prev, [field]: [...prev[field], { key: '', value: '' }] }));

  const removeLab = (field: 'metabolic' | 'cbc', i: number): void =>
    setF((prev) => ({ ...prev, [field]: prev[field].filter((_, idx) => idx !== i) }));

  const submit = (): void => {
    onDerive({
      pmh: splitList(f.pmh),
      metabolic_panel: labsToRecord(f.metabolic),
      cbc: labsToRecord(f.cbc),
      medications: splitList(f.medications),
      allergies: splitList(f.allergies),
      age: Number(f.age),
      sex: f.sex,
      weight_kg: Number(f.weight_kg),
      height_cm: Number(f.height_cm),
      activity_level: f.activity_level,
      goal: f.goal,
    });
  };

  const valid =
    f.age.trim() !== '' &&
    f.weight_kg.trim() !== '' &&
    f.height_cm.trim() !== '' &&
    f.goal.trim() !== '';

  const labEditor = (field: 'metabolic' | 'cbc', title: string): JSX.Element => (
    <div className="field">
      <label>{title}</label>
      {f[field].map((row, i) => (
        <div className="kv-row" key={i}>
          <input
            placeholder="analyte (e.g. K)"
            value={row.key}
            onChange={(e) => setLab(field, i, { key: e.target.value })}
          />
          <input
            placeholder="value"
            inputMode="decimal"
            value={row.value}
            onChange={(e) => setLab(field, i, { value: e.target.value })}
          />
          <button
            type="button"
            className="btn-ghost btn-sm"
            onClick={() => removeLab(field, i)}
            aria-label="remove row"
          >
            &times;
          </button>
        </div>
      ))}
      <button type="button" className="btn-ghost btn-sm" onClick={() => addLab(field)}>
        + add analyte
      </button>
    </div>
  );

  return (
    <div className="card">
      <h2>1 &middot; Patient profile</h2>
      <p className="card-hint">
        De-identified, transient snapshot. Free-text history is parsed into structured factors by
        the model; numeric targets are derived deterministically. No identifiers are stored.
      </p>

      <div className="grid">
        <div className="field">
          <label>Age</label>
          <input inputMode="numeric" value={f.age} onChange={(e) => set('age', e.target.value)} />
        </div>
        <div className="field">
          <label>Sex</label>
          <select value={f.sex} onChange={(e) => set('sex', e.target.value as Sex)}>
            <option value="M">M</option>
            <option value="F">F</option>
          </select>
        </div>
        <div className="field">
          <label>Weight (kg)</label>
          <input inputMode="decimal" value={f.weight_kg} onChange={(e) => set('weight_kg', e.target.value)} />
        </div>
        <div className="field">
          <label>Height (cm)</label>
          <input inputMode="decimal" value={f.height_cm} onChange={(e) => set('height_cm', e.target.value)} />
        </div>
        <div className="field">
          <label>Activity level</label>
          <select
            value={f.activity_level}
            onChange={(e) => set('activity_level', e.target.value as ActivityLevel)}
          >
            <option value="sedentary">sedentary</option>
            <option value="light">light</option>
            <option value="moderate">moderate</option>
            <option value="active">active</option>
          </select>
        </div>
        <div className="field">
          <label>Goal</label>
          <input value={f.goal} onChange={(e) => set('goal', e.target.value)} placeholder="e.g. cardiovascular improvement" />
        </div>
      </div>

      <div className="field">
        <label>Past medical history (comma-separated)</label>
        <textarea value={f.pmh} onChange={(e) => set('pmh', e.target.value)} />
      </div>

      <div className="grid">
        <div className="field">
          <label>Medications (comma-separated)</label>
          <input value={f.medications} onChange={(e) => set('medications', e.target.value)} />
        </div>
        <div className="field">
          <label>Allergies (comma-separated)</label>
          <input value={f.allergies} onChange={(e) => set('allergies', e.target.value)} />
        </div>
      </div>

      <div className="grid">
        {labEditor('metabolic', 'Metabolic panel')}
        {labEditor('cbc', 'CBC')}
      </div>

      <div className="btn-row">
        <button className="btn-primary" onClick={submit} disabled={!valid || loading}>
          {loading ? 'Deriving…' : 'Derive constraints'}
        </button>
        <button className="btn-ghost" onClick={() => setF(EXAMPLE)} disabled={loading}>
          Load example
        </button>
        <button className="btn-ghost" onClick={() => setF(EMPTY)} disabled={loading}>
          Clear
        </button>
      </div>
    </div>
  );
}
