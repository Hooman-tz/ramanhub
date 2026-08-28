// Thin typed fetch wrapper for the RamanHub API.
//
// ASSUMPTIONS: The backend is being built concurrently by other agents.
// Every interface/endpoint shape below is "best effort" based on the spec
// handed to the frontend agent, NOT confirmed against a live backend.
// Search for "ASSUMPTION:" comments for the specific spots most likely to
// need reconciliation once real backend responses are available.

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL;

// ---------------------------------------------------------------------------
// Shared types
// ---------------------------------------------------------------------------

export interface User {
  id: string;
  email: string;
  display_name?: string | null;
  avatar_url?: string;
  profile_handle?: string | null;
  bio?: string | null;
  affiliation?: string | null;
  research_interests?: string[] | null;
  is_profile_public?: boolean;
  orcid_id?: string | null;
  orcid_verified_at?: string | null;
  /** True for try-before-login guest sessions: can upload and process, but
   * publishing/votes/comments/profile linking need a full Google account. */
  is_guest?: boolean;
}

export interface RawFileUploadResponse {
  raw_file_id: string;
  ingestion_job_id: string;
  deduplicated: boolean;
}

export interface IngestionJob {
  id: string;
  raw_file_id: string;
  status: 'pending' | 'running' | 'succeeded' | 'failed';
  parser_used?: string | null;
  parser_version?: string | null;
  parser_confidence?: number | null;
  canonicalization_version?: string | null;
  // Generic bag of extracted metadata fields; shape varies by
  // modality/vendor, so we treat it as an untyped record and render it
  // generically rather than hardcoding field names.
  extracted_metadata_raw?: Record<string, unknown>;
  // Present once `confirmIngestionJob` has been called; null/absent before
  // that. Same shape as `extracted_metadata_raw` but user-reviewed.
  extracted_metadata_confirmed?: Record<string, unknown> | null;
  // ASSUMPTION: sanity_check_flags maps a field key (matching a key in
  // extracted_metadata_raw) to a human-readable flag reason. Could also be
  // an array of { field, reason } objects — adjust `SanityFlags` below if so.
  sanity_check_flags?: Record<string, string>;
  error_message?: string;
  attempt_count: number;
  max_attempts: number;
  draft_spectrum_id?: string | null;
}

export interface LedgerStep {
  type: 'raman.snv' | 'raman.msc' | 'raman.fluorescence_suppression.airpls' | string;
  version: string;
  params: Record<string, unknown>;
}

export interface Ledger {
  id: string;
  steps: LedgerStep[];
}

export interface Spectrum {
  id: string;
  title?: string;
  description?: string;
  state: 'draft' | 'published' | 'embargoed';
  is_owner?: boolean;
  raw_file_id?: string;
  confirmed_metadata?: Record<string, unknown> | null;
  quality_flags?: Record<string, string> | null;
  canonicalization_version?: string | null;
  parent_spectrum_id?: string | null;
  current_ledger?: Ledger;
  license_id?: string;
  embargo_release_at?: string | null;
  doi?: string | null;
  publish_readiness?: {
    ready: boolean;
    blockers: string[];
    warnings: string[];
    metadata_state: string;
    qc_state: string;
    doi_verification: string;
  };
  provenance?: {
    raw_file?: {
      id: string;
      filename: string;
      checksum_sha256: string;
      object_version?: string | null;
      checksum_verified_at?: string | null;
    } | null;
    ingestion?: {
      parser?: string | null;
      parser_version?: string | null;
      parser_confidence?: number | null;
      header_hash?: string | null;
      canonicalization_version?: string | null;
      confirmed_at?: string | null;
    } | null;
    processing?: {
      ledger_id: string;
      ledger_hash: string;
      schema_version: number;
      environment?: Record<string, unknown> | null;
    } | null;
    lineage?: { parent_spectrum_id?: string | null };
    publication?: {
      doi: string;
      provider: string;
      verification_status: string;
      verified_at: string;
      snapshot: Record<string, unknown>;
    } | null;
  };
  // Generic axes dump — charting is out of scope, a plain array/table is fine.
  wavenumbers?: number[];
  intensities?: number[];
}

export interface Routine {
  id: string;
  modality: string;
  name: string;
  description?: string;
  // Named steps_template to match the backend response exactly — these are
  // step templates (type/params/order), not an applied ledger's steps.
  steps_template: LedgerStep[];
}

export interface License {
  id: string;
  name: string;
  spdx_identifier?: string;
  url?: string;
}

// ---------------------------------------------------------------------------
// Low-level request helper
// ---------------------------------------------------------------------------

