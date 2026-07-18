import { useState } from 'react';
import type { ActivityLevel, ClinicalSnapshot, Sex } from '../types';

type UnitSystem = 'metric' | 'us';

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
  unit_system: UnitSystem;
  weight: string; // value in the active unit system (kg or lb)
  height_cm: string; // used when unit_system === 'metric'
  height_ft: string; // used when unit_system === 'us'
  height_in: string; // used when unit_system === 'us'
  activity_level: ActivityLevel;
  goal: string;
}

// The nutritional goal options (SDD Section 3.1). The value string is what the API receives; the
// backend keys the energy envelope off the substrings "loss"/"gain" (else maintenance), so each
// value maps to the intended kcal adjustment. Free text is still accepted by the API, but a bounded
// clinical vocabulary is what a physician expects here.
const GOALS: { value: string; label: string }[] = [
  { value: 'weight loss', label: 'Weight loss' },
  { value: 'weight gain', label: 'Weight gain' },
  { value: 'weight maintenance', label: 'Weight maintenance' },
  { value: 'weight maintenance with increased muscle mass', label: 'Maintenance + muscle mass' },
  { value: 'muscle gain', label: 'Muscle gain' },
  { value: 'cardiovascular improvement', label: 'Cardiovascular improvement' },
];

const LB_PER_KG = 2.2046226218;
const CM_PER_IN = 2.54;

const round1 = (n: number): string => (Number.isFinite(n) ? String(Math.round(n * 10) / 10) : '');

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
  unit_system: 'metric',
  weight: '82',
  height_cm: '175',
  height_ft: '',
  height_in: '',
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
  unit_system: 'metric',
  weight: '',
  height_cm: '',
  height_ft: '',
  height_in: '',
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

// Convert the active-unit inputs to the canonical metric the API requires (kg, cm).
function toMetric(f: FormState): { weight_kg: number; height_cm: number } {
  if (f.unit_system === 'us') {
    const lb = Number(f.weight);
    const ft = Number(f.height_ft || '0');
    const inch = Number(f.height_in || '0');
    return { weight_kg: lb / LB_PER_KG, height_cm: (ft * 12 + inch) * CM_PER_IN };
  }
  return { weight_kg: Number(f.weight), height_cm: Number(f.height_cm) };
}

interface Props {
  onDerive: (snapshot: ClinicalSnapshot) => void;
  loading: boolean;
}

export function ProfileBuilder({ onDerive, loading }: Props): JSX.Element {
  const [f, setF] = useState<FormState>(EXAMPLE);

  const set = <K extends keyof FormState>(key: K, value: FormState[K]): void =>
    setF((prev) => ({ ...prev, [key]: value }));

  // Toggle unit system, converting the current values so nothing is lost across the switch.
  const setUnitSystem = (next: UnitSystem): void =>
    setF((prev) => {
      if (prev.unit_system === next) return prev;
      if (next === 'us') {
        const kg = Number(prev.weight);
        const cm = Number(prev.height_cm);
        const totalIn = Number.isFinite(cm) && cm > 0 ? cm / CM_PER_IN : NaN;
        return {
          ...prev,
          unit_system: 'us',
          weight: Number.isFinite(kg) && prev.weight.trim() !== '' ? round1(kg * LB_PER_KG) : '',
          height_ft: Number.isFinite(totalIn) ? String(Math.floor(totalIn / 12)) : '',
          height_in: Number.isFinite(totalIn) ? round1(totalIn % 12) : '',
        };
      }
      const lb = Number(prev.weight);
      const ft = Number(prev.height_ft || '0');
      const inch = Number(prev.height_in || '0');
      const cm = (ft * 12 + inch) * CM_PER_IN;
      return {
        ...prev,
        unit_system: 'metric',
        weight: Number.isFinite(lb) && prev.weight.trim() !== '' ? round1(lb / LB_PER_KG) : '',
        height_cm: cm > 0 ? round1(cm) : '',
      };
    });

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
    const { weight_kg, height_cm } = toMetric(f);
    onDerive({
      pmh: splitList(f.pmh),
      metabolic_panel: labsToRecord(f.metabolic),
      cbc: labsToRecord(f.cbc),
      medications: splitList(f.medications),
      allergies: splitList(f.allergies),
      age: Number(f.age),
      sex: f.sex,
      weight_kg,
      height_cm,
      activity_level: f.activity_level,
      goal: f.goal,
    });
  };

  const heightFilled =
    f.unit_system === 'metric' ? f.height_cm.trim() !== '' : f.height_ft.trim() !== '';
  const valid =
    f.age.trim() !== '' && f.weight.trim() !== '' && heightFilled && f.goal.trim() !== '';

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
      <div className="card-title-row">
        <h2>1 &middot; Patient profile</h2>
        <div className="unit-toggle" role="group" aria-label="Input unit system">
          <button
            type="button"
            className={f.unit_system === 'us' ? 'seg on' : 'seg'}
            onClick={() => setUnitSystem('us')}
          >
            lb / ft
          </button>
          <button
            type="button"
            className={f.unit_system === 'metric' ? 'seg on' : 'seg'}
            onClick={() => setUnitSystem('metric')}
          >
            kg / cm
          </button>
        </div>
      </div>
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
          <label>Weight ({f.unit_system === 'us' ? 'lb' : 'kg'})</label>
          <input inputMode="decimal" value={f.weight} onChange={(e) => set('weight', e.target.value)} />
        </div>
        {f.unit_system === 'metric' ? (
          <div className="field">
            <label>Height (cm)</label>
            <input
              inputMode="decimal"
              value={f.height_cm}
              onChange={(e) => set('height_cm', e.target.value)}
            />
          </div>
        ) : (
          <div className="field">
            <label>Height (ft / in)</label>
            <div className="kv-row">
              <input
                inputMode="numeric"
                placeholder="ft"
                value={f.height_ft}
                onChange={(e) => set('height_ft', e.target.value)}
              />
              <input
                inputMode="decimal"
                placeholder="in"
                value={f.height_in}
                onChange={(e) => set('height_in', e.target.value)}
              />
            </div>
          </div>
        )}
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
          <select value={f.goal} onChange={(e) => set('goal', e.target.value)}>
            <option value="" disabled>
              Select a goal…
            </option>
            {GOALS.map((g) => (
              <option key={g.value} value={g.value}>
                {g.label}
              </option>
            ))}
          </select>
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
