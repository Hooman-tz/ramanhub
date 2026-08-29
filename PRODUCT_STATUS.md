# Spectra Insight — Product Status

_Assistant-maintained. Updated at every milestone boundary. Last update: 2026-08-29 (M5 shipped — web beta feature-complete)._

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

**M1 shipped (same branch):** cherry-picked from Track A onto Track B —
`findings`/`finding_entries`/`finding_spectra` tables + router at
`/v1/findings`, the `follows`/`handle_history` tables, `spectra.accession` +
`RH-S-`/`RH-F-` accession sequences, `users.onboarded_at`, and the
engagement-ranked `/v1/feed` (Following/Discover tabs, `app.ranking` — used
only by feed + trending, never search, ADR-004 intact). Note-only findings
publish with no spectrum gate (the low-friction "post"). Alembic Migration 1
(`f2b1e9c4d7a3`) applies clean from scratch; single head. Backend tests:
**355 pass** (350 prior + 4 new `test_findings_feed_m1` + the `onboarded_at`
column-list fix); the 11 pre-existing failures (trending ×3, search ×2,
processing ×1, ingestion ×5) are unchanged — none regressed.

**Local DB note:** the dev `ramanhub` database is stamped at Track A's alembic
head (`1e817525ab60`) and can't run the Track B chain. M1 was verified on a
fresh `ramanhub_m1test` DB. Before running the app locally against `backend/`,
recreate the dev DB (`dropdb ramanhub && createdb ramanhub && cd backend &&
uv run alembic upgrade head && make -C .. seed`).

**M2 shipped (same branch):** `apps/web` now leads with the feed. `/` is the
Feed (Discover / Following tabs) with an inline note composer; `/findings/[id]`
detail; `/u/[handle]` profile (thin — follow button + bio come in M4).
`@ramanhub/api-client` gained `getFeed` / `getFinding` / `createFinding` /
`publishFinding` / `postNote` / `getSession` and the `FeedItem` / `Finding`
types. React Query wired in `providers.tsx`; server components forward the
session cookie via `lib/server-api.ts`. Brand tokens swapped pink→RamanHub
blue (hue 258) in `tooling/tailwind/theme.css`. `pnpm typecheck` 10/10,
`pnpm --filter @ramanhub/web build` green; live: `GET /api/v1/feed` proxies
through the web server and returns findings; `/` renders the feed shell.
Posting from a browser needs a signed-in full account (Google OAuth not
configured locally; email/password lands in M3) — the composer shows the
sign-in CTA otherwise.

