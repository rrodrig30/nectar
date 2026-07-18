import { useEffect, useState } from 'react';
import { api } from './api';
import { BoundaryBanner } from './components/BoundaryBanner';
import { Sidebar, type Section } from './components/Sidebar';
import { ComposeSection } from './components/ComposeSection';
import { RecipeBrowser } from './components/RecipeBrowser';
import { MealPlanner } from './components/MealPlanner';
import { GroceryList } from './components/GroceryList';
import { VideosSection } from './components/VideosSection';
import { SettingsPanel } from './components/SettingsPanel';
import type {
  DerivedConstraint,
  NutrientInfo,
  PlanResponse,
  RecommendResponse,
} from './types';

const TITLES: Record<Section, string> = {
  compose: 'Compose',
  browse: 'Recipe browser',
  plan: 'Meal planner',
  grocery: 'Grocery list',
  videos: 'Demonstration videos',
  settings: 'Settings',
};

export function App(): JSX.Element {
  const [section, setSection] = useState<Section>('compose');

  // Shared state lifted to the shell so sections compose on each other: the confirmed constraints
  // and recommendation drive the planner; the plan drives the grocery list.
  const [confirmed, setConfirmed] = useState<DerivedConstraint[]>([]);
  const [result, setResult] = useState<RecommendResponse | null>(null);
  const [plan, setPlan] = useState<PlanResponse | null>(null);
  const [vocab, setVocab] = useState<Map<string, NutrientInfo>>(new Map());

  // The nutrient vocabulary (id -> name, unit) labels values across sections. Fetched once.
  useEffect(() => {
    let live = true;
    api
      .nutrients()
      .then((list) => {
        if (live) setVocab(new Map(list.map((n) => [n.nutrient_id, n])));
      })
      .catch(() => {
        /* values still render by id if the vocab lookup fails */
      });
    return () => {
      live = false;
    };
  }, []);

  return (
    <>
      <BoundaryBanner />
      <div className="shell">
        <aside className="shell-nav">
          <div className="brand">
            <img className="logo" src="/nectar-logo.jpg" alt="NECTAR" />
            <span className="brand-tag">research use only</span>
          </div>
          <Sidebar active={section} onNavigate={setSection} />
        </aside>

        <main className="shell-main">
          <header className="shell-head">
            <h1>{TITLES[section]}</h1>
            <span className="shell-sub">
              Nutritional Evaluation and Clinical Therapeutic Advisory Resource
            </span>
          </header>

          <div className="shell-body">
            {section === 'compose' && (
              <ComposeSection
                vocab={vocab}
                confirmed={confirmed}
                setConfirmed={setConfirmed}
                result={result}
                setResult={setResult}
              />
            )}
            {section === 'browse' && <RecipeBrowser vocab={vocab} confirmed={confirmed} />}
            {section === 'plan' && (
              <MealPlanner
                result={result}
                confirmed={confirmed}
                vocab={vocab}
                plan={plan}
                setPlan={setPlan}
                onGoCompose={() => setSection('compose')}
              />
            )}
            {section === 'grocery' && (
              <GroceryList plan={plan} onGoPlan={() => setSection('plan')} />
            )}
            {section === 'videos' && <VideosSection />}
            {section === 'settings' && <SettingsPanel />}
          </div>
        </main>
      </div>
    </>
  );
}
