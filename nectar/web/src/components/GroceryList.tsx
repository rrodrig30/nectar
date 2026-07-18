import { useEffect, useMemo, useState } from 'react';
import { api } from '../api';
import type { PlanResponse } from '../types';

interface Props {
  plan: PlanResponse | null;
  onGoPlan: () => void;
}

interface GroceryItem {
  food: string;
  meals: number; // how many planned meals need this food
  dishes: string[]; // distinct dish titles that use it
}

// Aggregate the planned week into a shopping checklist. Ingredient amounts in this corpus are parsed
// and uncalibrated, so summing them would be misleading; instead each food is counted by how many
// planned meals need it (the quantity signal that is honest), with the dishes that use it.
export function GroceryList({ plan, onGoPlan }: Props): JSX.Element {
  const dishCounts = useMemo(() => {
    const counts = new Map<string, number>();
    if (plan) {
      for (const day of plan.days) {
        for (const meal of day.meals) counts.set(meal.dish_id, (counts.get(meal.dish_id) ?? 0) + 1);
      }
    }
    return counts;
  }, [plan]);

  const [items, setItems] = useState<GroceryItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [checked, setChecked] = useState<Set<string>>(new Set());

  useEffect(() => {
    if (dishCounts.size === 0) {
      setItems([]);
      return;
    }
    let live = true;
    setLoading(true);
    (async () => {
      const foods = new Map<string, GroceryItem>();
      await Promise.all(
        [...dishCounts.entries()].map(async ([dishId, occurrences]) => {
          let recipe;
          try {
            recipe = await api.recipe(dishId);
          } catch {
            return;
          }
          const dishTitle = recipe.title ?? dishId;
          for (const ing of recipe.ingredients) {
            const food = ing.food?.trim();
            if (!food) continue;
            const key = food.toLowerCase();
            const item = foods.get(key) ?? { food, meals: 0, dishes: [] };
            item.meals += occurrences;
            if (!item.dishes.includes(dishTitle)) item.dishes.push(dishTitle);
            foods.set(key, item);
          }
        }),
      );
      if (!live) return;
      const sorted = [...foods.values()].sort((a, b) => b.meals - a.meals || a.food.localeCompare(b.food));
      setItems(sorted);
      setLoading(false);
    })();
    return () => {
      live = false;
    };
  }, [dishCounts]);

  const toggle = (food: string): void =>
    setChecked((prev) => {
      const next = new Set(prev);
      if (next.has(food)) next.delete(food);
      else next.add(food);
      return next;
    });

  if (!plan) {
    return (
      <div className="card">
        <h2>Grocery list</h2>
        <p className="card-hint">
          The grocery list aggregates the ingredients across a generated weekly plan. Generate a meal
          plan first, then come back here for the shopping list.
        </p>
        <button className="btn-primary" onClick={onGoPlan}>
          Go to Meal planner
        </button>
      </div>
    );
  }

  const remaining = items.length - checked.size;

  return (
    <div className="card">
      <div className="card-title-row">
        <h2>Grocery list</h2>
        {items.length > 0 && (
          <span className="meta-chip">
            {remaining} of {items.length} left
          </span>
        )}
      </div>
      <p className="card-hint">
        Every food the planned week needs, across {dishCounts.size} dish
        {dishCounts.size === 1 ? '' : 'es'}. The count is how many planned meals use each food.
        Amounts are not summed: the corpus quantities are parsed and uncalibrated, so this is a
        shopping checklist, not a quantified order.
      </p>

      {loading && <p className="spinner">Assembling the list…</p>}

      {!loading && items.length === 0 && (
        <p className="muted">No resolved ingredients in the planned dishes.</p>
      )}

      {items.length > 0 && (
        <ul className="grocery-list">
          {items.map((it) => (
            <li key={it.food} className={checked.has(it.food) ? 'grocery-item done' : 'grocery-item'}>
              <label>
                <input
                  type="checkbox"
                  checked={checked.has(it.food)}
                  onChange={() => toggle(it.food)}
                />
                <span className="grocery-food">{it.food}</span>
                <span className="grocery-count" title="planned meals needing this">
                  &times;{it.meals}
                </span>
                <span className="grocery-dishes">{it.dishes.join(', ')}</span>
              </label>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
