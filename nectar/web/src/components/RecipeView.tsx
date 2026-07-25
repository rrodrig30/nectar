import type { NutrientInfo, RecipeDetail } from '../types';
import { humanize } from '../nutrients';
import { NutritionPanel } from './NutritionPanel';

interface Props {
  recipe: RecipeDetail;
  vocab?: Map<string, NutrientInfo>; // when given, the per-serving nutrition table is shown
}

// The recipe as a cook uses it: the ingredient list with quantities as written, then the
// step-by-step directions. The resolved-food table (what the nutrition is computed from, with parsed
// per-ingredient masses) is kept below as a collapsible detail, since those amounts are calibration
// inputs, not cooking measurements.
export function RecipeView({ recipe, vocab }: Props): JSX.Element {
  const methods = [...new Set(recipe.ingredients.map((i) => i.method).filter(Boolean))] as string[];
  const hasText = recipe.ingredient_lines.length > 0 || recipe.directions.length > 0;

  return (
    <div className="recipe">
      <div className="recipe-meta">
        {recipe.servings != null && (
          <span className="meta-chip"><b>{recipe.servings}</b> servings</span>
        )}
        <span className="meta-chip">{recipe.ingredient_lines.length || recipe.ingredients.length} ingredients</span>
        {recipe.source_id && <span className="meta-chip">source: {recipe.source_id}</span>}
      </div>

      {(recipe.serving_mass_g != null || recipe.energy_kcal != null || recipe.fluid_ml != null) && (
        <div className="serving-facts" title="Calculated per-serving facts for the as-authored version">
          {recipe.serving_mass_g != null && (
            <span className="sf"><b>{Math.round(recipe.serving_mass_g)}</b> g<span className="sf-l">per serving</span></span>
          )}
          {recipe.energy_kcal != null && (
            <span className="sf"><b>{Math.round(recipe.energy_kcal)}</b> kcal<span className="sf-l">energy</span></span>
          )}
          {recipe.fluid_ml != null && (
            <span className="sf"><b>{Math.round(recipe.fluid_ml)}</b> mL<span className="sf-l">fluid</span></span>
          )}
        </div>
      )}

      {vocab && recipe.nutrients.length > 0 && (
        <NutritionPanel nutrients={recipe.nutrients} vocab={vocab} />
      )}

      {recipe.ingredient_lines.length > 0 && (
        <section className="recipe-block">
          <h3 className="recipe-h">Ingredients</h3>
          <ul className="ingredient-lines">
            {recipe.ingredient_lines.map((line, i) => (
              <li key={i}>{line}</li>
            ))}
          </ul>
        </section>
      )}

      {recipe.directions.length > 0 && (
        <section className="recipe-block">
          <h3 className="recipe-h">Directions</h3>
          <ol className="directions">
            {recipe.directions.map((step, i) => (
              <li key={i}>{step}</li>
            ))}
          </ol>
        </section>
      )}

      {!hasText && (
        <p className="notice info">
          The step-by-step method for this recipe record is not available. The resolved ingredients
          used for the nutrition calculation are shown below.
        </p>
      )}

      {recipe.ingredients.length > 0 && (
        <details className="nutrition-basis">
          <summary>
            How the nutrition was calculated &mdash; {recipe.ingredients.length} resolved food
            {recipe.ingredients.length === 1 ? '' : 's'}
          </summary>
          {methods.length > 0 && (
            <div className="prep-summary">
              <span className="muted">Preparation methods:</span>
              {methods.map((m) => <span className="tag prep" key={m}>{humanize(m)}</span>)}
            </div>
          )}
          <table className="ingredient-table">
            <thead>
              <tr>
                <th>Resolved food</th>
                <th>Preparation</th>
                <th className="num">Amount<span className="th-note">calibration input, grams</span></th>
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
                        <span className="muted">&mdash;</span>
                      )}
                  </td>
                  <td className="num">{ing.amount != null ? Math.round(ing.amount).toLocaleString() : '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="recipe-foot muted">
            These are the foods each ingredient line was matched to for the nutrition estimate; the
            grams are the calculation basis, not a cooking measurement. Every nutrient value is
            calculated, not measured.
            {recipe.license && <> License: {recipe.license}.</>}
          </p>
        </details>
      )}
    </div>
  );
}
