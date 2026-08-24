// Thin typed fetch wrapper for the RamanHub API.
//
// Shapes here are confirmed against the live backend. `request` and
// `API_BASE_URL` are exported so the feature-specific API modules
// (analysis, findings, feed, export) share one error-handling and
// credentials policy rather than each rolling its own fetch.

export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL;

// ---------------------------------------------------------------------------
// Shared types
// ---------------------------------------------------------------------------

export interface User {
  id: string;
  email: string;
  /** Public URL handle — `/u/<handle>`. Null for guest sessions, which
   * have no public profile. */
  handle?: string | null;
  name?: string;
  display_name?: string | null;
  avatar_url?: string;
  orcid_id?: string | null;
  affiliation?: string | null;
  bio?: string | null;
  /** True for try-before-login guest sessions: can upload and process, but
   * publishing/votes/comments/profile linking need a full Google account. */
  is_guest?: boolean;
}

export interface RawFileUploadResponse {
  raw_file_id: string;
  ingestion_job_id: string;
}

export interface IngestionJob {
  id: string;
  raw_file_id: string;
  status: 'pending' | 'running' | 'succeeded' | 'failed';
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
  /** Human-quotable public identifier, e.g. RH-S-000042 — what a paper
   * cites, as opposed to `id`, which is what links point at internally. */
  accession?: string | null;
  title?: string;
  description?: string;
  state: 'draft' | 'published' | 'embargoed';
  owner_id?: string;
  raw_file_id?: string;
  current_ledger?: Ledger;
  license_id?: string;
  doi?: string | null;
  material_type?: string | null;
  snr?: number | null;
  published_at?: string | null;
  embargo_release_at?: string | null;
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

export async function request<T>(path: string, init?: RequestInit): Promise<T> {
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

export async function getCurrentUser(): Promise<User> {
  return request<User>('/users/me');
}

/** Mint a guest session (server sets the same session cookie the OAuth flow
 * would). Signing in with Google later migrates the guest's work to the
 * real account. */
export async function startGuestSession(): Promise<User> {
  return request<User>('/auth/guest', { method: 'POST' });
}

// ---------------------------------------------------------------------------
// Upload / ingestion
// ---------------------------------------------------------------------------

export async function uploadRawFile(file: File): Promise<RawFileUploadResponse> {
  const formData = new FormData();
  formData.append('file', file);
  return request<RawFileUploadResponse>('/raw-files', {
    method: 'POST',
    body: formData,
  });
}

export async function getIngestionJob(jobId: string): Promise<IngestionJob> {
  return request<IngestionJob>(`/ingestion-jobs/${jobId}`);
}

export async function confirmIngestionJob(
  jobId: string,
  metadata: Record<string, unknown>,
): Promise<IngestionJob> {
  return request<IngestionJob>(`/ingestion-jobs/${jobId}`, {
    method: 'PATCH',
    // Backend wraps the edited metadata under a `metadata` key so it can
    // reuse ExtractedMetadata's strict pydantic validation directly.
    body: JSON.stringify({ metadata }),
  });
}

// ---------------------------------------------------------------------------
// Spectra / ledgers
// ---------------------------------------------------------------------------

export async function getSpectrum(id: string): Promise<Spectrum> {
  return request<Spectrum>(`/spectra/${id}`);
}

export async function createSpectrum(payload: {
  raw_file_id: string;
  current_ledger_id?: string;
  title?: string;
  description?: string;
  confirmed_metadata?: Record<string, unknown>;
  material_type?: string;
}): Promise<Spectrum> {
  return request<Spectrum>('/spectra', {
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
  return request<Spectrum>(`/spectra/${id}`, {
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
  return request<CreateLedgerResponse>(`/raw-files/${rawFileId}/ledgers`, {
    method: 'POST',
    body: JSON.stringify({ steps }),
  });
}

export async function getLicenses(): Promise<License[]> {
  return request<License[]>('/licenses');
}

/** Fork a readable spectrum into the caller's own workspace as a new draft
 * (copied raw file + replayed pipeline) — the way to experiment on public
 * spectra, since pipelines only attach to raw files you own. */
export async function forkSpectrum(id: string): Promise<Spectrum> {
  return request<Spectrum>(`/spectra/${id}/fork`, { method: 'POST' });
}

export async function publishSpectrum(
  id: string,
  payload: { license_id: string; embargo_release_at?: string | null; doi?: string | null },
): Promise<Spectrum> {
  return request<Spectrum>(`/spectra/${id}/publish`, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

// ---------------------------------------------------------------------------
// Routines
// ---------------------------------------------------------------------------

export async function listRoutines(): Promise<Routine[]> {
  return request<Routine[]>('/routines');
}

export async function createRoutine(
  payload: Omit<Routine, 'id'>,
): Promise<Routine> {
  return request<Routine>('/routines', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export async function applyRoutineToRawFile(
  rawFileId: string,
  routineId: string,
): Promise<Ledger> {
  return request<Ledger>(`/raw-files/${rawFileId}/apply-routine/${routineId}`, {
    method: 'POST',
  });
}

// ---------------------------------------------------------------------------
// Profile
// ---------------------------------------------------------------------------

export interface PublicProfile {
  id: string;
  handle: string | null;
  display_name: string | null;
  avatar_url: string | null;
  orcid_id: string | null;
  affiliation: string | null;
  bio: string | null;
  created_at: string;
  spectrum_count: number;
  finding_count: number;
}

/** A contributor's public profile. Deliberately a different shape from
 * `User` — it carries no email. */
export async function getPublicProfile(handle: string): Promise<PublicProfile> {
  return request<PublicProfile>(`/users/by-handle/${encodeURIComponent(handle)}`);
}

export async function updateMyProfile(payload: {
  display_name?: string;
  handle?: string;
  orcid_id?: string;
  affiliation?: string;
  bio?: string;
}): Promise<User> {
  return request<User>('/users/me', {
    method: 'PATCH',
    body: JSON.stringify(payload),
  });
}
