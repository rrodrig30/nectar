import { useState } from 'react';
import { api, ApiError } from './api';
import { BoundaryBanner } from './components/BoundaryBanner';
import { ProfileBuilder } from './components/ProfileBuilder';
import { ConfirmView } from './components/ConfirmView';
import { RecommendSetup } from './components/RecommendSetup';
import { Results } from './components/Results';
import { EvidencePanel } from './components/EvidencePanel';
import { AskPanel } from './components/AskPanel';
import type { ClinicalSnapshot, DerivedConstraint, RecommendResponse } from './types';

type Step = 'profile' | 'confirm' | 'recommend';

const STEPS: { id: Step; label: string }[] = [
  { id: 'profile', label: 'Profile' },
  { id: 'confirm', label: 'Confirm' },
  { id: 'recommend', label: 'Recommend' },
];

export function App(): JSX.Element {
  const [step, setStep] = useState<Step>('profile');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [derived, setDerived] = useState<DerivedConstraint[]>([]);
  const [confirmed, setConfirmed] = useState<DerivedConstraint[]>([]);
  const [result, setResult] = useState<RecommendResponse | null>(null);

  const fail = (e: unknown): void =>
    setError(e instanceof ApiError ? e.message : String(e));

  const derive = async (snapshot: ClinicalSnapshot): Promise<void> => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.derive(snapshot);
      setDerived(res.constraints);
      setConfirmed([]);
      setResult(null);
      setStep('confirm');
    } catch (e) {
      fail(e);
    } finally {
      setLoading(false);
    }
  };

  const confirm = async (
    approvals: Record<number, boolean>,
    overrides: Record<number, DerivedConstraint>,
  ): Promise<void> => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.confirm(derived, approvals, overrides);
      setConfirmed(res.confirmed);
      setResult(null);
      setStep('recommend');
    } catch (e) {
      fail(e);
    } finally {
      setLoading(false);
    }
  };

  const recommend = async (conditionIds: string[], dishIds: string[]): Promise<void> => {
    setLoading(true);
    setError(null);
    try {
      setResult(await api.recommend(confirmed, conditionIds, dishIds));
    } catch (e) {
      fail(e);
    } finally {
      setLoading(false);
    }
  };

  const activeIndex = STEPS.findIndex((s) => s.id === step);

  return (
    <>
      <BoundaryBanner />
      <div className="app">
        <div className="masthead">
          <img className="logo" src="/nectar-logo.jpg" alt="NECTAR" />
          <span className="sub">
            Nutritional Evaluation and Clinical Therapeutic Advisory Resource
            <span className="sub-tag">research use only</span>
          </span>
        </div>

        {step === 'profile' && (
          <div className="hero" role="img" aria-label="A plated, portion-controlled meal">
            <div className="hero-overlay">
              <h1>Compose a recipe to the patient in front of you.</h1>
              <p>
                Enter a de-identified clinical snapshot. NECTAR derives the dietary constraints,
                you confirm them, and it ranks real recipes against the confirmed set.
              </p>
            </div>
          </div>
        )}

        <div className="stepper">
          {STEPS.map((s, i) => {
            const state = i === activeIndex ? 'active' : i < activeIndex ? 'done' : '';
            return (
              <div key={s.id} className={`step-chip ${state}`}>
                <span className="num">{i < activeIndex ? '✓' : i + 1}</span>
                {s.label}
              </div>
            );
          })}
        </div>

        {error && <div className="notice err">{error}</div>}

        {step === 'profile' && <ProfileBuilder onDerive={derive} loading={loading} />}

        {step === 'confirm' && (
          <ConfirmView
            constraints={derived}
            onConfirm={confirm}
            onBack={() => setStep('profile')}
            loading={loading}
          />
        )}

        {step === 'recommend' && (
          <>
            <RecommendSetup
              confirmedCount={confirmed.length}
              onRecommend={recommend}
              onBack={() => setStep('confirm')}
              loading={loading}
            />
            {result && <Results result={result} />}
            {result && <EvidencePanel confirmed={confirmed} result={result} />}
            {result && result.rankings.length > 0 && <AskPanel result={result} />}
          </>
        )}
      </div>
    </>
  );
}
