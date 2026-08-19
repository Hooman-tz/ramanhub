# SYSTEM INSTRUCTION FOR AI DEVELOPMENT AGENT (v2 — Revised)

## POSITIONING NOTE (read first)
An existing open-source platform, SpectraGuru (NSF POSE-funded, published in
Analytical Chemistry in 2026, PostgreSQL-backed, browser-based, no install),
already covers upload, preprocessing (baseline correction, smoothing,
normalization, despiking, interpolation), peak identification, and
multivariate ML (PCA, clustering, classification) against a shared spectral
database. Its own stated goal is to become open, reproducible infrastructure
for the spectroscopy community — close to this project's mission.

This project's differentiation must therefore be explicit and load-bearing in
every module below, not assumed:
1. LLM-based parsing for arbitrary/messy vendor headers, not just
   standardized upload
2. A private per-user reference library alongside the shared public commons
3. A social/trending layer, quarantined from core scientific search
4. A freemium compute model (local by default, cloud tier paid) — this is a
   product, not grant-funded academic infrastructure
5. DOI/manuscript-linkage as the central trust and provenance mechanism, tied
   to the actual publication workflow

If a proposed feature doesn't serve one of these five, treat it as lower
priority — it's likely already solved elsewhere.

Core framing: this is "GitHub for spectral data" — GitHub for sharing code,
this platform for sharing spectra, with the same open, collaborative,
versioned ethos. Hands-on testing of SpectraGuru confirms preprocessing
quality and interface polish are the two biggest, most winnable gaps —
prioritize both heavily.

## PREREQUISITES — DO THESE BEFORE / ALONGSIDE BUILDING
Everything here is something only you can do (create accounts, obtain
credentials) — the coding agent needs the resulting keys/IDs as environment
variables, but can't get them itself.
1. Register a domain name (Cloudflare Registrar or Namecheap are both fine)
2. Create a Google Cloud Console project → OAuth 2.0 Client ID/Secret, for
   login
3. Create a Cloudflare account → an R2 bucket → an R2 API token (object
   storage)
4. Create an Anthropic Console account → an API key, and set a monthly
   spending cap/alert immediately
5. Create a GitHub repo for the codebase (public fits the "GitHub for data"
   framing, and doubles as the bug tracker via Issues)
6. Create a Sentry account (free tier) for error tracking
7. Create a Vercel or Netlify account for frontend hosting
8. Ask Edward Grant to sponsor a Digital Research Alliance of Canada (UBC
   ARC) cloud account for you — free hosting built for exactly this kind of
   research web portal, but sponsorship + setup can take some back-and-forth,
   so start it in parallel rather than waiting on it (see Hosting below)
9. Decide the default data license now (CC-BY 4.0 is the sane default) and
   draft a short Terms of Service / Privacy Policy before public launch —
   you're collecting accounts and user data from day one, this shouldn't be
   an afterthought

## GUIDING PRINCIPLES
- Simple, traditional architecture over trendy frameworks; lean, efficient,
  scientifically precise code
- Build for the scale you have today (hundreds to low thousands of users),
  not the scale you might have in five years. Leave clean interfaces (the
  ledger pattern below is one) so pieces can be swapped or scaled later
  without a rewrite — don't pre-build infrastructure you have no evidence you
  need yet
- Raw spectral data is immutable and sacred: never overwritten, always
  recoverable
- Confirmed roadmap: Raman first (the primary use case), then expansion to
  mass spectrometry and NMR. Namespace the schema (metadata fields, ledger
  step definitions) by modality from the start so this doesn't force a
  rewrite later — but don't build mass-spec- or NMR-specific features now

## CORE ARCHITECTURE
- Frontend: React or Vue, responsive PWA
- Backend: Python via FastAPI, for direct access to SciPy/NumPy/scikit-learn
- Relational DB: PostgreSQL — metadata, users, DOIs, comments, processing
  ledgers
- Object storage: Cloudflare R2 (S3-compatible) — see Hosting & Deployment
  below for why. Same S3 API as AWS, so nothing else in this spec changes if
  you ever migrate off it
- Cache/queue: Redis, added once synchronous processing becomes a bottleneck
  (see Scaling Posture) — not required for the first version

## HOSTING & DEPLOYMENT
- Frontend: Vercel or Netlify — trivial deploy straight from the GitHub
  repo, free tier, automatic HTTPS and global CDN