export async function apiRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE_URL}${path}`, {
    credentials: 'include', // httpOnly cookie auth
    ...init,
    headers: {
      ...(init?.body && !(init.body instanceof FormData)
        ? { 'Content-Type': 'application/json' }
        : {}),
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

  // Some endpoints (e.g. publish) may return 204 No Content.
  if (res.status === 204) return undefined as T;

  return (await res.json()) as T;
}

// ---------------------------------------------------------------------------
// Auth
// ---------------------------------------------------------------------------

/** Full-page redirect URL for "Sign in with Google" — navigate, don't fetch. */
export function getGoogleLoginUrl(): string {
  return `${API_BASE_URL}/auth/login`;
}

export function getOrcidLinkUrl(): string {
  return `${API_BASE_URL}/users/me/orcid/link`;
}

export async function getCurrentUser(): Promise<User> {
  return apiRequest<User>('/auth/session');
}

export async function updateCurrentUser(payload: Partial<Pick<User,
  'display_name' | 'profile_handle' | 'bio' | 'affiliation' | 'research_interests' | 'is_profile_public'
>>): Promise<User> {
  return apiRequest<User>('/users/me', { method: 'PATCH', body: JSON.stringify(payload) });
}

export async function exportCurrentUser(): Promise<unknown> {
  return apiRequest('/users/me/export');
}

export async function deleteCurrentUser(): Promise<void> {
  return apiRequest<void>('/users/me', { method: 'DELETE' });
}

/** Mint a guest session (server sets the same session cookie the OAuth flow
 * would). Signing in with Google later migrates the guest's work to the
 * real account. */
export async function startGuestSession(): Promise<User> {
  return apiRequest<User>('/auth/guest', { method: 'POST' });
}

// ---------------------------------------------------------------------------
// Upload / ingestion
// ---------------------------------------------------------------------------

export async function uploadRawFile(file: File): Promise<RawFileUploadResponse> {
  const formData = new FormData();
  formData.append('file', file);
  return apiRequest<RawFileUploadResponse>('/raw-files', {
    method: 'POST',
    body: formData,
  });
}

export async function getIngestionJob(jobId: string): Promise<IngestionJob> {
  return apiRequest<IngestionJob>(`/ingestion-jobs/${jobId}`);
}

export async function confirmIngestionJob(
  jobId: string,
  metadata: Record<string, unknown>,
): Promise<IngestionJob> {
  return apiRequest<IngestionJob>(`/ingestion-jobs/${jobId}`, {
    method: 'PATCH',
    // Backend wraps the edited metadata under a `metadata` key so it can
    // reuse ExtractedMetadata's strict pydantic validation directly.
    body: JSON.stringify({ metadata }),
  });
}

export async function retryIngestionJob(jobId: string): Promise<IngestionJob> {
  return apiRequest<IngestionJob>(`/ingestion-jobs/${jobId}/retry`, { method: 'POST' });
}

// ---------------------------------------------------------------------------
// Spectra / ledgers
// ---------------------------------------------------------------------------

export async function getSpectrum(id: string): Promise<Spectrum> {
  return apiRequest<Spectrum>(`/spectra/${id}`);
}

export async function createSpectrum(payload: {
  raw_file_id: string;
  current_ledger_id?: string;
  title?: string;
  description?: string;
  confirmed_metadata?: Record<string, unknown>;
  material_type?: string;
}): Promise<Spectrum> {
  return apiRequest<Spectrum>('/spectra', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export async function updateSpectrum(
  id: string,
  payload: Partial<{
    current_ledger_id: string;
    title: string;
    description: string;
    confirmed_metadata: Record<string, unknown>;
  }>,
): Promise<Spectrum> {
  return apiRequest<Spectrum>(`/spectra/${id}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  });
}

export interface CreateLedgerResponse {
  ledger: { schema_version: number; raw_file_id: string; steps: LedgerStep[] };
  ledger_id: string;
  ledger_hash: string;
  reused_existing: boolean;
  processed: { length: number };
}

export async function createLedger(
  rawFileId: string,
  steps: Array<{ type: string; params: Record<string, unknown>; order: number }>,
): Promise<CreateLedgerResponse> {
  return apiRequest<CreateLedgerResponse>(`/raw-files/${rawFileId}/ledgers`, {
    method: 'POST',
    body: JSON.stringify({ steps }),
  });
}

export async function getLicenses(): Promise<License[]> {
  return apiRequest<License[]>('/licenses');
}

/** Fork a readable spectrum into the caller's own workspace as a new draft
 * (copied raw file + replayed pipeline) — the way to experiment on public
 * spectra, since pipelines only attach to raw files you own. */
export async function forkSpectrum(id: string): Promise<Spectrum> {
  return apiRequest<Spectrum>(`/spectra/${id}/fork`, { method: 'POST' });
}

export async function publishSpectrum(
  id: string,
  payload: { license_id: string; embargo_release_at?: string | null },
): Promise<Spectrum> {
  return apiRequest<Spectrum>(`/spectra/${id}/publish`, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

/** Resolve and persist DOI evidence on a draft before it is labelled verified. */
export async function verifySpectrumDoi(id: string, doi: string): Promise<Spectrum> {
  return apiRequest<Spectrum>(`/spectra/${id}/doi/verify?doi=${encodeURIComponent(doi)}`, {
    method: 'POST',
  });
}

// ---------------------------------------------------------------------------
// Routines
// ---------------------------------------------------------------------------

export async function listRoutines(): Promise<Routine[]> {
  return apiRequest<Routine[]>('/routines');
}

export async function createRoutine(
  payload: Omit<Routine, 'id'>,
): Promise<Routine> {
  return apiRequest<Routine>('/routines', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export async function applyRoutineToRawFile(
  rawFileId: string,
  routineId: string,
): Promise<CreateLedgerResponse> {
  return apiRequest<CreateLedgerResponse>(`/raw-files/${rawFileId}/apply-routine/${routineId}`, {
    method: 'POST',
  });
}
