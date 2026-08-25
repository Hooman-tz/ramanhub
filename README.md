# RamanHub

RamanHub is "GitHub for spectral data" — an open, collaborative, versioned
platform for sharing Raman spectroscopy data, built with the same ethos
GitHub brought to sharing code. It differentiates from existing open
spectroscopy infrastructure through LLM-based parsing of arbitrary/messy
vendor headers, a private per-user reference library alongside the shared
public commons, a social layer that is integrated with — rather than
quarantined from — core scientific search (see "Ranking policy" below), a
freemium compute model (local by default, cloud tier paid), and
DOI/manuscript-linkage as the central trust and provenance mechanism.

The backend is Python/FastAPI (for direct access to SciPy/NumPy/scikit-learn),
backed by PostgreSQL for metadata and an S3-compatible object store
(MinIO locally, Cloudflare R2 in production) for raw and processed spectra.
The frontend is a React PWA. Raman spectroscopy is the initial modality,
with the schema namespaced from the start to support mass spectrometry and
NMR later without a rewrite.

## Local development

1. Copy the environment template and fill in secrets you need:

   ```bash
   cp .env.example .env
   ```

   Fill in `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` (Google OAuth login)
   and **one** LLM key — either `OPENROUTER_API_KEY` or `ANTHROPIC_API_KEY`
   — only if you're testing those features. The core scaffold (API, DB,
   object storage, migrations) works fine with them left blank.

   See [LLM header parsing](#llm-header-parsing) for which key does what.

2. Start Postgres + MinIO:

   ```bash
   make up
   ```

   No Docker available? Set `STORAGE_BACKEND=local` in `.env` and object
   storage becomes plain files under `storage-data/` (dev only — you still
   need a reachable Postgres). Everything else works identically.

3. Run database migrations:

   ```bash
   make migrate
   ```

4. Seed reference data (licenses, field definitions, ledger step
   definitions):

   ```bash
   make seed
   ```

   Optionally add demo content — three published synthetic spectra (one
   fluorescence-swamped for the baseline tools, one with cosmic-ray spikes
   for despiking), votes/comments for the Trending feed, and a
   drag-and-droppable sample file at `sample-data/`:

   ```bash
   make seed-demo
   ```

5. Run the backend with hot reload. For the fastest iteration loop, run it
   directly on the host rather than inside the `backend` container:

   ```bash
   cd backend && uv run uvicorn app.main:app --reload
   ```

6. Run the frontend:

   ```bash
   cd frontend && npm install && npm run dev
   ```

7. Run the backend test suite:

   ```bash
   make test
   ```

### A note on hostnames: `localhost` vs. service names

`.env.example` is written for the common case of running the backend
directly on the host via `uv run` (step 5 above) while Postgres/MinIO run in
Docker with their ports published — so `DATABASE_URL` and `S3_ENDPOINT_URL`
point at `localhost`.

If instead you run the backend *inside* Docker Compose (the `backend`
service, built from `backend/Dockerfile`), `localhost` inside that
container would refer to the container itself, not the `postgres`/`minio`
containers. To handle this without maintaining two versions of `.env`,
`docker-compose.yml` explicitly overrides `DATABASE_URL` and
`S3_ENDPOINT_URL` for the `backend` service to use the in-network service
names (`postgres`, `minio`) — everything else still comes from `.env` via
`env_file`. You don't need to do anything for this; it's just why the
values you see inside the running `backend` container differ from what's
in your `.env` file on disk.

## Processing pipeline

Raw spectra are immutable. Processing is recorded as an ordered ledger of
versioned steps rather than by writing a modified file, so any published
result can be replayed exactly from the raw data plus its ledger. Processed
output is cached by `hash(raw_file_id + ledger)`.

`GET /processing/algorithms` returns the live catalog — step types, labels,
parameter schemas and defaults — which is what the frontend's pipeline
builder renders its inputs from. The steps currently shipped, in the order
a pipeline normally applies them:

| Category | Step type | Notes |
| --- | --- | --- |
| Artifact removal | `raman.despike` | Cosmic-ray removal. Run first — spikes corrupt every later step |
| Smoothing | `raman.smooth.savitzky_golay` | Preserves peak height/width; optional 1st/2nd derivative |
| Baseline | `raman.fluorescence_suppression.airpls` | Default choice for fluorescence-swamped spectra |
| Baseline | `raman.baseline.als` | Asymmetric least squares (Eilers & Boelens) |
| Baseline | `raman.baseline.polynomial` | ModPoly (Lieber & Mahadevan-Jansen) |
| Normalization | `raman.snv`, `raman.msc` | Standard normal variate; multiplicative scatter correction |
| Normalization | `raman.normalize.minmax`, `.vector`, `.area`, `.peak` | Vector matches the geometry of similarity search; peak scales to an internal standard |
| Axis | `raman.crop`, `raman.resample` | The two steps that change the wavenumber axis |

Adding an algorithm means adding one module under
`backend/app/processing/algorithms/` (declaring `STEP_TYPE`, `VERSION`,
`LABEL`, `CATEGORY`, `DESCRIPTION`, `PARAM_SCHEMA` and `apply`) and
registering it in `registry.py`. The seeded `LedgerStepDefinition` rows that
submitted ledgers are validated against are generated from that registry, so
re-running `make seed` is all that's needed to make a new step usable — no
schema restated in two places.

### Previewing a pipeline before committing it

`POST /spectra/{id}/preview` answers "what WOULD this pipeline do": it
replays a client-supplied step list against the raw arrays and returns the
resulting curve, **writing nothing** — no ledger row, no processed-cache
row, no storage object.

That needs its own compute path (`app/processing/preview.py`) rather than
`processing.cache.get_or_compute`, whose contract is a read-through cache
keyed by a persisted ledger's content hash. The reason is not a technicality:
a user changes a parameter several times per step before settling, and
routing that through the persisting path would write a ledger row and a cache
blob for every intermediate pipeline they clicked through on the way to the
one they meant.

Validation is deliberately identical to the commit path, so a preview can
never accept a pipeline that Apply would then reject with a 422. Params that
are individually schema-valid can still be impossible for a particular
spectrum — a crop window outside the measured range, a Savitzky-Golay window
longer than the array — and those surface as a 422 naming the failing step,
not a 500.

The frontend debounces previews at 400 ms and guards against out-of-order
responses; the builder also has undo/redo (`src/lib/useHistory.ts`), which
coalesces consecutive keystrokes in one field into a single undo entry so
Ctrl-Z doesn't degrade into a character-at-a-time backspace.


## LLM header parsing

Most uploads are handled by a deterministic vendor parser. When none
recognizes a file, `app/ingestion/llm_fallback.py` asks a model to extract the
metadata instead.

**Configure one key.** `LLM_PROVIDER` defaults to `auto`, which prefers
OpenRouter when its key is set and falls back to Anthropic:

| Variable | Notes |
| --- | --- |
| `OPENROUTER_API_KEY` | `OPENROUTER` is accepted as an alias |
| `ANTHROPIC_API_KEY` | Direct Anthropic API |
| `LLM_PROVIDER` | `auto` (default), `openrouter`, or `anthropic` |
| `OPENROUTER_MODEL` | Default `qwen/qwen3.7-flash` — tool calling, 1M context, ~$0.03/Mtok in. **Must support tool calling** |
| `OPENROUTER_FALLBACK_MODELS` | Comma-separated; passed to OpenRouter's `models` routing array |

### Check it works: `make check-llm`

Model slugs get renamed and retired, and a stale one fails inside a
background ingestion job where nobody sees it. So don't trust the default
written above — ask OpenRouter:

```bash
make check-llm ARGS='--list'    # what OpenRouter serves right now
make check-llm                  # ...then one real tool call on a real header
make check-llm ARGS='--model qwen/qwen3.8-27b'
```

`--list` prints every Qwen/flash model with **whether it supports tool
calling**, its context length and its price per Mtok — only tool-capable
models can do header extraction. The full run then sends the real
`sample-data/horiba_acetaminophen_785nm.txt` header through the same code
path the parser uses and checks the result against what the header actually
says (785 nm, 3 accumulations, 1800 lines/mm), so a pass means the parser
works rather than that a request returned 200.

`OPENROUTER_FALLBACK_MODELS` is a *chain* for the same reason: OpenRouter's
`models` array skips entries it cannot serve, so a retired slug degrades to
the next candidate instead of failing the upload.

`app/ingestion/llm_providers.py` is the seam. It returns an **unvalidated
dict**; `llm_fallback.py` remains the only thing that decides what may reach
the database, and every response still goes through
`ExtractedMetadata.model_validate`. A schema violation writes nothing.

Two details that matter for cheap models:

- **`provider.require_parameters` is set**, because tool-calling support
  varies between the providers serving a given open model — without it a
  request can be routed to one that ignores `tools` and answers in prose.
- **One corrective retry** feeds the schema-validation error back to the
  model. Small models get structured output wrong more often than frontier
  ones, and naming the offending field recovers most of those.

### Only the header is sent

`_extract_header_text` stops at the first run of numeric data rows.
`sample-data/horiba_acetaminophen_785nm.txt` is 22 kB of which the header is
9 lines / 182 bytes — sending the whole file cost **~5,700 tokens per parse
where ~45 suffice**, and burying nine useful lines under fifteen hundred rows
of numbers is what makes a small model extract badly.

This also repairs the vendor-parse cache. `compute_header_hash` runs over
whatever that function returns, so while it included intensity values every
spectrum hashed differently and `VendorParseCache` missed on *every* upload —
defeating the entire point of a cache keyed on a header template.


## Analysis (descriptive, not a ledger step)

Peak picking, PCA and HCA *describe* a spectrum; they don't transform it.
They therefore live in `backend/app/analysis/`, deliberately outside
`processing/algorithms/` — whose contract is `apply(...) -> intensities` —
so that asking a question about a spectrum never mutates its ledger.

| Endpoint | What it does |
| --- | --- |
| `GET /spectra/{id}/peaks` | Band detection with position, prominence, FWHM (cm⁻¹) and Gaussian-equivalent area |
| `POST /analysis/pca` | PCA over N spectra — scores, loadings, explained-variance ratio |
| `POST /analysis/hca` | Hierarchical clustering — linkage/dendrogram structure |

Two design notes worth knowing before changing this code:

- **The peak threshold is `max(fraction × range, noise_multiple × σ)`, not
  just a fraction of range.** On a noisy spectrum with weak bands, 5% of the
  range sits *below* the noise, and a fraction-only threshold returns fifty
  noise wiggles as "peaks".
- **`estimate_noise_sigma` measures at several lags and keeps the largest.**
  A lag-1 difference assumes independent samples, which stops being true the
  moment Savitzky–Golay smoothing runs — it correlates neighbours, so
  point-to-point differences shrink faster than the noise amplitude does.
  The single-lag estimate came out ~2× too low on smoothed data, and since
  Auto-clean smooths by default, that was the *default* path: 48 reported
  bands on a 6-band spectrum. Regression tests cover both halves.

PCA uses a NumPy SVD rather than `sklearn.decomposition.PCA` because sklearn
always mean-centres with no opt-out, which would make the exposed
`mean_center=False` parameter a lie. Multi-spectrum analyses first align
members onto the **intersection** of their wavenumber ranges (never the
union — extrapolating past a spectrum's measured range invents data),
reusing `raman.resample` so cross-spectrum alignment matches the
user-facing ledger step.

## Accessions, export and citation

Every spectrum and finding carries a human-quotable accession — `RH-S-000042`
/ `RH-F-000042` — minted from a Postgres sequence and resolvable at `/s/…`
and `/f/…`. A UUID is not something anyone types into a manuscript.

| Endpoint | Formats |
| --- | --- |
| `GET /spectra/{id}/download` | `csv`, `tsv`, `json`, `jcamp` (JCAMP-DX 4.24), with `stage=raw\|processed` |
| `GET /spectra/{id}/citation` | `bibtex`, `ris`, `text` |
| `GET /findings/{id}/citation` | same three |
| `GET /findings/{id}/bundle` | Streaming ZIP: per-member raw + processed CSV + `_ledger.json`, plus `README.txt`, `CITATION.bib` and a `manifest.json` carrying a SHA-256 per file |

The bundle re-checks every member against `require_owner_or_public` and
reports how many were withheld in an `X-RamanHub-Skipped-Spectra` header —
a bundle must never become a side channel that leaks a draft.

## Findings: the social layer

A **Finding** is the shareable unit: a thread bundling spectra, analyses,
narrative and a publication DOI. `FindingEntry` rows are the ordered posts
inside it, which is the "add my ML results step by step" mechanism. An
entry's `config` JSONB stores the analysis *parameters*, never a rendered
image, so a posted figure is re-derived from the data on view — reproducible
rather than a screenshot.

Votes and comments target **either** a spectrum or a finding. That is
enforced by a CHECK constraint plus **two partial unique indexes**, not one
plain `UNIQUE(spectrum_id, user_id)`: every finding-vote has a NULL
`spectrum_id`, Postgres treats NULLs as distinct, and a plain constraint
would therefore not constrain finding-votes at all.

## Ranking policy

The architecture doc's original Module 4 rule quarantined social signals from
core search. **That rule has been deliberately reversed** — see the amendment
in `raman-platform-architecture-v2.md` for the full rationale and the
tradeoff it accepts.

`backend/app/ranking.py` is the single definition of the blend, shared by
`/search` and `/feed` so the two can't drift: engagement (weight 1.0,
log-compressed, 30-day half-life), recency (1.5, 365-day half-life) and
DOI-verified status (0.75). `sort=newest` remains a fully popularity-free
ordering.

`/trending` stays a separate endpoint — pure engagement in a fixed window,
inner-joined so zero-vote items are correctly absent. Search must keep using
a correlated scalar vote count instead; an inner join there would silently
hide every spectrum nobody has voted on yet, which is most of the corpus.

## Deployment (production)

Topology: **Vercel** serves the frontend at `https://serds.ca`; **Render**
runs the API at `https://api.serds.ca` (same registrable domain, so the
SameSite=lax session cookie works) plus managed Postgres; **Cloudflare R2**
holds raw/processed spectra. `render.yaml` at the repo root is the Render
blueprint; `frontend/vercel.json` adds the SPA rewrite.

One-time setup:

1. **Cloudflare R2** — create buckets `raw-spectra` and `processed-spectra`
   and an API token. Endpoint is
   `https://<account-id>.r2.cloudflarestorage.com`, region `auto`.
2. **Render** — New → Blueprint → this repo (tracks `main`). Paste the
   `sync: false` secrets: `JWT_SECRET` (generate:
   `python3 -c "import secrets; print(secrets.token_urlsafe(48))"`),
   `GOOGLE_CLIENT_ID`/`GOOGLE_CLIENT_SECRET`, one LLM key
   (`OPENROUTER_API_KEY` or `ANTHROPIC_API_KEY`), the R2
   values, optional `SENTRY_DSN`. Add custom domain `api.serds.ca`.
3. **Vercel** — import the repo, root directory `frontend`, env vars
   `VITE_API_BASE_URL=https://api.serds.ca` and
   `VITE_GITHUB_REPO=Hooman-tz/ramanhub`. Add domain `serds.ca`.
4. **DNS (Cloudflare)** — CNAME `api` → the Render hostname; apex →
   Vercel, per each dashboard's instructions.
5. **Google Cloud Console** — add
   `https://api.serds.ca/auth/callback` to the OAuth client's Authorized
   redirect URIs; move the consent screen out of Testing (or add testers).
6. **Seed** — from the Render service Shell:
   `uv run python -m app.seed.seed_data` (required reference data), and
   optionally `uv run python -m app.seed.demo_data` (demo spectra).

Migrations run automatically before each deploy (`preDeployCommand` in
`render.yaml`). The in-process rate limiter assumes a single instance —
swap in a shared store before scaling horizontally (see
`backend/app/ratelimit.py`). `/terms` and `/privacy` ship placeholder
text — review before announcing publicly.

### Services

| Service      | Purpose                              | Local URL                       |
| ------------ | ------------------------------------- | -------------------------------- |
| `postgres`   | Metadata, users, DOIs, ledgers        | `localhost:5432`                 |
| `minio`      | S3-compatible object storage (dev)    | API `localhost:9000`, console `localhost:9001` |
| `minio-init` | One-shot bucket bootstrap, then exits | n/a                               |
| `backend`    | FastAPI app (optional; see above)     | `localhost:8000`                 |

MinIO console login is `minioadmin` / `minioadmin` (dev-only credentials,
see `.env.example`).
