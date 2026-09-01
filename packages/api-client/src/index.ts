/**
 * Typed REST client for the RamanHub / Spectra Insight FastAPI backend.
 *
 * Both `apps/web` and `apps/mobile` import this — it is the single seam
 * between the TypeScript frontend and the Python API, which keeps the
 * server's language invisible to the apps (see the plan's "future Go split").
 *
 * Transport:
 *   - browser  -> relative `/api/*` (Next.js rewrites to the API; the
 *     `samesite=lax` session cookie rides along)
 *   - server / React Native -> absolute `API_URL`
 */

const isBrowser = typeof globalThis !== "undefined" && "window" in globalThis;

/** Base URL for API calls. Override per-call via {@link ApiClientOptions.baseUrl}. */
export function resolveBaseUrl(explicit?: string): string {
  if (explicit) return explicit.replace(/\/$/, "");
  if (isBrowser) return "/api";
  // Server components / RN. `process` is available in both node and Metro.
  const fromEnv =
    typeof process !== "undefined" ? process.env.API_URL : undefined;
  return (fromEnv ?? "http://127.0.0.1:8000").replace(/\/$/, "");
}

export interface ApiError {
  status: number;
  message: string;
  body?: unknown;
}

export function isApiError(e: unknown): e is ApiError {
  return typeof e === "object" && e !== null && "status" in e && "message" in e;
}

export interface ApiClientOptions {
  /** Override the resolved base URL. */
  baseUrl?: string;
  /** Bearer token for React Native (web uses the cookie instead). */
  token?: string;
}

export interface RequestOptions extends ApiClientOptions {
  method?: "GET" | "POST" | "PATCH" | "PUT" | "DELETE";
  /**
   * Request body. A `FormData` instance is sent as-is (multipart, the
   * browser sets the boundary); anything else is JSON-serialized.
   */
  body?: unknown;
  /** Extra query params. */
  query?: Record<string, string | number | boolean | undefined>;
  headers?: Record<string, string>;
  signal?: AbortSignal;
}

