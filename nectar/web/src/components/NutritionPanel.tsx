import type { NutrientInfo, NutrientValue } from '../types';
import { fmt, KEY_NUTRIENTS, NUTRIENT_GROUPS } from '../nutrients';

interface Props {
  nutrients: NutrientValue[];
  vocab: Map<string, NutrientInfo>;
}

// Per-serving nutrition, grouped for reading, each value labeled with its canonical unit and human
// name. Energy is a hero stat; sodium/potassium/phosphorus are flagged for renal/cardiac review.
// [INVARIANT] Every value carries the calculated-not-measured disclaimer (hover) and the panel
// states it once up front, since these are computed, not laboratory-measured.
export function NutritionPanel({ nutrients, vocab }: Props): JSX.Element {
  const byId = new Map(nutrients.map((n) => [n.nutrient, n]));
  const label = (id: string): string => vocab.get(id)?.name ?? id;
  const unit = (id: string): string => vocab.get(id)?.unit ?? '';

  const energy = byId.get('energy');
  const lowestConfidence = nutrients.length
    ? Math.min(
        ...nutrients.map((n) => {
          const m = /confidence (\d+)%/.exec(n.disclaimer);
          return m ? Number(m[1]) : 100;
        }),
      )
    : null;

  return (
    <div className="nutrition">
      <div className="nutrition-head">
        <h3>Nutrition <span className="muted">· per serving</span></h3>
        {energy && (
          <div className="energy-stat" title={energy.disclaimer}>
            <span className="energy-val">{fmt(energy.value)}</span>
            <span className="energy-unit">kcal</span>
          </div>
        )}
      </div>

      <div className="calc-banner">
        Calculated, not laboratory-measured{lowestConfidence !== null && ` · confidence from ${lowestConfidence}%`}.
        Hover a value for its source.
      </div>

      <div className="nutrient-groups">
        {NUTRIENT_GROUPS.map((g) => {
          const rows = g.ids.filter((id) => byId.has(id));
          if (rows.length === 0) return null;
          return (
            <div className="nutrient-group" key={g.key}>
              <div className="ng-label">{g.label}</div>
              {rows.map((id) => {
                const nv = byId.get(id)!;
                const key = KEY_NUTRIENTS.has(id);
                return (
                  <div className={`ng-row${key ? ' key' : ''}`} key={id} title={nv.disclaimer}>
                    <span className="ng-name">
                      {label(id)}
                      {key && <span className="ng-flag" title="Electrolyte watched in renal/cardiac care">●</span>}
                    </span>
                    <span className="ng-value">
                      {fmt(nv.value)} <span className="ng-unit">{unit(id)}</span>
                    </span>
                  </div>
                );
              })}
            </div>
          );
        })}
      </div>
    </div>
  );
}
