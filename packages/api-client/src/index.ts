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

/**
 * Collapse any error response body into one short sentence safe to show a
 * user. Backend 4xx `detail` strings are written to be read by humans, so
 * those pass through; a FastAPI 422 `detail` array, a 5xx reason, or a
 * missing/'{}' body all become a generic line. The untouched body is still
 * on `ApiError.body` and is logged by `apiRequest`.
 */
function userFacingMessage(status: number, body: unknown): string {
  if (status >= 500) return "That broke on our side. Try again.";
  // The likeliest 429 is now the shared free-model tier, which is capped
  // per minute and per day — worth naming so it doesn't read as a scolding.
  if (status === 429)
    return "Rate limited — the free model pool is capped. Give it a minute.";
  const detail = (body as { detail?: unknown; message?: unknown } | null)
    ?.detail;
  if (typeof detail === "string" && detail.trim()) return detail;
  if (Array.isArray(detail)) return "Some of those values didn't validate.";
  const msg = (body as { message?: unknown } | null)?.message;
  if (typeof msg === "string" && msg.trim()) return msg;
  if (status === 404) return "No such thing — or not yours to see.";
  if (status === 401 || status === 403) return "You don't have access to that.";
  return `Request failed (${status}).`;
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

/**
 * RFC-4122 v4 UUID. Prefers the platform `crypto.randomUUID`; falls back to
 * a `Math.random`-based generator on runtimes that don't expose it (older
 * RN / JSC). Not cryptographically strong in the fallback path — it only
 * needs to be collision-free enough to key one idempotent request.
 */
function generateUuid(): string {
  // Typed as always-present in lib.dom, but genuinely absent on some older
  // RN/JSC runtimes — hence the cast so the guards below aren't "unnecessary".
  const platformCrypto = globalThis.crypto as
    | { randomUUID?: () => string }
    | undefined;
  const fromCrypto = platformCrypto?.randomUUID?.();
  if (fromCrypto) return fromCrypto;
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    const v = c === "x" ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
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

  const method = opts.method ?? "GET";

  // Generated once per `apiRequest` call, BEFORE `fetch`. A transparent
  // HTTP replay by a proxy (Vercel rewrite) or an HTTP/2 stream reset
  // resends the exact same request, carrying this same key — which is how
  // the backend (see `app/idempotency.py`) recognises the retry and returns
  // the first response instead of creating a duplicate draft / post / vote.
  const idempotencyHeader: Record<string, string> =
    method === "GET" ? {} : { "Idempotency-Key": generateUuid() };

  const res = await fetch(`${base}${rel}${qs}`, {
    method,
    credentials: "include",
    signal: opts.signal,
    headers: {
      ...(opts.body !== undefined && !isFormBody
        ? { "content-type": "application/json" }
        : {}),
      ...(opts.token ? { authorization: `Bearer ${opts.token}` } : {}),
      ...idempotencyHeader,
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
    let body: unknown;
    try {
      body = await res.json();
    } catch {
      /* non-JSON error body */
    }
    // `message` is what a component may show a user directly, so it must
    // always be a short, safe string — never a raw stack, a FastAPI 422
    // `detail` array, or an internal 5xx reason. The full response stays on
    // `.body` for callers that want it, and is logged below for debugging.
    const message = userFacingMessage(res.status, body);
    const err: ApiError = { status: res.status, message, body };
    if (typeof console !== "undefined") {
      console.error(
        `[api] ${opts.method ?? "GET"} ${rel}${qs} -> ${res.status}`,
        body ?? "(no body)",
      );
    }
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
  /** The model that actually wrote this summary. Under the free router the
   *  model varies per call, so this is only known after the fact — null for
   *  summaries generated before it was recorded. */
  model?: string | null;
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

/** A registered user credited on a finding. Order is meaningful. */
export interface FindingCoAuthor {
  user_id: string;
  handle: string | null;
  display_name: string | null;
  avatar_url: string | null;
  position: number;
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
  /** What the author thinks should happen next — open questions, help wanted. */
  next_steps_md: string | null;
  state: "draft" | "published";
  license_id: string | null;
  doi: string | null;
  /** Optional link to the code/analysis repo behind the write-up (e.g. a GitHub repo). Not verified. */
  repo_url: string | null;
  publication_metadata: PublicationMeta | null;
  /**
   * The dataset this write-up is about, if it names one. Denormalised onto
   * the response so a post page can render its data card without a second
   * request. All four are `null` when the post attaches loose spectra.
   */
  dataset_id: string | null;
  dataset_accession: string | null;
  dataset_name: string | null;
  dataset_state: "draft" | "published" | null;
  tags: string[] | null;
  published_at: string | null;
  created_at: string;
  updated_at: string;
  co_authors: FindingCoAuthor[];
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
    next_steps_md?: string;
    tags?: string[];
    repo_url?: string;
    /**
     * Handles of registered users to credit, in order. An unknown handle
     * fails the whole request with 422 rather than being dropped — sending
     * the list is how you set it, and a silently-ignored typo would credit
     * nobody while looking like it worked.
     */
    co_author_handles?: string[];
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
    next_steps_md?: string;
    tags?: string[];
    doi?: string;
    repo_url?: string;
    /** Replaces the credit list wholesale; omit to leave it alone, `[]` clears it. */
    co_author_handles?: string[];
    /**
     * The dataset this post is about. Must be one the caller owns (404
     * otherwise). Explicit `null` unlinks; omitting the key leaves it alone.
     */
    dataset_id?: string | null;
  },
  opts?: ApiClientOptions,
): Promise<Finding> {
  return apiRequest<Finding>(`/v1/findings/${encodeURIComponent(id)}`, {
    ...opts,
    method: "PATCH",
    body,
  });
}

/**
 * `POST /v1/findings/{id}/fork-data` — 201. Fork every spectrum attached to
 * this post into a new draft dataset in the caller's lab, and return it.
 *
 * The single call behind "Fork to my lab". Works whether or not the post names
 * a `dataset_id`, so posts that attach loose spectra are still forkable. 422
 * when the post has no attached spectra.
 */
export function forkFindingData(
  findingId: string,
  opts?: ApiClientOptions,
): Promise<Dataset> {
  return apiRequest<Dataset>(
    `/v1/findings/${encodeURIComponent(findingId)}/fork-data`,
    { ...opts, method: "POST" },
  );
}

/**
 * `POST /v1/findings/{id}/link-doi` — attach a published paper.
 *
 * The server resolves the DOI against Crossref at link time and caches the
 * result in `publication_metadata`, so rendering a feed doesn't make an
 * outbound call per card. An unresolvable DOI is still stored, flagged
 * `resolved: false` — a brand-new DOI may simply not be indexed yet. Pass an
 * empty string to unlink.
 */
export function linkFindingDoi(
  id: string,
  doi: string,
  opts?: ApiClientOptions,
): Promise<Finding> {
  return apiRequest<Finding>(
    `/v1/findings/${encodeURIComponent(id)}/link-doi`,
    {
      ...opts,
      method: "POST",
      body: { doi },
    },
  );
}

/**
 * `POST /v1/findings/{id}/spectra` — attach a spectrum the caller can read.
 *
 * Someone else's *published* spectrum is allowed: that is how a finding
 * compares your data against a published reference. Their draft is not.
 */
export function attachFindingSpectrum(
  findingId: string,
  spectrumId: string,
  label?: string,
  opts?: ApiClientOptions,
): Promise<Finding> {
  return apiRequest<Finding>(
    `/v1/findings/${encodeURIComponent(findingId)}/spectra`,
    {
      ...opts,
      method: "POST",
      body: { spectrum_id: spectrumId, ...(label ? { label } : {}) },
    },
  );
}

/** `DELETE /v1/findings/{id}/spectra/{spectrumId}` — detach; returns the finding. */
export function detachFindingSpectrum(
  findingId: string,
  spectrumId: string,
  opts?: ApiClientOptions,
): Promise<Finding> {
  return apiRequest<Finding>(
    `/v1/findings/${encodeURIComponent(findingId)}/spectra/${encodeURIComponent(spectrumId)}`,
    { ...opts, method: "DELETE" },
  );
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

/**
 * `DELETE /v1/findings/{id}` — 204. Owner-only; hard-deletes a non-published
 * finding. Published findings are citable and refuse deletion with 409.
 */
export function deleteFinding(
  id: string,
  opts?: ApiClientOptions,
): Promise<void> {
  return apiRequest<void>(`/v1/findings/${encodeURIComponent(id)}`, {
    ...opts,
    method: "DELETE",
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

export interface CommentAuthor {
  display_name: string;
  avatar_url: string | null;
  orcid_id: string | null;
  /** In-app path to the author's profile, or null if it isn't public. */
  profile_path: string | null;
}

export interface FindingComment {
  id: number;
  spectrum_id: string | null;
  finding_id: string | null;
  parent_id: number | null;
  body: string;
  created_at: string;
  author: CommentAuthor;
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
  /**
   * Drafts have no `published_at`, so this is the only timestamp that orders
   * the owner's own library. `/library/mine` is already sorted by it, desc.
   */
  created_at: string;
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

/* --- public reference library: identify a spectrum ------------------ */

/*
 * Not the same thing as the section above. `/library/mine` is *your* spectra,
 * in every state. `/v1/library/*` is the shared corpus of identified compounds
 * that anyone can match against — bundled reference data plus vetted user
 * contributions.
 */

export interface ReferenceEntry {
  id: string;
  spectrum_id: string;
  compound_name: string;
  chemical_formula: string | null;
  cas_number: string | null;
  mineral_name: string | null;
  source: string;
  source_id: string | null;
  source_dataset: string | null;
  provenance_url: string | null;
  /**
   * `curated` is bundled or staff-vetted reference data. `community` is
   * user-contributed: auto-approved and matchable at once, but ranked below a
   * curated entry at equal similarity. Badge it — a user should always be able
   * to see which tier an identification came from.
   */
  trust_tier: "curated" | "community";
  curation_status: "approved" | "demoted" | "removed";
  flagged_for_review: boolean;
  license_id: string | null;
  title: string | null;
  excitation_wavelength_nm: number | null;
  primary_peak_cm1: number | null;
}

export interface ReferencePeak {
  cm1: number;
  height: number;
  rel_height: number;
  prominence: number;
  fwhm: number | null;
  snr: number | null;
}

export interface ReferenceDetail extends ReferenceEntry {
  peaks: ReferencePeak[];
  wavenumber_min: number | null;
  wavenumber_max: number | null;
}

export interface ReferenceSearchParams {
  q?: string;
  formula?: string;
  cas_number?: string;
  source?: string;
  trust_tier?: "curated" | "community";
  limit?: number;
  offset?: number;
}

/** `GET /v1/library/references` — browse the reference corpus by identity. */
export function searchReferences(
  params: ReferenceSearchParams = {},
  opts?: ApiClientOptions,
): Promise<ReferenceEntry[]> {
  return apiRequest<ReferenceEntry[]>("/v1/library/references", {
    ...opts,
    query: { ...params },
  });
}

/** `GET /v1/library/references/{id}` — one entry plus its detected bands. */
export function getReference(
  referenceId: string,
  opts?: ApiClientOptions,
): Promise<ReferenceDetail> {
  return apiRequest<ReferenceDetail>(
    `/v1/library/references/${encodeURIComponent(referenceId)}`,
    { ...opts },
  );
}

export interface LibraryMatch {
  reference: ReferenceEntry;
  /** Cosine over the shared 512-point feature grid, 0..1. */
  similarity: number;
  overlap_fraction: number;
  matched_peak_count: number;
  unmatched_query_peaks_cm1: number[];
}

export interface LibraryMatchResult {
  contract_version: string;
  peak_index_version: string;
  feature_version: string;
  query_spectrum_id: string;
  query_peaks: ReferencePeak[];
  primary_peak_cm1: number | null;
  peak_to_background: number | null;
  /**
   * Which rung of the prefilter answered. `full` means the query shared no
   * band with anything indexed and the whole corpus was scanned — worth
   * surfacing, since it is both slow and a hint the match is weak.
   */
  prefilter_stage: "narrow" | "widened" | "full";
  candidates_screened: number;
  candidates_scored: number;
  matches: LibraryMatch[];
  mixture_suspected: boolean;
  mixture_reason: string | null;
  suggested_component_reference_ids: string[];
}

export interface LibraryMatchBody {
  spectrum_id: string;
  top_k?: number;
  trust_tiers?: ("curated" | "community")[];
  /** Advisory only: the server recomputes peaks and never trusts these. */
  client_peaks_cm1?: number[];
}

/** `POST /v1/library/match` — rank the reference corpus against a spectrum. */
export function matchAgainstLibrary(
  body: LibraryMatchBody,
  opts?: ApiClientOptions,
): Promise<LibraryMatchResult> {
  return apiRequest<LibraryMatchResult>("/v1/library/match", {
    ...opts,
    method: "POST",
    body,
  });
}

export interface UnmixComponent {
  reference: ReferenceEntry;
  /**
   * Fraction of *spectral contribution*, not concentration. Raman cross
   * sections differ by orders of magnitude between compounds, so label this
   * "spectral weight" in the UI and never "how much of the sample is X".
   */
  weight: number;
  raw_coefficient: number;
}

export interface LibraryUnmixResult {
  contract_version: string;
  query_spectrum_id: string;
  baseline_applied: string;
  grid_wavenumbers: number[];
  observed: number[];
  fitted: number[];
  residual: number[];
  components: UnmixComponent[];
  offset: number;
  slope: number;
  r_squared: number;
  residual_norm_fraction: number;
  /** High values mean the components are near-duplicates and the split
   *  between them is arbitrary — show the warnings, do not bury them. */
  condition_number: number;
  collinear_warnings: string[];
}

export interface LibraryUnmixBody {
  spectrum_id: string;
  /** Two to six references; the server rejects more. */
  reference_ids: string[];
  grid_points?: number;
  baseline?: "als" | "none";
}

/** `POST /v1/library/unmix` — fit a spectrum as a mixture of chosen references. */
export function unmixAgainstLibrary(
  body: LibraryUnmixBody,
  opts?: ApiClientOptions,
): Promise<LibraryUnmixResult> {
  return apiRequest<LibraryUnmixResult>("/v1/library/unmix", {
    ...opts,
    method: "POST",
    body,
  });
}

export interface ContributeReferenceBody {
  spectrum_id: string;
  compound_name: string;
  chemical_formula?: string;
  cas_number?: string;
  mineral_name?: string;
  provenance_url?: string;
  notes?: string;
}

/** `POST /v1/library/references` — promote your published spectrum to a reference. */
export function contributeReference(
  body: ContributeReferenceBody,
  opts?: ApiClientOptions,
): Promise<ReferenceEntry> {
  return apiRequest<ReferenceEntry>("/v1/library/references", {
    ...opts,
    method: "POST",
    body,
  });
}

/** `POST /v1/library/references/{id}/report` — flag a mislabelled reference. */
export function reportReference(
  referenceId: string,
  body: { reason: string },
  opts?: ApiClientOptions,
): Promise<void> {
  return apiRequest<void>(
    `/v1/library/references/${encodeURIComponent(referenceId)}/report`,
    { ...opts, method: "POST", body },
  );
}

/** `PATCH /v1/library/references/{id}` — moderator-only demote or remove. */
export function moderateReference(
  referenceId: string,
  body: {
    curation_status: "approved" | "demoted" | "removed";
    trust_tier?: "curated" | "community";
    note?: string;
  },
  opts?: ApiClientOptions,
): Promise<ReferenceEntry> {
  return apiRequest<ReferenceEntry>(
    `/v1/library/references/${encodeURIComponent(referenceId)}`,
    { ...opts, method: "PATCH", body },
  );
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

/**
 * `PATCH /spectra/{id}` — edit the record's title/description, and/or point it
 * at a processing ledger (`current_ledger_id: null` resets to raw).
 */
export function updateSpectrum(
  spectrumId: string,
  body: {
    current_ledger_id?: string | null;
    title?: string;
    description?: string;
  },
  opts?: ApiClientOptions,
): Promise<Spectrum> {
  return apiRequest<Spectrum>(`/spectra/${encodeURIComponent(spectrumId)}`, {
    ...opts,
    method: "PATCH",
    body,
  });
}

/* --- datasets (analysis project folders) ------------------------- */

/** A spectrum as it appears inside a dataset's ordered membership list. */
export interface DatasetSpectrum {
  id: string;
  title: string | null;
  modality: string;
  state: string;
  /** Public handle, e.g. `RH-S-000042`. Null until the spectrum is published. */
  accession: string | null;
  excitation_wavelength_nm: number | null;
  /** Set only on a fork — the spectrum this one was copied from. */
  parent_spectrum_id: string | null;
}

/**
 * An owner-scoped, named collection of spectra — a "project folder". May be
 * empty or hold a single spectrum; an analysis run (`POST` under `/analysis`)
 * is what requires >= 2. `spectra` is ordered by membership position.
 */
export interface Dataset {
  id: string;
  name: string;
  description: string | null;
  modality: string;
  spectra: DatasetSpectrum[];
  created_at: string | null;
  updated_at: string | null;
  /**
   * Owner-chosen visual identity. Typed `string`, not a union, so a slot added
   * server-side does not break this client; render through
   * `projectColor()` / `projectIcon()`, which fall back on an unknown value.
   */
  color: string;
  icon: string;
  /** Public handle, e.g. `RH-D-000004`. Null until published. */
  accession: string | null;
  state: "draft" | "published";
  published_at: string | null;
  license_id: string | null;
  doi: string | null;
  /** Set only on a fork — the dataset this one was copied from. */
  parent_dataset_id: string | null;
  owner_id: string | null;
  owner_handle: string | null;
  is_owner: boolean;
}

/**
 * One person's credited work inside a project. Derived server-side from
 * spectrum ownership and Finding authorship — there is no membership table,
 * so this list changes as data and write-ups are added, not by invitation.
 *
 * Counts are evaluated for the *requesting* user: an item is included only if
 * it is published or the requester owns it.
 */
export interface DatasetContributor {
  user_id: string;
  handle: string | null;
  display_name: string | null;
  avatar_url: string | null;
  affiliation: string | null;
  spectra: number;
  findings: number;
  is_owner: boolean;
}

/**
 * `GET /analysis/datasets/{id}/contributors` — no auth required for a
 * published dataset; a draft is 404 to anyone but its owner. Ordered by total
 * contribution, owner first on a tie.
 */
export function listDatasetContributors(
  datasetId: string,
  opts?: ApiClientOptions,
): Promise<DatasetContributor[]> {
  return apiRequest<DatasetContributor[]>(
    `/analysis/datasets/${encodeURIComponent(datasetId)}/contributors`,
    opts,
  );
}

/** `GET /analysis/datasets` — the caller's datasets, newest-updated first. */
export function listDatasets(opts?: ApiClientOptions): Promise<Dataset[]> {
  return apiRequest<Dataset[]>("/analysis/datasets", opts);
}

/**
 * `POST /analysis/datasets` — create a folder. `spectrum_ids` is optional and
 * may be `[]`; when non-empty every spectrum must be owned-or-public, Raman,
 * and share one modality. Re-POSTing the same name + identical id list returns
 * the existing dataset (201); a different list under a taken name is 409.
 */
export function createDataset(
  body: {
    name: string;
    description?: string;
    spectrum_ids?: string[];
    /** Omit both and the server assigns the next free palette slot. */
    color?: string;
    icon?: string;
  },
  opts?: ApiClientOptions,
): Promise<Dataset> {
  return apiRequest<Dataset>("/analysis/datasets", {
    ...opts,
    method: "POST",
    body,
  });
}

/** `GET /analysis/datasets/{id}` — owner only, else 404. */
export function getDataset(
  datasetId: string,
  opts?: ApiClientOptions,
): Promise<Dataset> {
  return apiRequest<Dataset>(
    `/analysis/datasets/${encodeURIComponent(datasetId)}`,
    opts,
  );
}

/**
 * `PATCH /analysis/datasets/{id}` — rename and/or edit the description. Owner
 * only. A name already used by another of the caller's datasets is 409.
 */
export function updateDataset(
  datasetId: string,
  body: {
    name?: string;
    description?: string | null;
    color?: string;
    icon?: string;
  },
  opts?: ApiClientOptions,
): Promise<Dataset> {
  return apiRequest<Dataset>(
    `/analysis/datasets/${encodeURIComponent(datasetId)}`,
    { ...opts, method: "PATCH", body },
  );
}

/**
 * `DELETE /analysis/datasets/{id}` — 204. Owner only. Removes the folder and
 * its membership rows but never the spectra. 409 if the dataset still has
 * analysis runs (delete those first).
 */
export function deleteDataset(
  datasetId: string,
  opts?: ApiClientOptions,
): Promise<void> {
  return apiRequest<void>(
    `/analysis/datasets/${encodeURIComponent(datasetId)}`,
    { ...opts, method: "DELETE" },
  );
}

/**
 * `POST /analysis/datasets/{id}/spectra` — append spectra to the folder.
 * Idempotent: ids already present are skipped. New ids must be
 * owned-or-public and match the dataset's modality; the per-dataset cap
 * still applies. Returns the updated dataset.
 */
export function addDatasetSpectra(
  datasetId: string,
  spectrumIds: string[],
  opts?: ApiClientOptions,
): Promise<Dataset> {
  return apiRequest<Dataset>(
    `/analysis/datasets/${encodeURIComponent(datasetId)}/spectra`,
    { ...opts, method: "POST", body: { spectrum_ids: spectrumIds } },
  );
}

/**
 * `POST /analysis/datasets/{id}/publish` — draft -> published. Mints an
 * `RH-D-*` accession and makes the dataset world-readable.
 *
 * 422 if the dataset is empty or holds a spectrum that is not itself
 * published: a dataset that advertises data its readers can't fetch is worse
 * than no dataset. 400 if it is already published.
 */
export function publishDataset(
  datasetId: string,
  body: { license_id: string },
  opts?: ApiClientOptions,
): Promise<Dataset> {
  return apiRequest<Dataset>(
    `/analysis/datasets/${encodeURIComponent(datasetId)}/publish`,
    { ...opts, method: "POST", body },
  );
}

/**
 * `POST /analysis/datasets/{id}/fork` — 201. Copy a readable dataset and every
 * spectrum in it into the caller's own lab as a new draft folder of forks.
 * The new dataset records `parent_dataset_id`, and each fork records its own
 * `parent_spectrum_id`.
 */
export function forkDataset(
  datasetId: string,
  opts?: ApiClientOptions,
): Promise<Dataset> {
  return apiRequest<Dataset>(
    `/analysis/datasets/${encodeURIComponent(datasetId)}/fork`,
    { ...opts, method: "POST" },
  );
}

/**
 * `DELETE /analysis/datasets/{id}/spectra/{spectrumId}` — drop one membership
 * row, 204. The spectrum itself is untouched. 404 if it was not a member.
 */
export function removeDatasetSpectrum(
  datasetId: string,
  spectrumId: string,
  opts?: ApiClientOptions,
): Promise<void> {
  return apiRequest<void>(
    `/analysis/datasets/${encodeURIComponent(datasetId)}/spectra/${encodeURIComponent(spectrumId)}`,
    { ...opts, method: "DELETE" },
  );
}

/**
 * `POST /spectra/{id}/fork` — 201. Copy a readable spectrum into the caller's
 * own workspace as a new draft.
 *
 * Ledger creation requires owning the raw file, so this is how anyone
 * experiments on a *public* spectrum: fork first, then process the copy. The
 * source's processing ledger is replayed onto the fork, so it opens looking
 * identical. Publish state, license and DOI are deliberately not copied.
 */
export function forkSpectrum(
  spectrumId: string,
  opts?: ApiClientOptions,
): Promise<Spectrum> {
  return apiRequest<Spectrum>(
    `/spectra/${encodeURIComponent(spectrumId)}/fork`,
    { ...opts, method: "POST" },
  );
}

/**
 * `GET /spectra/{id}/lineage` — where this spectrum came from, and how many
 * copies came from it. A non-empty `ancestors` means "this is a working copy
 * of someone else's data".
 */
export function getSpectrumLineage(
  spectrumId: string,
  opts?: ApiClientOptions,
): Promise<SpectrumLineage> {
  return apiRequest<SpectrumLineage>(
    `/spectra/${encodeURIComponent(spectrumId)}/lineage`,
    opts,
  );
}

/**
 * `DELETE /spectra/{id}` — 204. Owner-only; hard-deletes a non-published
 * spectrum plus its raw file, ingestion job(s), ledgers and social signals.
 * A published / DOI-linked spectrum refuses deletion with 409.
 */
export function deleteSpectrum(
  spectrumId: string,
  opts?: ApiClientOptions,
): Promise<void> {
  return apiRequest<void>(`/spectra/${encodeURIComponent(spectrumId)}`, {
    ...opts,
    method: "DELETE",
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

/* --- bring-your-own LLM key ------------------------------------------- */

export interface LlmProvider {
  slug: string;
  label: string;
  default_model: string;
  key_hint: string;
}

export interface LlmKeyStatus {
  /** False when the deployment has no encryption key — hide the whole card. */
  enabled: boolean;
  configured: boolean;
  provider: string | null;
  provider_label: string | null;
  model: string | null;
  /** Last 4 characters only. The key itself is never returned. */
  key_last4: string | null;
  /** What you're routed to without your own key — usually `openrouter/free`. */
  platform_model: string | null;
  /** True when `platform_model` is a router that picks per call, not a
   *  single fixed model. */
  platform_model_varies: boolean;
  providers: LlmProvider[];
}

export interface SetLlmKeyBody {
  provider: string;
  api_key: string;
  /** Omit for the provider's default model. */
  model?: string;
}

/** `GET /v1/users/me/llm-key` — full account only. */
export function getLlmKeyStatus(
  opts?: ApiClientOptions,
): Promise<LlmKeyStatus> {
  return apiRequest<LlmKeyStatus>("/v1/users/me/llm-key", opts);
}

/**
 * `PUT /v1/users/me/llm-key` — full account only. The key is verified against
 * the provider before it is stored, so a 400 here means the key itself did
 * not work.
 */
export function setLlmKey(
  body: SetLlmKeyBody,
  opts?: ApiClientOptions,
): Promise<LlmKeyStatus> {
  return apiRequest<LlmKeyStatus>("/v1/users/me/llm-key", {
    ...opts,
    method: "PUT",
    body,
  });
}

/** `DELETE /v1/users/me/llm-key` — fall back to the shared models. 204. */
export function deleteLlmKey(opts?: ApiClientOptions): Promise<void> {
  return apiRequest<void>("/v1/users/me/llm-key", {
    ...opts,
    method: "DELETE",
  });
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
  /** Public handle, e.g. `RH-S-000042`. Null until published. */
  accession: string | null;
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
  /**
   * The spectrum this one was forked from, or null for an original. Written
   * only by the fork path — applying a processing ledger mutates a spectrum
   * in place rather than creating a child.
   */
  parent_spectrum_id: string | null;
  raw_file_id?: string;
  current_ledger_id?: string | null;
}

/**
 * One ancestor in a fork chain. A spectrum that was public when it was forked
 * can be unpublished later; rather than leak it or silently shorten the chain,
 * such a node comes back with `redacted: true` and every descriptive field
 * null.
 */
export interface LineageNode {
  id: string | null;
  accession: string | null;
  title: string | null;
  owner_handle: string | null;
  state: string | null;
  redacted: boolean;
}

export interface SpectrumLineage {
  /** Ordered ROOT FIRST, ending at the immediate parent. Empty for an original. */
  ancestors: LineageNode[];
  /** How many spectra name this one as their direct parent. */
  fork_count: number;
  /** True when the chain was cut short by the server's depth cap. */
  truncated: boolean;
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

/* --- ingestion: getting a spectrum into the platform ---------------------- */

/**
 * The typed metadata shape the vendor parsers and the LLM fallback both
 * produce, and the only thing `PATCH /ingestion-jobs/{id}` accepts. Mirrors
 * `ExtractedMetadata` in `backend/app/schemas/ingestion.py`, which is
 * `extra="forbid"` — sending an unknown key is a 422, not a silent drop.
 */
export interface ExtractedMetadata {
  modality: "raman";
  instrument_vendor?: string | null;
  instrument_model?: string | null;
  laser_wavelength_nm?: number | null;
  laser_power_mw?: number | null;
  integration_time_ms?: number | null;
  accumulations?: number | null;
  /** Formatted "min-max", e.g. "200-3200". */
  spectral_range_cm1?: string | null;
  resolution_cm1?: number | null;
  acquisition_datetime?: string | null;
  sample_description?: string | null;
  grating_lines_mm?: number | null;
  objective_magnification?: number | null;
  raw_extra_fields?: Record<string, string | number>;
}

export type IngestionStatus =
  | "pending"
  | "running"
  | "succeeded"
  | "failed"
  | "cancelled"
  /**
   * The file parsed, but its structure could not be worked out — how many
   * spectra it holds and which columns they are. A question for the owner,
   * not a failure: answer it with {@link declareIngestionJobLayout}.
   */
  | "needs_input";

/** How a text spectral file is laid out, i.e. where its numbers are. */
export interface FileLayout {
  /**
   * `column_major`: one column is the wavenumber axis, each other numeric
   * column is a spectrum. `row_major`: one row is the axis and each other row
   * is a spectrum. `stacked_blocks`: two-column blocks separated by blanks.
   */
  orientation: "column_major" | "row_major" | "stacked_blocks";
  /** A literal character, or `"whitespace"` for "any run of blank space". */
  delimiter: string;
  decimal_separator: "." | ",";
  comment_prefixes: string[];
  /** Preamble rows skipped before the numeric body. All indexes below are
   * counted AFTER these. */
  header_rows: number;
  /** Column (column_major) or row (row_major) holding the wavenumber axis. */
  x_index: number;
  /** Column carrying each trace's name, for row_major files. */
  label_index: number | null;
  traces: { index: number; label: string | null }[];
  confidence: number;
  source: "heuristic" | "llm" | "user";
}

/** A sample of the raw file's text, shown to the user when we have to ask
 * them what shape it is. */
export interface StructurePreview {
  delimiter: string;
  decimal_separator: "." | ",";
  total_lines: number;
  column_count: number;
  header_rows: number;
  header_cells: string[][];
  /** Body rows, indexed from 0 after `header_rows` — the same numbering
   * `FileLayout` uses, so a column the user clicks maps straight to an index. */
  rows: string[][];
  numeric_fraction: number[];
  leading_comment_lines: number;
  body_lines: number;
  blank_separated_blocks: number;
  truncated_rows: boolean;
  truncated_columns: boolean;
}

export interface IngestionJob {
  id: string;
  raw_file_id: string;
  status: IngestionStatus;
  parser_used: string | null;
  parser_version: string | null;
  parser_confidence: number | null;
  canonicalization_version: string | null;
  header_hash: string | null;
  extracted_metadata_raw: Record<string, unknown> | null;
  sanity_check_flags: Record<string, unknown> | null;
  extracted_metadata_confirmed: Record<string, unknown> | null;
  /** Null until structure detection has run, or when it gave up. */
  file_layout: FileLayout | null;
  structure_preview: StructurePreview | null;
  /** Which rung answered: cache | heuristic | llm | llm-wide | user |
   * unresolved. */
  layout_source: string | null;
  error_message: string | null;
  attempt_count: number;
  max_attempts: number;
  draft_spectrum_id: string | null;
  /** Set only when the file held more than one spectrum: the dataset its
   * drafts were grouped into. */
  draft_dataset_id: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  confirmed_at: string | null;
}

export interface RawFileUploadResult {
  raw_file_id: string;
  ingestion_job_id: string;
  /**
   * True when this exact content was already uploaded by this user. The
   * server returns the original job rather than creating a duplicate, so the
   * caller should resume that job instead of treating it as an error.
   */
  deduplicated: boolean;
}

/**
 * `POST /raw-files` — upload a vendor spectrum file.
 *
 * Returns 202: the file is stored and an ingestion job is queued, but nothing
 * is parsed yet. A separate worker process (`python -m app.ingestion.worker`)
 * moves the job pending -> running -> succeeded; poll {@link getIngestionJob}
 * until it leaves a non-terminal state. If no worker is running the job stays
 * `pending` forever.
 */
export function uploadRawFile(
  file: File | Blob,
  opts?: ApiClientOptions,
): Promise<RawFileUploadResult> {
  const form = new FormData();
  form.append("file", file);
  return apiRequest<RawFileUploadResult>("/raw-files", {
    ...opts,
    method: "POST",
    body: form,
  });
}

/**
 * An advisory short display name for a freshly uploaded file. `suggested_title`
 * is null whenever a name could not be produced — no model configured, the
 * model unreachable, or a reply that failed validation — with `reason`
 * explaining which. That is a normal 200, not an error: naming is a
 * convenience on top of an upload and must never block one.
 */
export interface NameSuggestion {
  suggested_title: string | null;
  reason: string | null;
}

/**
 * `POST /raw-files/{id}/name-suggestion` — suggest a short display name from
 * the file's extracted metadata. 400s until parsing has produced metadata.
 */
export function suggestSpectrumName(
  rawFileId: string,
  opts?: ApiClientOptions,
): Promise<NameSuggestion> {
  return apiRequest<NameSuggestion>(
    `/raw-files/${encodeURIComponent(rawFileId)}/name-suggestion`,
    { ...opts, method: "POST" },
  );
}

/** `GET /ingestion-jobs/{id}` — poll parse progress. 404s for non-owners. */
export function getIngestionJob(
  jobId: string,
  opts?: ApiClientOptions,
): Promise<IngestionJob> {
  return apiRequest<IngestionJob>(
    `/ingestion-jobs/${encodeURIComponent(jobId)}`,
    opts,
  );
}

/**
 * `PATCH /ingestion-jobs/{id}` — confirm the parsed metadata, which
 * atomically creates (or recovers) the private draft spectrum. Only valid
 * once the job has succeeded; earlier calls 409. Re-confirming is idempotent
 * and preserves the draft's title/description and processing work.
 */
export function confirmIngestionMetadata(
  jobId: string,
  metadata: ExtractedMetadata,
  opts?: ApiClientOptions,
): Promise<IngestionJob> {
  return apiRequest<IngestionJob>(
    `/ingestion-jobs/${encodeURIComponent(jobId)}`,
    { ...opts, method: "PATCH", body: { metadata } },
  );
}

/**
 * `POST /ingestion-jobs/{id}/layout` — tell the server how this file is laid
 * out, when detection could not work it out (`status === "needs_input"`).
 *
 * The declaration is checked against the file's actual bytes: a layout that
 * cannot produce a readable spectrum comes back as a 422 with a message
 * naming what to fix, rather than being stored and failing later. An accepted
 * layout is remembered for this file format, so the next upload of it is read
 * without asking again.
 */
export function declareIngestionJobLayout(
  jobId: string,
  layout: Partial<FileLayout> & Pick<FileLayout, "orientation" | "traces">,
  opts?: ApiClientOptions,
): Promise<IngestionJob> {
  return apiRequest<IngestionJob>(
    `/ingestion-jobs/${encodeURIComponent(jobId)}/layout`,
    { ...opts, method: "POST", body: { layout } },
  );
}

/** `POST /ingestion-jobs/{id}/retry` — requeue a failed parse. */
export function retryIngestionJob(
  jobId: string,
  opts?: ApiClientOptions,
): Promise<IngestionJob> {
  return apiRequest<IngestionJob>(
    `/ingestion-jobs/${encodeURIComponent(jobId)}/retry`,
    { ...opts, method: "POST" },
  );
}

/* --- licenses + spectrum publishing --------------------------------------- */

export interface LicenseOption {
  id: string;
  name: string;
  url: string | null;
  is_default: boolean;
}

/**
 * `GET /licenses` — the publishable license list. Seeded by
 * `app.seed.seed_data`; an unseeded database returns [] and nothing can be
 * published, because publish requires a `license_id`.
 */
export function listLicenses(
  opts?: ApiClientOptions,
): Promise<LicenseOption[]> {
  return apiRequest<LicenseOption[]>("/licenses", opts);
}

/** `POST /spectra/{id}/publish` — move a draft to the public commons. */
export function publishSpectrum(
  spectrumId: string,
  input: { license_id: string },
  opts?: ApiClientOptions,
): Promise<Spectrum> {
  return apiRequest<Spectrum>(
    `/spectra/${encodeURIComponent(spectrumId)}/publish`,
    { ...opts, method: "POST", body: input },
  );
}

/* --- lab consultant (read-only processing advice) ----------------------- */

export interface LabConsultBody {
  /** An analysis dataset (project folder) owned by the caller. */
  dataset_id?: string;
  /** Individual spectrum ids owned by the caller. Combined with the
   *  dataset's members when both are given. */
  spectrum_ids?: string[];
  /** Optional free-text question (max 500 chars). Only answered when it's
   *  about processing the caller's own spectra. */
  question?: string;
}

export interface SuggestedPreprocessing {
  /** One of the 13 registered algorithm step types, e.g. `raman.snv`. */
  step_type: string;
  /** Params already coerced/validated against the algorithm's schema
   *  server-side; unknown/invalid keys are stripped before you see them. */
  params: Record<string, unknown>;
  rationale: string;
}

export interface SuggestedAnalysis {
  /** A supported analysis type, e.g. `pca` or `pca_kmeans`. */
  analysis_type: string;
  rationale: string;
}

export interface LabConsultResult {
  observations: string[];
  suggested_preprocessing: SuggestedPreprocessing[];
  suggested_analyses: SuggestedAnalysis[];
  caveats: string[];
  /** The model that produced this advice, so it can be shown alongside it. */
  model?: string | null;
}

/**
 * `POST /v1/lab/consult` — full account only. Read-only: sends the model a
 * compact statistical summary of the caller's own spectra and returns
 * processing advice. Never mutates anything. 503 when no LLM is configured;
 * 404 for any spectrum/dataset the caller doesn't own.
 */
export function labConsult(
  body: LabConsultBody,
  opts?: ApiClientOptions,
): Promise<LabConsultResult> {
  return apiRequest<LabConsultResult>("/v1/lab/consult", {
    ...opts,
    method: "POST",
    body,
  });
}
