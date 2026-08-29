# Spectra Insight — Product Status

_Assistant-maintained. Updated at every milestone boundary. Last update: 2026-08-28 (M0 shipped)._

Full plan: `/Users/hooman/.claude/plans/how-is-our-social-gentle-alpaca.md`

---

## Current state

The project is being **unified**. Until now it lived on two incompatible
foundations: a working Python **FastAPI + Postgres** science backend with a thin
React/Vite web UI (RamanHub, deployed on Replit, with two unmerged feature
branches Track A / Track B), and a brand-new empty **`social-app/`** pnpm/Turborepo
scaffold (Next.js + Expo + tRPC + Drizzle + Better Auth).

**Agreed direction:** one monorepo. FastAPI stays the API and sole database owner.
`social-app` becomes the new web (+ later mobile) frontend, talking to FastAPI over
REST. The old `frontend/` is retired. Product is **science-first with the social
layer brought forward** — feed as the landing page, `findings` threads, follow
graph, four signup methods — for an audience of **spectroscopy researchers & grad
students**. Backend goes to **Go post-beta**, keeping Python only for spectral
signal processing.

**M0 shipped (branch `integration/social-forward`):** `social-app/` folded into
this repo and deleted (history dropped). Root is now `apps/{web,mobile}` +
`packages/{api-client,ui,validators}` + `tooling/` + `turbo/` alongside the
untouched `backend/`. tRPC / Drizzle / Better-Auth removed. `@acme`→`@ramanhub`.
New `@ramanhub/api-client` (typed REST client, `getHealth()`); `apps/web`
rewrites `/api/*`→`$API_URL`. `pnpm typecheck` 10/10 green; `pnpm --filter
@ramanhub/web build` succeeds. Not yet run: live `pnpm dev:web` + backend
end-to-end (needs local Postgres) — user hands-on check.

**Next action:** M1 — cherry-pick `findings` + `feed` + accessions from Track A
onto Track B (`backend/`).

---

## Milestones

| Milestone | Goal | Demo | Status | PR | Blocking tests |
|---|---|---|---|---|---|
| **M0** | One monorepo: fold in `social-app/`, strip tRPC/Drizzle/Better-Auth, `apps/web` + `apps/mobile` + `packages/{ui,validators,api-client}`, backend unchanged | `pnpm typecheck` green; web page reads FastAPI `/health` through the `/api/*` proxy | **Shipped** (branch `integration/social-forward`; typecheck 10/10, web build ok; live proxy check pending) | — | none |
| **M1** | Backend: cherry-pick `findings` + `feed` + accessions from Track A onto Track B; Alembic Migration 1; note-only findings can publish; Bearer-token auth | `POST /findings` (note) → `GET /feed?filter=all` returns it | Not started | — | none |
| **M2** | Web: feed is the app — Following/Discover tabs, inline composer, finding detail, profile; port OKLCH tokens | Open web app → land on feed → post a note → see it → open a profile | Not started | — | none |
| **M3** | Backend: follow graph + `shares` + votes/comments on findings (Migrations 2–3); `auth_identities` + GitHub/ORCID/email signup + onboarding endpoints (Migration 4) | Email signup → verify → onboarding (follow 3) → Following feed fills; GitHub + ORCID sign-in work | Not started | — | fixes `test_trending ×3` |
| **M4** | Web: follow buttons, onboarding wizard, 4-provider signup UI; **delete `frontend/`**; point Vercel at `apps/web` | Full new-user journey on web end to end; old frontend gone; CI green | Not started | — | none |
| **M5** | Mobile (Expo) feed + compose + Bearer auth; fix remaining backend failures; single-alembic-head CI check; real legal pages; OAuth redirect URIs registered | Expo Go shows feed + lets you post; `pnpm test` + `pytest` fully green; a stranger signs up unaided | Not started | — | fixes `test_search ×2`, `test_processing_api ×1`, `test_ingestion_api ×5` |
| _M6 (later)_ | Extract `processing/` + `ingestion/` behind an internal API as a standalone Python worker | FastAPI calls the worker as a client; no behavior change | Not started | — | — |
| _M7 (later)_ | Go API service for auth/feed/follows/findings/CRUD/DOI against the same Postgres + `/v1` contract; keep the Python worker | `api-client` base URL cut over to Go; parity | Not started | — | — |

---

## Open decisions

| # | Decision | Recommendation | Resolved? |
|---|---|---|---|
| O1 | Fold monorepo into this git repo vs keep two repos | One repo (delete nested `.git`) | ☐ |
| O2 | Package scope name to replace `@acme` | `@ramanhub` or `@spectra` | ☐ |
| O3 | Web auth transport | Next.js `/api/*` proxy + existing cookie; Bearer for mobile | ☐ |
| O4 | Build Expo now or defer | Scaffold in M0, build in M5 | ☐ |
| O5 | `is_profile_public` default for new signups | Public via pre-checked onboarding step; never mass-flip | ☐ |
| O6 | Publish note-only findings (no spectra) | Yes — first-class citable record, auto default license | ☐ |
| O7 | ADR-004 amendment wording | "Engagement ranks `/feed` and `/trending`; never `/search`." | ☐ |
| O8 | Web hosting | Vercel (`apps/web`); API stays Replit/Render | ☐ |
| O9 | Track A branch after cherry-pick | Keep read-only for reference; delete once M3 lands | ☐ |
| O10 | `handle` vs `profile_handle` naming | Keep `profile_handle`, rewrite ported Track A code | ☐ |
| O11 | When to start the Go migration | After the beta is live and has users | ☐ |
| O12 | New endpoints under `/v1/*` from M1 | Yes — cheap now, required for Go later | ☐ |

---

## Known failing tests (baseline: Track B, ~11)

| Test | Count | Root cause (suspected) | Target milestone | Status |
|---|---|---|---|---|
| `test_trending` | 3 | trending feed assertions | M3 (votes retarget touches this) | Failing |
| `test_search` | 2 | search assertions | M5 | Failing |
| `test_processing_api` | 1 | processing endpoint | M5 | Failing |
| `test_ingestion_api` | 5 | FK-violation / ingestion setup | M5 | Failing |

---

## Changelog

- **2026-08-28** — Project unification plan agreed (one monorepo, FastAPI API,
  social-first frontend, Go backend post-beta). `PRODUCT_STATUS.md` created.
- **2026-08-28** — **M0 shipped** on `integration/social-forward`. Monorepo
  consolidated; `social-app/` removed; tRPC/Drizzle/Better-Auth stripped;
  `@ramanhub/api-client` added; `/api/*` proxy wired. `pnpm typecheck` 10/10,
  `pnpm --filter @ramanhub/web build` green.
