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

const isBrowser =
  typeof globalThis !== "undefined" && "window" in globalThis;

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
  return (
    typeof e === "object" &&
    e !== null &&
    "status" in e &&
    "message" in e
  );
}

export interface ApiClientOptions {
  /** Override the resolved base URL. */
  baseUrl?: string;
  /** Bearer token for React Native (web uses the cookie instead). */
  token?: string;
}

export interface RequestOptions extends ApiClientOptions {
  method?: "GET" | "POST" | "PATCH" | "PUT" | "DELETE";
  /** JSON-serializable request body. */
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

  const res = await fetch(`${base}${rel}${qs}`, {
    method: opts.method ?? "GET",
    credentials: "include",
    signal: opts.signal,
    headers: {
      ...(opts.body !== undefined
        ? { "content-type": "application/json" }
        : {}),
      ...(opts.token ? { authorization: `Bearer ${opts.token}` } : {}),
      ...opts.headers,
    },
    body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
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
export function startGuestSession(opts?: ApiClientOptions): Promise<SessionUser> {
  return apiRequest<SessionUser>("/auth/guest", { ...opts, method: "POST" });
}

export function googleLoginUrl(base = "/api"): string {
  return `${base.replace(/\/$/, "")}/auth/login`;
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
  body: { title: string; abstract_md?: string; tags?: string[] },
  opts?: ApiClientOptions,
): Promise<Finding> {
  return apiRequest<Finding>("/v1/findings", { ...opts, method: "POST", body });
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