export async function apiRequest<T>(
  path: string,
  opts: RequestOptions = {},
): Promise<T> {
  const base = resolveBaseUrl(opts.baseUrl);
  const rel = path.startsWith("/") ? path : `/${path}`;
  const qs = opts.query
    ? "?" +
      new URLSearchParams(
        Object.entries(opts.query)
          .filter(([, v]) => v !== undefined)
          .map(([k, v]) => [k, String(v)] as [string, string]),
      ).toString()
    : "";

  const isFormBody =
    typeof FormData !== "undefined" && opts.body instanceof FormData;

  const res = await fetch(`${base}${rel}${qs}`, {
    method: opts.method ?? "GET",
    credentials: "include",
    signal: opts.signal,
    headers: {
      ...(opts.body !== undefined && !isFormBody
        ? { "content-type": "application/json" }
        : {}),
      ...(opts.token ? { authorization: `Bearer ${opts.token}` } : {}),
      ...opts.headers,
    },
    body:
      opts.body === undefined
        ? undefined
        : isFormBody
          ? (opts.body as FormData)
          : JSON.stringify(opts.body),
  });

  if (!res.ok) {
    let message = `API error ${res.status}`;
    let body: unknown;
    try {
      body = await res.json();
      const b = body as { detail?: string; message?: string };
      message = b.detail ?? b.message ?? message;
    } catch {
      /* non-JSON error body */
    }
    const err: ApiError = { status: res.status, message, body };
    // Deliberately a plain structured value, not an Error subclass — callers
    // discriminate it with `isApiError`, and RN/Next both preserve the shape.
    // eslint-disable-next-line @typescript-eslint/only-throw-error
    throw err;
  }

  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

/* -------------------------------------------------------------------------- */
/* Endpoints                                                                   */
/* -------------------------------------------------------------------------- */

export interface HealthResponse {
  status: string;
  environment: string;
}

/** `GET /health` — liveness probe, used by the M0 smoke test. */
export function getHealth(opts?: ApiClientOptions): Promise<HealthResponse> {
  return apiRequest<HealthResponse>("/health", opts);
}

/* --- auth / session -------------------------------------------------------- */

export interface SessionUser {
  id: string;
  email: string | null;
  display_name: string | null;
  avatar_url: string | null;
  profile_handle: string | null;
  orcid_id: string | null;
  is_guest: boolean;
  onboarded_at: string | null;
  is_profile_public?: boolean;
}

/** Current user, or `null` when not signed in (never throws on 401). */
export async function getSession(
  opts?: ApiClientOptions,
): Promise<SessionUser | null> {
  try {
    return await apiRequest<SessionUser | null>("/auth/session", opts);
  } catch (e) {
    if (isApiError(e) && e.status === 401) return null;
    throw e;
  }
}

/** Mint an anonymous guest session (cookie set by the response). */
export function startGuestSession(
  opts?: ApiClientOptions,
): Promise<SessionUser> {
  return apiRequest<SessionUser>("/auth/guest", { ...opts, method: "POST" });
}

/** Clear the session cookie. */
export function logout(opts?: ApiClientOptions): Promise<unknown> {
  return apiRequest<unknown>("/auth/logout", { ...opts, method: "POST" });
}

export function googleLoginUrl(base = "/api"): string {
  return `${base.replace(/\/$/, "")}/auth/login`;
}

export function githubLoginUrl(base = "/api"): string {
  return `${base.replace(/\/$/, "")}/auth/github/login`;
}

export function orcidLoginUrl(base = "/api"): string {
  return `${base.replace(/\/$/, "")}/auth/orcid/login`;
}

/* --- feed ---------------------------------------------------------------- */

export interface FeedAuthor {
  id: string;
  handle: string | null;
  display_name: string | null;
  avatar_url: string | null;
  orcid_id: string | null;
}

export interface FeedItem {
  kind: "finding" | "spectrum";
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

export interface FeedParams {
  kind?: "all" | "findings" | "spectra";
  filter?: "all" | "following";
  tag?: string;
  author?: string;
  trust_tier?: "doi_verified" | "community";
  limit?: number;
  offset?: number;
}

export function getFeed(
  params: FeedParams = {},
  opts?: ApiClientOptions,
): Promise<FeedItem[]> {
  return apiRequest<FeedItem[]>("/v1/feed", { ...opts, query: { ...params } });
}

/* --- findings ---------------------------------------------------------------- */

export interface FindingEntry {
  id: string;
  author_id: string;
  position: number;
  kind: string;
  body_md: string | null;
  config: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
}

export interface MemberSpectrum {
  spectrum_id: string;
  accession: string | null;
  title: string | null;
  label: string | null;
  position: number;
  state: string;
}

/** AI-generated abstract digest, cached on `publication_metadata`. */
export interface AiSummary {
  summary: string;
  keywords: string[];
}

/**
 * Cached paper metadata on a Finding, populated at DOI-link time from
 * Crossref + the SCImago journal table (see `POST /v1/findings/{id}/link-doi`).
 * `resolved` is `false` when Crossref couldn't find the DOI — only `doi` is
 * then meaningful.
 */
export interface PublicationMeta {
  doi: string;
  title?: string | null;
  authors?: string[];
  journal?: string | null;
  issn?: string[];
  year?: number | null;
  url?: string | null;
  resolved: boolean;
  citations?: number | null;
  quartile?: string | null;
  sjr?: number | null;
  cover_url?: string | null;
  abstract_raw?: string | null;
  ai_summary?: AiSummary | null;
}

export interface FindingImage {
  id: string;
  kind: "figure" | "graphical_abstract";
  caption: string | null;
  position: number;
  content_type: string;
  /** Relative API path, e.g. `/v1/findings/{id}/images/{image_id}/file`. */
  url: string;
  created_at: string;
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
  state: "draft" | "published";
  license_id: string | null;
  doi: string | null;
  /** Optional link to the code/analysis repo behind the write-up (e.g. a GitHub repo). Not verified. */
  repo_url: string | null;
  publication_metadata: PublicationMeta | null;
  tags: string[] | null;
  published_at: string | null;
  created_at: string;
  updated_at: string;
  entries: FindingEntry[];
  spectra: MemberSpectrum[];
  images: FindingImage[];
  vote_count: number;
  comment_count: number;
}

export function getFinding(
  id: string,
  opts?: ApiClientOptions,
): Promise<Finding> {
  return apiRequest<Finding>(`/v1/findings/${id}`, opts);
}

export function listMyFindings(opts?: ApiClientOptions): Promise<Finding[]> {
  return apiRequest<Finding[]>("/v1/findings", opts);
}

export function createFinding(
  body: {
    title: string;
    abstract_md?: string;
    tags?: string[];
    repo_url?: string;
  },
  opts?: ApiClientOptions,
): Promise<Finding> {
  return apiRequest<Finding>("/v1/findings", { ...opts, method: "POST", body });
}

/** `PATCH /v1/findings/{id}` — edit an owned finding's title / abstract / tags / doi / repo_url. */
export function updateFinding(
  id: string,
  body: {
    title?: string;
    abstract_md?: string;
    tags?: string[];
    doi?: string;
    repo_url?: string;
  },
  opts?: ApiClientOptions,
): Promise<Finding> {
  return apiRequest<Finding>(`/v1/findings/${encodeURIComponent(id)}`, {
    ...opts,
    method: "PATCH",
    body,
  });
}

export function publishFinding(
  id: string,
  license_id = "CC-BY-4.0",
  opts?: ApiClientOptions,
): Promise<Finding> {
  return apiRequest<Finding>(`/v1/findings/${id}/publish`, {
    ...opts,
    method: "POST",
    body: { license_id },
  });
}

/** Create a draft note and immediately publish it — the one-tap "post". */
export async function postNote(
  body: { title: string; abstract_md?: string; tags?: string[] },
  opts?: ApiClientOptions,
): Promise<Finding> {
  const draft = await createFinding(body, opts);
  return publishFinding(draft.id, "CC-BY-4.0", opts);
}

/* --- social: follow graph ------------------------------------------------- */

export interface FollowUser {
  id: string;
  handle: string;
  display_name: string | null;
  avatar_url: string | null;
  affiliation: string | null;
}

export interface FollowStatus {
  following: boolean;
  follower_count: number;
}

export interface ListParams {
  limit?: number;
  offset?: number;
}

/** `GET /users/{handle}/follow` — auth optional. */
export function getFollowStatus(
  handle: string,
  opts?: ApiClientOptions,
): Promise<FollowStatus> {
  return apiRequest<FollowStatus>(
    `/users/${encodeURIComponent(handle)}/follow`,
    opts,
  );
}

/** `POST /users/{handle}/follow` — toggle. Guests get 403. */
export function toggleFollow(
  handle: string,
  opts?: ApiClientOptions,
): Promise<FollowStatus> {
  return apiRequest<FollowStatus>(
    `/users/${encodeURIComponent(handle)}/follow`,
    { ...opts, method: "POST" },
  );
}

/** `GET /users/{handle}/followers`. */
export function listFollowers(
  handle: string,
  params: ListParams = {},
  opts?: ApiClientOptions,
): Promise<FollowUser[]> {
  return apiRequest<FollowUser[]>(
    `/users/${encodeURIComponent(handle)}/followers`,
    { ...opts, query: { ...params } },
  );
}

/** `GET /users/{handle}/following`. */
export function listFollowing(
  handle: string,
  params: ListParams = {},
  opts?: ApiClientOptions,
): Promise<FollowUser[]> {
  return apiRequest<FollowUser[]>(
    `/users/${encodeURIComponent(handle)}/following`,
    { ...opts, query: { ...params } },
  );
}

/* --- social: finding votes / shares ------------------------------------- */

export interface FindingVotes {
  count: number;
  voted_by_me: boolean;
}

export interface ToggleVoteResult {
  voted: boolean;
  count: number;
}

export interface FindingShares {
  count: number;
  shared_by_me: boolean;
}

export interface ToggleShareResult {
  shared: boolean;
  count: number;
}

/** `GET /findings/{id}/votes`. */
export function getFindingVotes(
  id: string,
  opts?: ApiClientOptions,
): Promise<FindingVotes> {
  return apiRequest<FindingVotes>(
    `/findings/${encodeURIComponent(id)}/votes`,
    opts,
  );
}

/** `POST /findings/{id}/votes` — toggle. */
export function toggleFindingVote(
  id: string,
  opts?: ApiClientOptions,
): Promise<ToggleVoteResult> {
  return apiRequest<ToggleVoteResult>(
    `/findings/${encodeURIComponent(id)}/votes`,
    { ...opts, method: "POST" },
  );
}

/** `GET /findings/{id}/shares`. */
export function getFindingShares(
  id: string,
  opts?: ApiClientOptions,
): Promise<FindingShares> {
  return apiRequest<FindingShares>(
    `/findings/${encodeURIComponent(id)}/shares`,
    opts,
  );
}

/** `POST /findings/{id}/shares` — toggle. */
export function toggleFindingShare(
  id: string,
  opts?: ApiClientOptions,
): Promise<ToggleShareResult> {
  return apiRequest<ToggleShareResult>(
    `/findings/${encodeURIComponent(id)}/shares`,
    { ...opts, method: "POST" },
  );
}

/* --- social: finding comments ----------------------------------------- */

export interface FindingComment {
  id: number;
  spectrum_id: string | null;
  finding_id: string | null;
  parent_id: number | null;
  user_id: string;
  body: string;
  created_at: string;
  author_handle: string | null;
  author_display_name: string | null;
}

/** `GET /findings/{id}/comments` — oldest → newest. */
export function listFindingComments(
  id: string,
  opts?: ApiClientOptions,
): Promise<FindingComment[]> {
  return apiRequest<FindingComment[]>(
    `/findings/${encodeURIComponent(id)}/comments`,
    opts,
  );
}

/** `POST /findings/{id}/comments`. */
export function postFindingComment(
  id: string,
  body: { body: string; parent_id?: number },
  opts?: ApiClientOptions,
): Promise<FindingComment> {
  return apiRequest<FindingComment>(
    `/findings/${encodeURIComponent(id)}/comments`,
    { ...opts, method: "POST", body },
  );
}

/* --- onboarding ------------------------------------------------------- */

export interface HandleAvailability {
  available: boolean;
  normalized: string;
  reason: string | null;
}

export interface SuggestedUser {
  id: string;
  profile_handle: string;
  display_name: string | null;
  avatar_url: string | null;
  affiliation: string | null;
  follower_count: number;
}

export interface OnboardingBody {
  handle: string;
  display_name: string;
  interests: string[];
  is_profile_public: boolean;
}

/** `GET /v1/users/handle-available?handle=` — no auth. */
export function checkHandle(
  handle: string,
  opts?: ApiClientOptions,
): Promise<HandleAvailability> {
  return apiRequest<HandleAvailability>("/v1/users/handle-available", {
    ...opts,
    query: { handle },
  });
}

/** `GET /v1/users/suggested?limit=` — auth optional. */
export function getSuggestedUsers(
  limit = 10,
  opts?: ApiClientOptions,
): Promise<SuggestedUser[]> {
  return apiRequest<SuggestedUser[]>("/v1/users/suggested", {
    ...opts,
    query: { limit },
  });
}

/** `POST /v1/users/me/onboarding` — full account only. */
export function submitOnboarding(
  body: OnboardingBody,
  opts?: ApiClientOptions,
): Promise<SessionUser> {
  return apiRequest<SessionUser>("/v1/users/me/onboarding", {
    ...opts,
    method: "POST",
    body,
  });
}

/* --- public profile ------------------------------------------------- */

export interface PublicProfile {
  id: string;
  display_name: string | null;
  avatar_url: string | null;
  orcid_id: string | null;
  orcid_verified: boolean;
  profile_handle: string | null;
  bio: string | null;
  affiliation: string | null;
  research_interests: string[] | null;
  followers: number;
  following: number;
  spectrum_count: number;
  finding_count: number;
  doi_linked: number;
  votes_received: number;
  shares_received: number;
  comments_written: number;
  reuse_findings: number;
  reuse_groups: number;
  created_at: string;
}

/** `GET /users/by-handle/{handle}` — 404 if missing / guest / inactive. */
export function getUserByHandle(
  handle: string,
  opts?: ApiClientOptions,
): Promise<PublicProfile> {
  return apiRequest<PublicProfile>(
    `/users/by-handle/${encodeURIComponent(handle)}`,
    opts,
  );
}

/* --- profile: contribution activity ----------------------------------- */

export interface ActivityDay {
  date: string;
  spectra: number;
  findings: number;
  comments: number;
}

export interface UserActivity {
  days: ActivityDay[];
  total: number;
  current_streak: number;
  longest_streak: number;
}

/** `GET /users/{handle}/activity?days=` — no auth. `days` is `1..730`. */
export function getUserActivity(
  handle: string,
  days?: number,
  opts?: ApiClientOptions,
): Promise<UserActivity> {
  return apiRequest<UserActivity>(
    `/users/${encodeURIComponent(handle)}/activity`,
    { ...opts, query: { days } },
  );
}

/* --- profile: pinned items ------------------------------------------- */

export interface Pin {
  kind: "spectrum" | "finding";
  id: string;
  accession: string | null;
  title: string | null;
  position: number;
}

/** `GET /users/{handle}/pins` — no auth. */
export function getUserPins(
  handle: string,
  opts?: ApiClientOptions,
): Promise<Pin[]> {
  return apiRequest<Pin[]>(`/users/${encodeURIComponent(handle)}/pins`, opts);
}

/** `POST /pins` — full account. Returns the caller's full pin list. */
export function addPin(
  body: { kind: "spectrum" | "finding"; id: string },
  opts?: ApiClientOptions,
): Promise<Pin[]> {
  return apiRequest<Pin[]>("/pins", { ...opts, method: "POST", body });
}

/** `DELETE /pins/{kind}/{item_id}` — full account. Returns the remaining pins. */
export function removePin(
  kind: "spectrum" | "finding",
  id: string,
  opts?: ApiClientOptions,
): Promise<Pin[]> {
  return apiRequest<Pin[]>(`/pins/${kind}/${encodeURIComponent(id)}`, {
    ...opts,
    method: "DELETE",
  });
}

/* --- private reference library ------------------------------------- */

export interface LibrarySpectrum {
  id: string;
  title: string | null;
  material_type: string | null;
  excitation_wavelength_nm: number | null;
  snr: number | null;
  modality: string;
  doi: string | null;
  published_at: string | null;
  state: string;
  raw_file_id: string;
  metadata_state: string;
  qc_state: string;
  publish_ready: boolean;
}

export interface LibraryParams {
  material_type?: string;
  excitation_wavelength_nm?: number;
  excitation_wavelength_tolerance_nm?: number;
  min_snr?: number;
  modality?: string;
  limit?: number;
  offset?: number;
}

/** `GET /library/mine` — the requester's own spectra, every state. */
export function getMyLibrary(
  params: LibraryParams = {},
  opts?: ApiClientOptions,
): Promise<LibrarySpectrum[]> {
  return apiRequest<LibrarySpectrum[]>("/library/mine", {
    ...opts,
    query: { ...params },
  });
}

/* --- processing: algorithm catalog + routines --------------------- */

export interface AlgorithmInfo {
  step_type: string;
  version: string;
  label: string;
  category: string;
  description: string;
  param_schema: Record<string, unknown>;
  transforms_axis: boolean;
}

export interface AlgorithmCatalog {
  categories: string[];
  algorithms: AlgorithmInfo[];
}

/** `GET /processing/algorithms` — public. */
export function getAlgorithmCatalog(
  opts?: ApiClientOptions,
): Promise<AlgorithmCatalog> {
  return apiRequest<AlgorithmCatalog>("/processing/algorithms", opts);
}

export interface RoutineStep {
  type: string;
  params: Record<string, unknown>;
  order: number;
}

export interface Routine {
  id: string;
  owner_id: string;
  modality: string;
  name: string;
  description: string | null;
  steps_template: RoutineStep[];
  created_at: string;
  updated_at: string;
}

/** `GET /routines` — the caller's saved processing routines. */
export function listRoutines(opts?: ApiClientOptions): Promise<Routine[]> {
  return apiRequest<Routine[]>("/routines", opts);
}

/** `POST /routines` — create a saved routine. */
export function createRoutine(
  body: {
    modality: string;
    name: string;
    description?: string;
    steps_template: RoutineStep[];
  },
  opts?: ApiClientOptions,
): Promise<Routine> {
  return apiRequest<Routine>("/routines", { ...opts, method: "POST", body });
}

/** `DELETE /routines/{id}` — 204. */
export function deleteRoutine(
  id: string,
  opts?: ApiClientOptions,
): Promise<void> {
  return apiRequest<void>(`/routines/${encodeURIComponent(id)}`, {
    ...opts,
    method: "DELETE",
  });
}

/* --- processing: build & apply a pipeline ------------------------- */

export interface LedgerResult {
  ledger_id: string;
  ledger_hash: string;
  reused_existing: boolean;
  processed: { length: number };
}

/**
 * `POST /raw-files/{rawFileId}/ledgers` — build + persist a processing
 * pipeline. Returns the ledger id; call `updateSpectrum` to make it the
 * spectrum's current view, then re-`getSpectrumData` for the processed curve.
 */
export function createLedger(
  rawFileId: string,
  steps: RoutineStep[],
  opts?: ApiClientOptions,
): Promise<LedgerResult> {
  return apiRequest<LedgerResult>(
    `/raw-files/${encodeURIComponent(rawFileId)}/ledgers`,
    { ...opts, method: "POST", body: { steps } },
  );
}

/** `PATCH /spectra/{id}` — point the spectrum at a processing ledger (or `null` to reset to raw). */
export function updateSpectrum(
  spectrumId: string,
  body: { current_ledger_id: string | null },
  opts?: ApiClientOptions,
): Promise<Spectrum> {
  return apiRequest<Spectrum>(`/spectra/${encodeURIComponent(spectrumId)}`, {
    ...opts,
    method: "PATCH",
    body,
  });
}

/* --- account settings --------------------------------------------- */

export interface UpdateMeBody {
  display_name?: string;
  orcid_id?: string;
  profile_handle?: string;
  bio?: string;
  affiliation?: string;
  research_interests?: string[];
  is_profile_public?: boolean;
}

/** `PATCH /users/me` — full account only. Returns the updated user. */
export function updateMe(
  body: UpdateMeBody,
  opts?: ApiClientOptions,
): Promise<SessionUser> {
  return apiRequest<SessionUser>("/users/me", {
    ...opts,
    method: "PATCH",
    body,
  });
}

/** `GET /users/me/export` — portable account export. */
export function exportMe(opts?: ApiClientOptions): Promise<unknown> {
  return apiRequest<unknown>("/users/me/export", opts);
}

/** `DELETE /users/me` — anonymize the account. 204. */
export function deleteMe(opts?: ApiClientOptions): Promise<void> {
  return apiRequest<void>("/users/me", { ...opts, method: "DELETE" });
}

/* --- spectra + findings: chart data ------------------------------------- */

export interface SpectrumData {
  wavenumbers: number[];
  intensities: number[];
  downsampled: boolean;
  total_points: number;
}

export interface FindingOverlay {
  grid_wavenumbers: number[];
  mean: number[];
  std: number[];
  n: number;
  members: { spectrum_id: string; label: string | null }[];
}

export interface Spectrum {
  id: string;
  title: string | null;
  description: string | null;
  modality: string;
  material_type: string | null;
  state: "draft" | "published" | "embargoed";
  doi: string | null;
  license_id: string | null;
  published_at: string | null;
  is_owner: boolean;
  confirmed_metadata: Record<string, unknown> | null;
}

/** `GET /spectra/{id}` — spectrum record metadata (no array data). */
export function getSpectrum(
  spectrumId: string,
  opts?: ApiClientOptions,
): Promise<Spectrum> {
  return apiRequest<Spectrum>(
    `/spectra/${encodeURIComponent(spectrumId)}`,
    opts,
  );
}

/** `GET /spectra/{id}/data` — chart-ready (wavenumbers, intensities). */
export function getSpectrumData(
  spectrumId: string,
  params: { maxPoints?: number; raw?: boolean } = {},
  opts?: ApiClientOptions,
): Promise<SpectrumData> {
  return apiRequest<SpectrumData>(
    `/spectra/${encodeURIComponent(spectrumId)}/data`,
    { ...opts, query: { max_points: params.maxPoints, raw: params.raw } },
  );
}

/** `GET /v1/findings/{id}/overlay` — mean + std band across member spectra. */
export function getFindingOverlay(
  findingId: string,
  params: { grid?: number; maxPoints?: number } = {},
  opts?: ApiClientOptions,
): Promise<FindingOverlay> {
  return apiRequest<FindingOverlay>(
    `/v1/findings/${encodeURIComponent(findingId)}/overlay`,
    { ...opts, query: { grid: params.grid, max_points: params.maxPoints } },
  );
}

/* --- DOI metadata + AI enrichment ------------------------------------- */

export interface DoiMetadata {
  doi: string;
  title?: string | null;
  authors: string[];
  journal?: string | null;
  year?: number | null;
  url?: string | null;
  issn: string[];
  citations: number | null;
  abstract: string | null;
}

/**
 * `GET /doi-lookup?doi=` — Crossref-backed lookup. Resolves to `null` when
 * the DOI can't be resolved (the API answers 404 in that case).
 */
export async function lookupDoi(
  doi: string,
  opts?: ApiClientOptions,
): Promise<DoiMetadata | null> {
  try {
    return await apiRequest<DoiMetadata | null>("/doi-lookup", {
      ...opts,
      query: { doi },
    });
  } catch (e) {
    if (isApiError(e) && e.status === 404) return null;
    throw e;
  }
}

export interface EnrichResult {
  enriched: boolean;
  reason?: string;
  ai_summary: AiSummary | null;
}

/** `POST /v1/findings/{id}/enrich` — owner-only; 200 no-op when no LLM key. */
export function enrichFinding(
  findingId: string,
  opts?: ApiClientOptions,
): Promise<EnrichResult> {
  return apiRequest<EnrichResult>(
    `/v1/findings/${encodeURIComponent(findingId)}/enrich`,
    { ...opts, method: "POST" },
  );
}

/* --- finding images -------------------------------------------------- */

/** `POST /v1/findings/{id}/images` — multipart upload. Owner-only. */
export function uploadFindingImage(
  findingId: string,
  input: {
    file: File | Blob;
    kind: "figure" | "graphical_abstract";
    caption?: string;
  },
  opts?: ApiClientOptions,
): Promise<FindingImage> {
  const form = new FormData();
  form.append("file", input.file);
  form.append("kind", input.kind);
  if (input.caption != null) form.append("caption", input.caption);
  return apiRequest<FindingImage>(
    `/v1/findings/${encodeURIComponent(findingId)}/images`,
    { ...opts, method: "POST", body: form },
  );
}

/** `PATCH /v1/findings/{id}/images/{image_id}` — caption / position. */
export function updateFindingImage(
  findingId: string,
  imageId: string,
  body: { caption?: string; position?: number },
  opts?: ApiClientOptions,
): Promise<FindingImage> {
  return apiRequest<FindingImage>(
    `/v1/findings/${encodeURIComponent(findingId)}/images/${encodeURIComponent(imageId)}`,
    { ...opts, method: "PATCH", body },
  );
}

/** `DELETE /v1/findings/{id}/images/{image_id}` — 204. */
export function deleteFindingImage(
  findingId: string,
  imageId: string,
  opts?: ApiClientOptions,
): Promise<void> {
  return apiRequest<void>(
    `/v1/findings/${encodeURIComponent(findingId)}/images/${encodeURIComponent(imageId)}`,
    { ...opts, method: "DELETE" },
  );
}

/** `POST /v1/findings/{id}/images/reorder` — full id list; returns the Finding. */
export function reorderFindingImages(
  findingId: string,
  imageIds: string[],
  opts?: ApiClientOptions,
): Promise<Finding> {
  return apiRequest<Finding>(
    `/v1/findings/${encodeURIComponent(findingId)}/images/reorder`,
    { ...opts, method: "POST", body: { image_ids: imageIds } },
  );
}

/** Browser `<img src>` URL for a finding image (goes through the `/api` rewrite). */
export function findingImageFileUrl(
  findingId: string,
  imageId: string,
): string {
  return `/api/v1/findings/${encodeURIComponent(findingId)}/images/${encodeURIComponent(imageId)}/file`;
}
