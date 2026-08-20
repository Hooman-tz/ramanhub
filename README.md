# RamanHub

RamanHub is "GitHub for spectral data" — an open, collaborative, versioned
platform for sharing Raman spectroscopy data, built with the same ethos
GitHub brought to sharing code. It differentiates from existing open
spectroscopy infrastructure through LLM-based parsing of arbitrary/messy
vendor headers, a private per-user reference library alongside the shared
public commons, a social/trending layer kept quarantined from core
scientific search, a freemium compute model (local by default, cloud tier
paid), and DOI/manuscript-linkage as the central trust and provenance
mechanism.

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
   and `ANTHROPIC_API_KEY` (LLM header parsing) only if you're testing those
   features — the core scaffold (API, DB, object storage, migrations) works
   fine with them left blank.

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

### Services

| Service      | Purpose                              | Local URL                       |
| ------------ | ------------------------------------- | -------------------------------- |
| `postgres`   | Metadata, users, DOIs, ledgers        | `localhost:5432`                 |
| `minio`      | S3-compatible object storage (dev)    | API `localhost:9000`, console `localhost:9001` |
| `minio-init` | One-shot bucket bootstrap, then exits | n/a                               |
| `backend`    | FastAPI app (optional; see above)     | `localhost:8000`                 |

MinIO console login is `minioadmin` / `minioadmin` (dev-only credentials,
see `.env.example`).
