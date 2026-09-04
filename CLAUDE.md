# CLAUDE.md — RamanHub / Spectra Insight

One repo, two halves:

- **`backend/`** — the API and the **sole owner of the database**. Python /
  FastAPI + Postgres + SQLAlchemy + Alembic. Owns auth (JWT cookie + OAuth),
  spectral ingestion (vendor parsers + LLM header parsing), the versioned
  processing toolbox, DOI verification, publishing, and (being brought forward)
  the social layer: feed, follow graph, `findings` threads. Runs on Replit
  today. **Migrating to Go post-beta**, keeping Python only for the spectral
  signal-processing code under `backend/app/processing/` + `backend/app/ingestion/`.
- **`apps/` + `packages/` + `tooling/`** — a pnpm + Turborepo monorepo for the
  **frontend**. Talks to `backend/` over REST only.

```
apps/
  web/        @ramanhub/web       Next.js 16 · App Router · React 19 · Tailwind v4   (web)
  mobile/     @ramanhub/mobile    Expo SDK 54 · RN 0.81 · Expo Router               (mobile — built in M5)
packages/
  api-client/ @ramanhub/api-client   typed fetch client for the FastAPI API — the ONLY seam to the backend
  ui/         @ramanhub/ui           shared shadcn/ui components (web)
  validators/ @ramanhub/validators   shared Zod schemas mirroring API contracts
tooling/      eslint · prettier · tailwind · typescript · github
backend/      FastAPI + Postgres — NOT a pnpm workspace member
```

There is **no tRPC, no Drizzle, no Better Auth** — the T3 scaffold's data/auth
packages were removed because FastAPI already owns schema and auth. Do not
re-add them.

Package manager: **pnpm** (`package.json#packageManager`). Node: `.nvmrc`.

## Golden path: add a feature end to end

1. **Backend** — add/extend a SQLAlchemy model in `backend/app/models/`, an
   Alembic revision in `backend/alembic/versions/` (on the current head), and a
   router in `backend/app/routers/` registered in `backend/app/main.py`. New
   endpoints go under `/v1/*`. Never put feed/social/auth logic inside
   `backend/app/processing/` or `backend/app/ingestion/` — those must stay a
   separable Python unit.
2. **Client** — add a typed method + response type in
   `packages/api-client/src/`. Cross-app input schemas go in
   `packages/validators`.
3. **Web** — screens in `apps/web/src/app/**`; shared presentational components
   in `packages/ui`.
4. **Mobile** (M5+) — screens in `apps/mobile/src/app/**` (Expo Router), calling
   the same `@ramanhub/api-client`. Web auth = session cookie via the Next.js
   `/api/*` rewrite; mobile auth = `Authorization: Bearer <jwt>` via
   `apps/mobile/src/utils/session-store.ts`.

## Commands

Frontend (repo root):

| Command | What |
| --- | --- |
| `pnpm i` | install the JS workspace |
| `pnpm dev:web` | run the web app (proxies `/api/*` → `$API_URL`) |
| `pnpm typecheck` | typecheck every JS package |
| `pnpm lint` / `pnpm format` | eslint / prettier across the workspace |
| `pnpm -F @ramanhub/ui ui-add` | add a shadcn/ui component |

Backend (`backend/`):

| Command | What |
| --- | --- |
| `uv run uvicorn app.main:app --reload` | run the API on :8000 |
| `uv run alembic upgrade head` | apply migrations |
| `uv run pytest` | backend test suite |
| `make seed` / `make seed-demo` | reference data / demo content |

## Environment

Root `.env` (copy from `.env.example`) is read by both halves — `backend/` via
pydantic-settings, `apps/web` via `dotenv -e ../../.env`. The frontend only
needs `API_URL`.

## Status

`PRODUCT_STATUS.md` at the repo root is the live milestone tracker. The full
plan is in the session plan file referenced there.

## Context discipline

Input-side tokens dominate cost here — re-reading accumulated context, not
generating output. Keep the main thread small.

- **Offload noisy search.** Broad greps, multi-file sweeps, log trawls, and
  "where is X used" questions go to the `Explore` agent
  (`.claude/agents/`), not the main thread. You want its conclusion, not the
  file dumps — those should die in the subagent's context.
- **Offload verification output.** Full `pytest` / `pnpm typecheck` / build logs
  go through `qa-verifier`. Only the pass/fail delta belongs in the transcript.
- **Read narrowly.** When you know the region you need, read that range rather
  than whole files. Don't re-read a file you just edited to confirm the edit.
- **Start fresh per task.** `/clear` between unrelated tasks. A session carried
  across three tasks re-reads all three on every turn.
