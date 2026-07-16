// Typed client for the NECTAR API. Every call goes to a relative `/api` base, proxied to the API
// in both dev (vite.config.ts) and prod (nginx.conf), so the browser never makes a cross-origin
// request. No clinical logic lives here; this only marshals JSON.

import type {
  AskRequest,
  AskResponse,
  ClinicalSnapshot,
  Condition,
  ConfirmResponse,
  DerivedConstraint,
  DeriveResponse,
  DishSummary,
  Guideline,
  NutrientInfo,
  RecipeDetail,
  RecommendResponse,
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
};
