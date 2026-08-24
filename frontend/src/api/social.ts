// Typed client for the social layer: votes, comments, Trending feed.
//
// Uses the shared `request<T>()` from `client.ts` — see the note there.
import { request } from './client';


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