- Object storage: Cloudflare R2. 10 GB/month free, and critically, zero
  egress fees — this matters specifically for a data-sharing platform, where
  people repeatedly downloading/viewing shared spectra is the whole point,
  and that's exactly the traffic pattern S3-style providers charge for
- Backend (FastAPI) + Postgres — two viable paths:
  - Free, best fit long-term: Digital Research Alliance of Canada cloud via
    UBC ARC. It's explicitly built for researchers developing web portals
    and continuously-running services, is free once Edward Grant sponsors a
    cloud project, and keeps hosting cost at zero indefinitely. Tradeoff:
    application/setup friction, and research-grade rather than
    commercial-grade uptime support
  - Faster to start, small monthly cost: Railway or Render. Both deploy
    FastAPI + managed Postgres with minimal setup, no sponsorship required.
    Reasonable to start here this week and migrate the backend to the
    Alliance cloud once sponsorship comes through
- All of the above serve HTTPS by default or via a one-line reverse-proxy
  config — never serve the app over plain HTTP

## MODULE 0: IDENTITY, TRUST & LICENSING
- Google OAuth as the only login method — simplest onboarding, and it
  removes password-storage risk entirely. Standard scopes return name,
  email, and profile photo, and nothing about academic affiliation or
  citation metrics — don't rely on Google for anything beyond basic identity
- Optional ORCID iD field in the user's profile (a linked identifier, not a
  second login path) — this is what actually carries scientist credibility
  and powers the DOI-verified trust tier in Module 4
- Mandatory license selection at publish time (CC-BY 4.0 default, CC0
  optional) — needed from day one on a public data repository, not
  retrofitted later
- Every public spectrum links to the contributor's linked ORCID profile, if
  they've added one

## MODULE 1: DATA INGESTION & PARSING
- Try deterministic parsers first, for known vendor header formats (Renishaw
  WiRE, Horiba LabSpec, WITec Project, Ocean Insight, Bruker OPUS, Thermo).
  Fall back to an LLM call only for headers that don't match a known template
- Cache successful LLM-derived parses by a hash of the header structure, so
  the same instrument/software-version signature is never re-parsed by the
  LLM twice — this is what keeps ingestion cheap and fast at scale, more than
  the parsing method itself
- Sanity-check extracted metadata against physically plausible ranges (laser
  wavelength near a known line unless flagged custom, positive integration
  time, etc.)
- Show extracted metadata to the user for confirm/edit before it's committed
  — on a reproducibility-focused platform, metadata accuracy is the product
- Run ingestion (especially any LLM call) as an async job, not inline in the
  upload request
- Optional LLM-assisted rename suggestion for uploaded files, so filenames
  stay consistent and easier for both users and the header-parsing step to
  work with

## MODULE 2: TRACEABLE PROCESSING PIPELINE
- Keep raw-immutable-in-storage + processing-steps-as-a-JSON-ledger — this is
  the strongest part of the original design and the right call for
  reproducibility
- Preprocessing suite explicitly includes SNV and MSC normalization and
  dedicated fluorescence-background suppression, not just generic "baseline
  correction" — real-world Raman data (biological, environmental, industrial
  samples) is very often fluorescence-swamped, and handling this well is a
  genuine, specific edge, not a commodity feature
- Cache processed output keyed by hash(raw_file_id + ledger) so repeated
  views don't recompute the same pipeline
- Version-stamp each ledger step with the exact algorithm + parameters, not
  just a method name, so ledgers stay replayable as the codebase evolves
- Add a Draft (private) vs. Published (public, DOI-linked) state. Users can
  process and explore entirely privately — this is the free-tool hook that
  earns trust before asking for data. Publishing is a distinct, explicit
  action, with an optional embargo (private now, auto-released on a set date
  or manual trigger) for pre-publication data, mirroring Zenodo/Figshare
- Let users save a named processing routine (a reusable ledger template) and
  reapply it to new uploads in one action; execution can run server-side or
  be dispatched to a local agent (see Phase 2 compute tiers)

## MODULE 3: VISUALIZATION & CORE UX
- Landing experience drops the user straight into the toolbox (upload/input
  box) on first load, not a static informational page — closer to opening a
  chat app than reading an academic poster, so it's low-friction enough that
  even long-time Raman users fold it into their routine
- Apache ECharts over Plotly for mobile weight/performance
- Downsample large arrays (e.g. LTTB algorithm) before sending to the client
  for high-resolution or hyperspectral-adjacent data
