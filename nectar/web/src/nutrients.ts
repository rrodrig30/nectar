// Presentation grouping for the nutrient vocabulary. The clinical meaning of each nutrient lives in
// the graph and the knowledge base; this is purely how they are laid out for reading.

export interface NutrientGroup {
  key: string;
  label: string;
  ids: string[];
}

export const NUTRIENT_GROUPS: NutrientGroup[] = [
  { key: 'macros', label: 'Macronutrients', ids: ['protein', 'carbohydrate', 'fat_total'] },
  { key: 'fats', label: 'Fats', ids: ['fat_saturated', 'fat_mono', 'fat_poly', 'fat_trans'] },
  {
    key: 'fiber_sugar',
    label: 'Fiber & sugar',
    ids: ['fiber_total', 'fiber_soluble', 'sugar_total', 'sugar_added'],
  },
  {
    key: 'minerals',
    label: 'Minerals & electrolytes',
    ids: ['sodium', 'potassium', 'phosphorus', 'calcium', 'iron', 'magnesium'],
  },
  { key: 'other', label: 'Other', ids: ['omega3_epa_dha', 'vitamin_k', 'phenylalanine'] },
];

// Nutrients that are electrolytes/minerals renal and cardiac patients watch most closely; the panel
// highlights these so they are not lost in the list.
export const KEY_NUTRIENTS = new Set(['sodium', 'potassium', 'phosphorus']);

/** Format a nutrient magnitude compactly with tabular-friendly rounding. */
export function fmt(n: number): string {
  if (!Number.isFinite(n)) return String(n);
  const abs = Math.abs(n);
  if (abs !== 0 && abs < 0.01) return n.toExponential(1);
  if (abs >= 1000) return n.toLocaleString(undefined, { maximumFractionDigits: 0 });
  return n.toLocaleString(undefined, { maximumFractionDigits: abs < 10 ? 2 : 1 });
}

/** Title-case a raw method/cut token like "saute" or "cut_class" for display. */
export function humanize(token: string | null | undefined): string {
  if (!token) return '';
  return token.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
}
