import { getHealth, isApiError } from "@ramanhub/api-client";

// Always rendered per-request — it calls the backend, so it must not be
// prerendered at build time.
export const dynamic = "force-dynamic";

// M0 smoke test: the web app reaching the FastAPI backend. Replaced by the
// feed in M2.
export default async function HomePage() {
  let health: Awaited<ReturnType<typeof getHealth>> | null = null;
  let error: string | null = null;
  try {
    health = await getHealth();
  } catch (e) {
    error = isApiError(e) ? `${e.status} ${e.message}` : String(e);
  }

  return (
    <main className="container flex min-h-screen flex-col items-center justify-center gap-6 py-16">
      <h1 className="text-4xl font-extrabold tracking-tight">
        Spectra<span className="text-primary">Insight</span>
      </h1>
      <p className="text-muted-foreground">
        Monorepo consolidated. Web app is talking to the FastAPI backend.
      </p>
      <div className="bg-muted w-full max-w-md rounded-lg p-4 font-mono text-sm">
        <div className="text-muted-foreground mb-2">GET /api/health</div>
        {health ? (
          <pre className="text-foreground">
            {JSON.stringify(health, null, 2)}
          </pre>
        ) : (
          <span className="text-destructive">
            backend unreachable: {error}
          </span>
        )}
      </div>
    </main>
  );
}
