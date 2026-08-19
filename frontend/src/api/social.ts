// Typed client for Module 4b's social layer (votes, comments, Trending
// feed). `client.ts` doesn't export its `request<T>()` helper, so this is a
// small local fetch wrapper following the exact same pattern (same base
// URL env var, same `credentials: 'include'` cookie-auth convention, same
// error-shape unwrapping) rather than editing `client.ts`.
//
// ASSUMPTIONS: the backend for this module is authored by this same pass,
// but is still "best effort" relative to what the eventual integration
// point (SpectrumViewPage) expects — reconcile field names if needed.

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL;

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE_URL}${path}`, {
    credentials: 'include',
    ...init,
    headers: {
      ...(init?.body ? { 'Content-Type': 'application/json' } : {}),
      ...init?.headers,
    },
  });

  if (!res.ok) {
    let detail: string | undefined;
    try {
      const body = await res.json();
      detail = body?.detail ?? body?.message ?? JSON.stringify(body);
    } catch {
      detail = await res.text().catch(() => undefined);
    }
    throw new Error(`API error ${res.status}: ${detail ?? res.statusText}`);
  }

  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

// ---------------------------------------------------------------------------
// Votes
// ---------------------------------------------------------------------------

export interface VoteToggleResult {
  voted: boolean;
  count: number;
}

export interface VoteStatus {
  count: number;
  voted_by_me: boolean;
}

/** Toggles the current user's vote on a spectrum (on -> off, off -> on). */
export async function toggleVote(spectrumId: string): Promise<VoteToggleResult> {
  return request<VoteToggleResult>(`/spectra/${spectrumId}/votes`, { method: 'POST' });
}

export async function getVotes(spectrumId: string): Promise<VoteStatus> {
  return request<VoteStatus>(`/spectra/${spectrumId}/votes`);
}

// ---------------------------------------------------------------------------
// Comments
// ---------------------------------------------------------------------------

export interface Comment {
  id: number;
  spectrum_id: string;
  user_id: string;
  body: string;
  created_at: string;
}

export async function listComments(
  spectrumId: string,
  params?: { limit?: number; offset?: number },
): Promise<Comment[]> {
  const query = new URLSearchParams();
  if (params?.limit !== undefined) query.set('limit', String(params.limit));
  if (params?.offset !== undefined) query.set('offset', String(params.offset));
  const qs = query.toString();
  return request<Comment[]>(`/spectra/${spectrumId}/comments${qs ? `?${qs}` : ''}`);
}

export async function postComment(spectrumId: string, body: string): Promise<Comment> {
  return request<Comment>(`/spectra/${spectrumId}/comments`, {
    method: 'POST',
    body: JSON.stringify({ body }),
  });
}

// ---------------------------------------------------------------------------
// Trending
// ---------------------------------------------------------------------------

export interface TrendingItem {
  id: string;
  title?: string | null;
  owner_id: string;
  published_at?: string | null;
  vote_count: number;
}

export async function getTrending(params?: {
  limit?: number;
  offset?: number;
  window_days?: number;
}): Promise<TrendingItem[]> {
  const query = new URLSearchParams();
  if (params?.limit !== undefined) query.set('limit', String(params.limit));
  if (params?.offset !== undefined) query.set('offset', String(params.offset));
  if (params?.window_days !== undefined) query.set('window_days', String(params.window_days));
  const qs = query.toString();
  return request<TrendingItem[]>(`/trending${qs ? `?${qs}` : ''}`);
}
