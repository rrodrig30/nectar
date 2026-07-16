import type { RecipeDetail } from '../types';
import { humanize } from '../nutrients';

interface Props {
  recipe: RecipeDetail;
}

// Ingredients and their parsed preparation. The corpus carries a resolved food, a parsed amount,
// and a per-ingredient method + cut; it does not carry step-by-step instructions or cook
// times/temperatures for most records, so those are not shown rather than invented.
export function RecipeView({ recipe }: Props): JSX.Element {
  const methods = [...new Set(recipe.ingredients.map((i) => i.method).filter(Boolean))] as string[];

  return (
    <div className="recipe">
      <div className="recipe-meta">
        {recipe.servings != null && (
          <span className="meta-chip"><b>{recipe.servings}</b> servings</span>
        )}
        <span className="meta-chip">{recipe.ingredients.length} ingredients</span>
        {recipe.source_id && <span className="meta-chip">source: {recipe.source_id}</span>}
      </div>

      {methods.length > 0 && (
        <div className="prep-summary">
          <span className="muted">Preparation methods:</span>
          {methods.map((m) => <span className="tag prep" key={m}>{humanize(m)}</span>)}
        </div>
      )}

      <table className="ingredient-table">
        <thead>
          <tr>
            <th>Ingredient</th>
            <th>Preparation</th>
            <th className="num">Amount<span className="th-note">parsed, uncalibrated</span></th>
          </tr>
        </thead>
        <tbody>
          {recipe.ingredients.map((ing, i) => (
            <tr key={i}>
              <td>{ing.food ?? <span className="muted">unresolved</span>}</td>
              <td>
                {ing.method && ing.method !== 'unknown' && (
                  <span className="tag prep">{humanize(ing.method)}</span>
                )}
                {ing.cut_class && ing.cut_class !== 'unknown' && (
                  <span className="tag cut">{humanize(ing.cut_class)}</span>
                )}
                {(!ing.method || ing.method === 'unknown') &&
                  (!ing.cut_class || ing.cut_class === 'unknown') && (
                    <span className="muted">—</span>
                  )}
              </td>
              <td className="num">{ing.amount != null ? ing.amount.toLocaleString(undefined, { maximumFractionDigits: 2 }) : '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <p className="recipe-foot muted">
        Amounts are the parsed corpus quantities (not calibrated per-serving grams); step-by-step
        instructions and cook times are not present in this corpus record.
        {recipe.license && <> License: {recipe.license}.</>}
      </p>
    </div>
  );
}
