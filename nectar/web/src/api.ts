// Typed client for the NECTAR API. Every call goes to a relative `/api` base, proxied to the API
// in both dev (vite.config.ts) and prod (nginx.conf), so the browser never makes a cross-origin
// request. No clinical logic lives here; this only marshals JSON.

import type {
  AskRequest,
  AskResponse,
  BrowseDish,
  ClinicalSnapshot,
  Condition,
  ConfirmResponse,
  DerivedConstraint,
  DeriveResponse,
  DishSummary,
  Guideline,
  NutrientInfo,
  PlanRequest,
  PlanResponse,
  RecipeDetail,
  RecommendResponse,
  Settings,
  SettingsUpdate,
} from './types';

const BASE: string = import.meta.env.VITE_API_BASE ?? '/api';

/** An API error carrying the HTTP status and the server's `detail`, so the UI can show it. */
export class ApiError extends Error {
  constructor(public readonly status: number, message: string) {
    super(message);
    this.name = 'ApiError';
  }
}

async function toError(res: Response): Promise<ApiError> {
  let detail: string = res.statusText;
  try {
    const body: unknown = await res.json();
    if (body && typeof body === 'object' && 'detail' in body) {
      const d = (body as { detail: unknown }).detail;
      detail = typeof d === 'string' ? d : JSON.stringify(d);
    }
  } catch {
    // non-JSON error body; keep the status text
  }
  return new ApiError(res.status, detail);
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, init);
  if (!res.ok) throw await toError(res);
  return (await res.json()) as T;
}

function postJson<T>(path: string, body: unknown): Promise<T> {
  return request<T>(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
}

export const api = {
  /** POST /profile/derive - snapshot in, deterministically derived (unconfirmed) constraints out. */
  derive(snapshot: ClinicalSnapshot): Promise<DeriveResponse> {
    return postJson<DeriveResponse>('/profile/derive', snapshot);
  },

  /** POST /profile/confirm - apply per-index approvals/overrides; only approved entries come back. */
  confirm(
    constraints: DerivedConstraint[],
    approvals: Record<number, boolean>,
    overrides?: Record<number, DerivedConstraint>,
  ): Promise<ConfirmResponse> {
    return postJson<ConfirmResponse>('/profile/confirm', { constraints, approvals, overrides });
  },

  /** POST /recommend - confirmed constraints + conditions + dishes in, ranked dishes out. */
  recommend(
    confirmed: DerivedConstraint[],
    conditionIds: string[],
    dishIds: string[],
  ): Promise<RecommendResponse> {
    return postJson<RecommendResponse>('/recommend', {
      confirmed,
      condition_ids: conditionIds,
      dish_ids: dishIds,
    });
  },

  /** GET /dishes/search - dishes whose name contains `q` (case-insensitive), bounded by `limit`. */
  searchDishes(q: string, limit = 20): Promise<DishSummary[]> {
    return request<DishSummary[]>(
      `/dishes/search?q=${encodeURIComponent(q)}&limit=${limit}`,
    );
  },

  /**
   * GET /dishes/browse - the recipe browser. Full-text name match `q`, refined by per-serving
   * nutrient `ceilings` (`{nutrient: max_mg}`, a dish qualifies when a version is at/under it),
   * sorted by `sort` (a nutrient_id, ascending median) or name relevance. Returns dishes with their
   * per-nutrient version spread.
   */
  browseDishes(
    q: string,
    ceilings: Record<string, number> = {},
    sort = '',
    limit = 30,
    offset = 0,
  ): Promise<BrowseDish[]> {
    const params = new URLSearchParams();
    params.set('q', q);
    for (const [nutrient, mg] of Object.entries(ceilings)) params.append('max', `${nutrient}:${mg}`);
    if (sort) params.set('sort', sort);
    params.set('limit', String(limit));
    params.set('offset', String(offset));
    return request<BrowseDish[]>(`/dishes/browse?${params.toString()}`);
  },

  /** POST /plan/week - a weekly meal plan over a supplied admissible meal pool with envelopes. */
  planWeek(req: PlanRequest): Promise<PlanResponse> {
    return postJson<PlanResponse>('/plan/week', req);
  },

  /** GET /conditions - every condition in the knowledge base, for the selector. */
  conditions(): Promise<Condition[]> {
    return request<Condition[]>('/conditions');
  },

  /** GET /guidelines - guideline passages for the given ids (unresolved ids are omitted). */
  guidelines(ids: string[]): Promise<Guideline[]> {
    if (ids.length === 0) return Promise.resolve([]);
    const qs = ids.map((id) => `ids=${encodeURIComponent(id)}`).join('&');
    return request<Guideline[]>(`/guidelines?${qs}`);
  },

  /** GET /nutrients - the nutrient vocabulary (id, name, unit) for labeling values. */
  nutrients(): Promise<NutrientInfo[]> {
    return request<NutrientInfo[]>('/nutrients');
  },

  /** GET /recipe - the primary recipe (title, servings, ingredients + preparation) for a dish. */
  recipe(dishId: string): Promise<RecipeDetail> {
    return request<RecipeDetail>(`/recipe?dish_id=${encodeURIComponent(dishId)}`);
  },

  /** POST /ask - natural-language question, grounded within the current ranking's dishes. */
  ask(req: AskRequest): Promise<AskResponse> {
    return postJson<AskResponse>('/ask', req);
  },

  /** GET /settings - the effective runtime settings (config defaults + operator overrides). */
  getSettings(): Promise<Settings> {
    return request<Settings>('/settings');
  },

  /** PUT /settings - apply an operator override; returns the new effective settings. */
  putSettings(update: SettingsUpdate): Promise<Settings> {
    return request<Settings>('/settings', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(update),
    });
  },

  /** DELETE /settings - drop overrides, return to config defaults. */
  resetSettings(): Promise<Settings> {
    return request<Settings>('/settings', { method: 'DELETE' });
  },

  /** GET /settings/models - models available from the active backend (empty if none discoverable). */
  models(): Promise<string[]> {
    return request<string[]>('/settings/models');
  },
};