**M3 shipped (same branch):** the social backend is complete for the beta.
_Social primitives cherry-picked from Track A:_ `Share` model + `shares` table;
`Vote`/`Comment` retargeted to "spectrum XOR finding" (`Comment` keeps a 3-way
target so Track B's `community_posts` still work) with `parent_id` one-level
threading; routers `follows.py` + `shares.py` (new) and finding branches added to
`votes.py` / `comments.py`; the feed's `share_count` ranking input restored.
_OAuth signup breadth (Google + GitHub + ORCID — email/password deferred):_
`auth_identities` table + `resolve_or_create_user` upsert, `users.google_sub` /
`users.email` now nullable, `migrate_guest_data` extracted to a shared module so
every provider reuses it, new `auth/github_oauth.py`, ORCID promoted from
link-only to a sign-in provider, `/auth/{github,orcid}/{login,callback}` routes,
`google_sub` dropped from the JWT, `Authorization: Bearer` accepted alongside the
cookie. _Onboarding:_ `GET /v1/users/handle-available`, `GET /v1/users/suggested`,
`POST /v1/users/me/onboarding` (sets handle, display name, `research_interests`,
`is_profile_public`, `onboarded_at`). Alembic Migrations `d4a7c1e93b25` →
`e5b8d2fa4c36` → `a7f3c1d9e2b4`, single head, verified from scratch. Backend
tests: **379 pass**; **`test_trending ×3` fixed** (idempotent-spectrum test bug);
the remaining 8 failures (`test_search ×2`, `test_processing_api ×1`,
`test_ingestion_api ×5`) are unchanged and deferred to M5. `ruff` clean.

**M4 shipped (same branch):** the web app is a full social client and the
legacy frontend is gone. `apps/web` gained `follow-button`, `finding-actions`
(vote + share), `finding-comments`, a 3-provider `/login` (Google / GitHub /
ORCID + guest), a 3-step `/onboarding` wizard (live handle check, interests,
follow-3), a `<RequireOnboarding>` guard, and an enriched `/u/[handle]` profile
(follower counts, verified-ORCID badge, interests, follow button).
`@ramanhub/api-client` gained 14 typed methods (follow status/toggle,
followers/following lists, finding votes/shares/comments, `checkHandle`,
`getSuggestedUsers`, `submitOnboarding`, `getUserByHandle`, GitHub/ORCID login
URLs). **`frontend/` deleted** (59 files); CI's `frontend` + `e2e` jobs replaced
with a `web` job (`pnpm install` + `pnpm typecheck` + `pnpm --filter
@ramanhub/web build`); `README.md`, `replit.md`, `render.yaml` updated to the
monorepo + "Vercel Root Directory = `apps/web`" topology. `pnpm typecheck`
10/10; `pnpm --filter @ramanhub/web build` green (`/`, `/login`, `/onboarding`
static; `/findings/[id]`, `/u/[handle]` dynamic).

**M5 shipped (same branch):** the web beta is feature-complete and the test
suite is fully green. All 8 remaining backend failures fixed — every one was a
stale test/fixture (not product code): `test_search ×2` (helpers must inject
`laser_wavelength_nm` through the ingestion job, and use one raw file per draft
now that `spectra.raw_file_id` is unique), `test_processing_api ×1` (upsert the
now-seeded field def; PATCH must include the now-required `integration_time_ms`),
`test_ingestion_api ×5` (module teardown must delete `Spectrum` before `RawFile`
now that `PATCH /ingestion-jobs/{id}` creates a draft spectrum — one bad teardown
was poisoning the rest of the module). **`uv run pytest` → 382 passed, 0 failed,
0 errors**, stable across randomized runs. CI's `backend` job gained an "assert a
single Alembic head" step. `apps/web` gained real `/terms` + `/privacy` pages
(shared `LegalDoc` shell, consent links on `/login`). `docs/OPERATIONS.md` §5
documents Google/GitHub/ORCID OAuth-app registration (redirect URIs per env, env
vars, the per-instance in-memory rate-limiter caveat). ADR-004 amended
("engagement ranks `/feed` + `/trending`, never `/search`"); ADR-007 moved to
**Accepted** (3 OAuth providers via `auth_identities`). `dependabot.yml`
repointed off the deleted `frontend/`.

**Next action:** the web beta (M0–M5) is done on `integration/social-forward`
and unpushed. Owner steps to go live: review the branch, merge to `main`,
register the three OAuth apps + set their secrets (see `docs/OPERATIONS.md` §5),
deploy the API (Render) and `apps/web` (Vercel, Root Directory `apps/web`), then
smoke-test a real signup. Deferred to later pushes: the Expo mobile app (M-mobile),
extracting the Python processing worker (M6), the Go API service (M7).

---

## Milestones

| Milestone | Goal | Demo | Status | PR | Blocking tests |
|---|---|---|---|---|---|
| **M0** | One monorepo: fold in `social-app/`, strip tRPC/Drizzle/Better-Auth, `apps/web` + `apps/mobile` + `packages/{ui,validators,api-client}`, backend unchanged | `pnpm typecheck` green; web page reads FastAPI `/health` through the `/api/*` proxy | **Shipped** (branch `integration/social-forward`; typecheck 10/10, web build ok; live proxy check pending) | — | none |
| **M1** | Backend: cherry-pick `findings` + `feed` + accessions from Track A onto Track B; Alembic Migration 1; note-only findings can publish | `POST /v1/findings` (note) → publish → `GET /v1/feed?filter=all` returns it | **Shipped** (migration `f2b1e9c4d7a3`; 355 tests pass; Bearer-token auth deferred to M3) | — | none |
| **M2** | Web: feed is the app — Following/Discover tabs, inline composer, finding detail, profile; port OKLCH tokens | Open web app → land on feed → post a note → see it → open a profile | **Shipped** (typecheck 10/10, web build green, feed proxies live; browser posting needs M3 auth) | — | none |
| **M3** | Backend: follow graph + `shares` + votes/comments on findings; `auth_identities` + Google/GitHub/ORCID signup (email/pw deferred) + onboarding endpoints | GitHub + ORCID sign-in work; onboarding (follow 3) → Following feed fills | **Shipped** (`9fb9c1e`; migrations `d4a7c1e93b25`→`e5b8d2fa4c36`→`a7f3c1d9e2b4`; 379 tests pass) | — | fixed `test_trending ×3` |
| **M4** | Web: follow / vote / share / comment UI, onboarding wizard, 3-provider `/login`, `<RequireOnboarding>`; **delete `frontend/`**; point Vercel at `apps/web` | Full new-user journey on web; old frontend gone; CI green | **Shipped** (typecheck 10/10, web build green; `frontend/` deleted; CI `web` job) | — | none |
| **M5** | Fix remaining backend failures; single-alembic-head CI check; real legal pages; `docs/OPERATIONS.md` OAuth-app registration. _(Expo mobile is a separate post-beta push.)_ | `pnpm typecheck` + web build + `uv run pytest` all green; a stranger signs up unaided | **Shipped** (382 tests pass, 0 fail; `/terms` + `/privacy` live; CI single-head step) | — | fixed `test_search ×2`, `test_processing_api ×1`, `test_ingestion_api ×5` |
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
| `test_trending` | 3 | idempotent-spectrum test bug (reused one raw file for N spectra) | M3 | **Fixed (M3)** |
| `test_search` | 2 | helpers didn't route `laser_wavelength_nm` through the ingestion job; shared raw file after `raw_file_id` went unique | M5 | **Fixed (M5)** |
| `test_processing_api` | 1 | test inserted a now-seeded field def; PATCH omitted the now-required `integration_time_ms` | M5 | **Fixed (M5)** |
| `test_ingestion_api` | 5 | module teardown deleted `RawFile` before the draft `Spectrum` that `PATCH /ingestion-jobs` now creates | M5 | **Fixed (M5)** |

**Backend suite: 382 passed, 0 failed, 0 errors.**

---

## Changelog

- **2026-08-28** — Project unification plan agreed (one monorepo, FastAPI API,
  social-first frontend, Go backend post-beta). `PRODUCT_STATUS.md` created.
- **2026-08-28** — **M0 shipped** on `integration/social-forward`. Monorepo
  consolidated; `social-app/` removed; tRPC/Drizzle/Better-Auth stripped;
  `@ramanhub/api-client` added; `/api/*` proxy wired. `pnpm typecheck` 10/10,
  `pnpm --filter @ramanhub/web build` green.
- **2026-08-28** — **M1 shipped**. Findings threads + `/v1/feed` + follow-graph
  tables + accessions cherry-picked onto `backend/`. Migration `f2b1e9c4d7a3`
  applies clean; 355 backend tests pass, 11 pre-existing failures unchanged.
  `app.ranking` reworded — engagement ranks feed/trending only, never search.
- **2026-08-29** — **M2 shipped**. `apps/web` feed-first: `/` Feed
  (Discover/Following) + inline composer, `/findings/[id]`, `/u/[handle]`.
  api-client feed/findings methods + React Query. Brand tokens → blue.
  typecheck 10/10, web build green, feed verified live through the proxy.
- **2026-08-29** — **M3 shipped** (`9fb9c1e`). Social primitives cherry-picked
  (`Share`, Vote/Comment retarget + `parent_id`, `follows`/`shares` routers,
  feed `share_count`); OAuth breadth (`auth_identities`, `resolve_or_create_user`,
  GitHub OAuth, ORCID promoted to sign-in, guest-migration shared module,
  `google_sub` out of the JWT, Bearer auth); onboarding endpoints. Alembic
  `d4a7c1e93b25`→`e5b8d2fa4c36`→`a7f3c1d9e2b4`, single head. 379 tests pass;
  `test_trending ×3` fixed. Email/password signup deferred post-beta.
- **2026-08-29** — **M4 shipped**. `apps/web` is a full social client:
  follow/vote/share/comment components, 3-provider `/login`, `/onboarding`
  wizard, `<RequireOnboarding>` guard, enriched profile; 14 new api-client
  methods. Legacy `frontend/` deleted (59 files); CI `frontend`+`e2e` jobs
  replaced with a pnpm `web` job; README/replit.md/render.yaml updated to the
  monorepo + Vercel-`apps/web` topology. typecheck 10/10, web build green.
- **2026-08-29** — **M5 shipped** — web beta feature-complete. All 8 remaining
  backend test failures fixed (all stale-test, no product change): `uv run
  pytest` → **382 passed, 0 failed, 0 errors**. CI `backend` job asserts a
  single Alembic head. Real `/terms` + `/privacy` pages; `docs/OPERATIONS.md`
  §5 = Google/GitHub/ORCID OAuth-app registration. ADR-004 amended, ADR-007
  → Accepted. `dependabot.yml` off the deleted `frontend/`.
  **M0–M5 complete on `integration/social-forward` (unpushed).**
