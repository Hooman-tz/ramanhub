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
