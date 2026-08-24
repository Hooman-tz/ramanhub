// Findings (forum threads) and the discovery feed.

import { request } from './client';

export type FindingEntryKind =
  | 'note'
  | 'figure'
  | 'spectra'
  | 'peaks'
  | 'pca'
  | 'hca'
  | 'attachment';

export interface FindingEntry {
  id: string;
  author_id: string;
  position: number;
  kind: FindingEntryKind;
  body_md: string | null;
  /** Analysis PARAMETERS, never a rendered image — the figure is recomputed
   * from live data on every view so it can't drift from what it claims to
   * show. */
  config: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
}

export interface MemberSpectrum {
  spectrum_id: string;
  accession: string | null;
  title: string | null;
  /** Overrides the spectrum's own title within this finding ("Control",
   * "Treated 24h") without renaming a record that belongs to its owner. */
  label: string | null;
  position: number;
  state: string;
}

export interface Finding {
  id: string;
  accession: string | null;
  owner_id: string;
  owner_handle: string | null;
  owner_display_name: string | null;
  owner_orcid: string | null;
  title: string;
  abstract_md: string | null;
  state: 'draft' | 'published';
  license_id: string | null;
  doi: string | null;
  publication_metadata: Record<string, unknown> | null;
  tags: string[] | null;
  published_at: string | null;
  created_at: string;
  updated_at: string;
  entries: FindingEntry[];
  spectra: MemberSpectrum[];
  vote_count: number;
  comment_count: number;
}

export async function listMyFindings(): Promise<Finding[]> {
  return request<Finding[]>('/findings');
}

export async function getFinding(id: string): Promise<Finding> {
  return request<Finding>(`/findings/${id}`);
}

export async function createFinding(payload: {
  title: string;
  abstract_md?: string;
  tags?: string[];
}): Promise<Finding> {
  return request<Finding>('/findings', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export async function updateFinding(
  id: string,
  payload: Partial<{ title: string; abstract_md: string; tags: string[]; doi: string }>,
): Promise<Finding> {
  return request<Finding>(`/findings/${id}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  });
}

export async function deleteFinding(id: string): Promise<void> {
  return request<void>(`/findings/${id}`, { method: 'DELETE' });
}

/** Publishing requires a license and at least one member spectrum, and
 * every member must itself be published — the backend rejects otherwise
 * with a message naming the offending accessions. */
export async function publishFinding(id: string, licenseId: string): Promise<Finding> {
  return request<Finding>(`/findings/${id}/publish`, {
    method: 'POST',
    body: JSON.stringify({ license_id: licenseId }),
  });
}

export async function attachSpectrum(
  findingId: string,
  spectrumId: string,
  label?: string,
): Promise<Finding> {
  return request<Finding>(`/findings/${findingId}/spectra`, {
    method: 'POST',
    body: JSON.stringify({ spectrum_id: spectrumId, label }),
  });
}

export async function detachSpectrum(
  findingId: string,
  spectrumId: string,
): Promise<Finding> {
  return request<Finding>(`/findings/${findingId}/spectra/${spectrumId}`, {
    method: 'DELETE',
  });
}

export async function appendEntry(
  findingId: string,
  payload: { kind: FindingEntryKind; body_md?: string; config?: Record<string, unknown> },
): Promise<Finding> {
  return request<Finding>(`/findings/${findingId}/entries`, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export async function updateEntry(
  findingId: string,
  entryId: string,
  payload: { body_md?: string; config?: Record<string, unknown> },
): Promise<Finding> {
  return request<Finding>(`/findings/${findingId}/entries/${entryId}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  });
}

export async function deleteEntry(findingId: string, entryId: string): Promise<Finding> {
  return request<Finding>(`/findings/${findingId}/entries/${entryId}`, {
    method: 'DELETE',
  });
}

/** Reorder by supplying the COMPLETE entry list in the desired order — a
 * partial list would leave positions ambiguous, and the backend rejects it. */
export async function reorderEntries(
  findingId: string,
  entryIds: string[],
): Promise<Finding> {
  return request<Finding>(`/findings/${findingId}/entries/reorder`, {
    method: 'POST',
    body: JSON.stringify({ entry_ids: entryIds }),
  });
}

// ---------------------------------------------------------------------------
// Feed
// ---------------------------------------------------------------------------

export interface FeedAuthor {
  id: string;
  handle: string | null;
  display_name: string | null;
  avatar_url: string | null;
  orcid_id: string | null;
}

export interface FeedItem {
  kind: 'finding' | 'spectrum';
  id: string;
  accession: string | null;
  title: string | null;
  summary: string | null;
  author: FeedAuthor | null;
  published_at: string | null;
  vote_count: number;
  comment_count: number;
  doi: string | null;
  tags: string[] | null;
  spectrum_count: number | null;
  material_type: string | null;
  snr: number | null;
  score: number;
}

export interface FeedOptions {
  kind?: 'all' | 'findings' | 'spectra';
  trust_tier?: 'doi_verified' | 'community';
  tag?: string;
  author?: string;
  limit?: number;
  offset?: number;
}

export async function getFeed(options: FeedOptions = {}): Promise<FeedItem[]> {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(options)) {
    if (value !== undefined && value !== null && value !== '') {
      params.set(key, String(value));
    }
  }
  const query = params.toString();
  return request<FeedItem[]>(`/feed${query ? `?${query}` : ''}`);
}

// ---------------------------------------------------------------------------
// Social on findings
// ---------------------------------------------------------------------------

export interface VoteStatus {
  count: number;
  voted_by_me: boolean;
}

export async function getFindingVotes(findingId: string): Promise<VoteStatus> {
  return request<VoteStatus>(`/findings/${findingId}/votes`);
}

export async function toggleFindingVote(
  findingId: string,
): Promise<{ voted: boolean; count: number }> {
  return request(`/findings/${findingId}/votes`, { method: 'POST' });
}

export interface FindingComment {
  id: number;
  finding_id: string | null;
  spectrum_id: string | null;
  parent_id: number | null;
  user_id: string;
  body: string;
  created_at: string;
  author_handle: string | null;
  author_display_name: string | null;
}

export async function listFindingComments(findingId: string): Promise<FindingComment[]> {
  return request<FindingComment[]>(`/findings/${findingId}/comments`);
}

export async function postFindingComment(
  findingId: string,
  body: string,
  parentId?: number,
): Promise<FindingComment> {
  return request<FindingComment>(`/findings/${findingId}/comments`, {
    method: 'POST',
    body: JSON.stringify({ body, parent_id: parentId ?? null }),
  });
}