- Auto-populate paper metadata via Crossref/DataCite DOI lookup rather than
  manual entry

## MODULE 4: DISCOVERY, LIBRARY SEARCH & VALIDATION
- Core search stays on objective metadata (material type, excitation
  wavelength, SNR) — define the SNR calculation once, explicitly, and apply
  it consistently so it's actually comparable across submissions
- Spectral similarity / library search: cosine similarity or
  correlation-based matching returning nearest-neighbor spectra from the
  database. Prioritize this — it plays directly to the ML background behind
  this project
- Personal reference library: a private per-user collection, separate from
  the shared commons, searchable on its own, with individual entries
  promotable into the public database
- Trust tiers, surfaced as a filter: "DOI-verified" (linked to a published,
  peer-reviewed paper) vs. "community" (unreviewed) — distinct from social
  voting
- Social features (upvote/comment) stay quarantined to a separate Trending
  feed and never affect core search ranking
- Basic rate limiting on uploads and votes to blunt spam/abuse

## MODULE 5: SECURITY, LOGGING & OPERATIONS
- Secrets (OAuth secret, LLM API key, DB credentials, R2 tokens) live only
  in environment variables or the hosting platform's secret manager — never
  in the git repo, even a private one. Commit a `.env.example` with empty
  placeholders instead
- Validate uploaded files by content, not file extension; enforce a size
  limit; run header/spectrum parsing in a resource-limited step so a
  malformed file can't crash or hang the server
- Treat LLM output as untrusted input: strictly validate the returned JSON's
  schema and value ranges before it's written anywhere — never let LLM
  output drive a raw database query or file path directly
- Use an ORM (e.g. SQLAlchemy) with parameterized queries, never hand-built
  SQL strings, to close off SQL injection
- The app's database user should be least-privilege, not a superuser;
  automated daily backups stored somewhere other than the primary server
- Row-level access control so Draft/embargoed spectra are visible only to
  their owner — this is the one bug that would matter most, since it
  directly breaks the platform's core trust promise
- Rate limit uploads, votes, and login attempts
- Turn on GitHub Dependabot (free) for automatic dependency vulnerability
  alerts on both the Python and JS sides
- Error tracking via Sentry (generous free tier) — captures stack traces and
  request context automatically, which is what a bug report actually needs
  to be actionable
- Structured (JSON) application logs for key events (upload, processing run,
  auth) — plain rotated log files are enough at this stage; no need for a
  full log-aggregation stack yet
- A simple in-app "report a bug" action that opens a GitHub Issue on the
  repo, pre-filled with the session/error ID — consistent with the
  GitHub-for-data framing, and free

## PHASE 2 (explicitly deferred — don't build in v1)
- Advisory pipeline recommendations: given a spectrum's characteristics,
  suggest a starting processing recipe through a chat-style interface, and,
  after initial unsupervised exploration (clustering/PCA-style), suggest
  candidate downstream approaches (regression, calibration, classification)
  worth trying. Must stay suggest-and-let-the-user-confirm, never
  auto-execute — a UX layer on top of Module 2's deterministic ledger, not a
  replacement for it
- Compute tiers: local CPU/GPU execution free by default (user's own
  machine) for heavier ML workflows; a paid tier offers hosted cloud compute
  for the same. The platform itself does not train or host custom models as
  a core free feature — it validates, processes, and supports unsupervised
  exploration (PCA-style), not model training

## SCALING POSTURE
- Launch: single FastAPI instance + Postgres + R2. Synchronous processing is
  fine for MVP validation
- Add a Redis-backed job queue (Celery or RQ) once upload volume or
  processing time makes synchronous painful — this is also where LLM parsing
  calls belong
- Add a CDN in front of object storage, plus the processed-spectrum cache,
  once read traffic grows
- Add a read replica or dedicated search index (Postgres full-text, or
  OpenSearch/pgvector for the similarity search) only when query patterns
  actually demand it
- Don't build any of the above ahead of evidence you need it

## DEVELOPMENT DIRECTIVE
- Begin by defining the PostgreSQL schema and the basic upload-to-storage
  flow (Cloudflare R2, S3-compatible)
- Build the backend in isolated, testable functions
- The LLM is a functional text parser for ingestion only in v1 — never an
  autonomous agent modifying data or pipelines unsupervised. The Phase 2
  advisory feature, when built, only suggests
- Keep all code lean, efficient, and scientifically precise
