# Spectra Insight — Product Architecture & Development Roadmap

**Product:** Spectra Insight
**Tagline:** *Spectra in sight. Spectral insight.*
**Status:** Product and technical roadmap — August 2026
**Repository codename:** RamanHub

## 1. Product thesis

Spectra Insight is a reproducible workspace and trusted commons for spectral
data. It begins with Raman spectroscopy, where users can upload imperfect
real-world files, understand and correct their metadata, process them through
a transparent toolbox, keep work private, and publish a citable public record
when ready.

The long-term product is not a generic social network or an arbitrary-file
converter. It is a set of connected scientific capabilities:

1. **Personal workspace** — private uploads, metadata, processing, visualization,
   reusable routines, and later exploratory analysis.
2. **Trusted public commons** — licensed, provenance-rich datasets and spectra
   that can be cited, searched, compared, and reused.
3. **Scientific community** — publication-linked posts and discussion around
   public records, explicitly separate from scientific search ranking.
4. **Discovery and computation** — scientifically constrained similarity search,
   multi-spectrum exploration, and eventually equivalent local and hosted
   compute options.

The product differentiates through five commitments:

- Deterministic parser support with a guarded AI fallback for messy files
- A private per-user reference library alongside a public commons
- Immutable raw data plus replayable, versioned processing provenance
- DOI/manuscript linkage that is genuinely verified, not just user-entered text
- A social layer that helps researchers discover work without changing
  objective scientific ranking

## 2. Scope and guiding principles

### Raman first, modality contracts before expansion

Raman is the only operational modality in the first launch. The platform may
share identity, ownership, provenance, storage, and publication concepts
across Raman, NMR, and mass spectrometry, but it must not pretend that a
two-column Raman array is a universal representation.

NMR and mass spectrometry will each be separate, accepted verticals with their
own canonical data model, metadata profile, quality checks, parsers,
algorithms, fixtures, and similarity rules. No cross-modality comparison or
processing is allowed without an explicitly validated scientific contract.

### Product principles

- Raw source files are immutable and recoverable.
- The user confirms metadata; AI may suggest, never silently decide.
- Every displayed or published result is traceable to source data and exact
  processing steps.
- Privacy defaults to private; publishing is explicit and reversible only by
  creating a new access state, never by deleting provenance.
- Search answers scientific questions; social popularity belongs only in
  community surfaces.
- Build for hundreds to low thousands of users, measure bottlenecks, then add
  infrastructure deliberately.
- AI output is untrusted input. It may return validated structured extraction
  or a proposed mapping, but it may never execute generated code or modify a
  user dataset without confirmation and isolation.

## 3. Brand, domains, and public surface

### Recommended domain model

| Host | Purpose | Rollout |
| --- | --- | --- |
| `spectra-in.site` | Product landing page, documentation, policy pages, account-level links, and cross-modality navigation | Launch |
| `raman.spectra-in.site` | Raman workspace and Raman public commons | Launch application |
| `api.spectra-in.site` | Stable API boundary shared by current and future modality applications | Launch application |
| `nmr.spectra-in.site` | NMR workspace/commons after the NMR modality contract is accepted | Later |
| `ms.spectra-in.site` | Mass-spectrometry workspace/commons after its modality contract is accepted | Later |

Use one identity namespace, stable public record IDs, and canonical redirects
across hosts. A Raman record may be displayed at the Raman host, while its
citation and API identifier remain stable as the product adds modalities.

### Brand transition

The running code, UI labels, deployment instructions, and existing URLs still
use the RamanHub/older-domain naming. Treat **Spectra Insight** and the hosts
above as the target public brand. Update application copy, canonical URLs,
OAuth redirect URIs, API CORS, deployment configuration, sitemap, sharing
metadata, and redirects together in Stage 2 (trusted publication and public
Raman commons), before issuing stable citation URLs—never as a partial rename.

## 4. Current delivery baseline

The table below is a truthful view of the current RamanHub implementation, not
a claim that the public product is launch-ready.

| Area | Current state | Notes |
| --- | --- | --- |
| Web app and API | **Shipped prototype** | React/Vite PWA, FastAPI, PostgreSQL, health checks, structured logs, and optional error reporting hooks exist. |
| Identity | **Partial** | Guest sessions and Google OAuth flows exist. ORCID is an optional profile value, not a completed sign-in or verified-link flow. |
| Raman ingestion | **Partial** | Deterministic vendor parsers, content/size checks, parser sanity checks, and an AI fallback exist. Jobs currently run in-process and are not durable across restarts. |
| Personal library | **Partial** | Users can create private drafts, process them, and browse an owner-scoped library. Recovery and user-facing workflow polish remain incomplete. |
| Processing toolbox | **Shipped prototype** | Versioned ledgers, cached outputs, routines, charts, despiking, smoothing, baseline correction, fluorescence suppression, normalization, crop, and resampling exist. |
| Metadata and publishing | **Partial** | Draft, published, and embargo states plus licensing exist. Metadata completeness, DOI verification, persisted publication records, and provenance gates do not. |
| Public discovery | **Partial** | Objective metadata filters and Raman similarity search exist. Similarity is a small-corpus, request-time comparison and needs QC/overlap controls before scale. |
| Social/community | **Partial** | Comments, upvotes, and a separate trending surface exist. Posts, public profiles, moderation, reporting, notifications, and sharing are not complete. |
| Multi-spectrum analysis | **Deferred** | PCA, clustering, regression/classification workflows, analysis artifacts, local workers, and hosted jobs are not implemented. |
| NMR and mass spectrometry | **Schema preparation only** | Modality enums/registries exist, but ingestion, representation, algorithms, and discovery are Raman-only. |
| Production operations | **Partial** | Deployment templates and operations notes exist. Production secrets, R2, backups, legal copy, durable jobs, and launch observability must be completed before public launch. |

## 5. Product domain model

The following boundaries keep the three product areas connected without
conflating their rules.

```text
Researcher / identity
        │ owns
        ▼
Personal workspace ── contains ──► immutable raw file
        │                                  │
        │                                  ▼
        │                         ingestion + metadata review
        │                                  │
        ▼                                  ▼
private spectrum ── uses ──► processing ledger ── produces ──► derived output
        │
        │ explicit publication with license, provenance, and optional embargo
        ▼
public spectrum / dataset ── links ──► publication record / DOI snapshot
        │                                      │
        ├── appears in ──► objective scientific search and similarity discovery
        └── may be announced by ──► social post, comments, reactions, reports
```

### Personal workspace

The workspace is the default home for uploads. It holds private raw files,
draft spectra, metadata revisions, processing ledgers, routines, and later
analysis runs. A user can explore and download their data without publishing
anything. A personal reference library is a workspace view, not a weaker copy
of the public commons.

### Toolbox

The toolbox turns a selected private or public spectrum into transparent,
replayable outputs. Its processing order, algorithm versions, parameters, and
input identifiers are part of the record. The interface should guide users
through defensible defaults while always allowing inspection and confirmation.

### Public commons

The commons contains only intentionally published records. It is optimized for
metadata quality, provenance, licensing, citation, scientific search, and
reuse—not engagement metrics. A publication can group one or more spectra or
datasets, preserving author attribution and a stable citable landing page.

### Community layer

The community layer can announce public records, host discussion, and surface
trending activity. It may use reactions and recency, but it never affects
metadata filters, similarity rank, quality flags, or trust tier in core search.

## 6. Core user journeys

### A. Explore privately

1. A guest or signed-in researcher uploads a Raman file.
2. The system stores the original bytes immutably and starts ingestion.
3. Deterministic parsing runs first; the AI fallback is used only when needed.
4. The user reviews extracted metadata, parser confidence, quality flags, and
   suggested naming before confirming a draft.
5. The user visualizes the spectrum, builds a processing ledger, saves a
   reusable routine, and keeps all results private by default.

### B. Publish a trusted record

1. The owner completes required Raman metadata and selects a license.
2. The system validates the current data/QC state and captures immutable
   provenance: raw checksum, parsing details, metadata revision, ledger, and
   data representation version.
3. The user links a DOI. The system resolves and stores a publication snapshot;
   a DOI is only marked verified after the configured verification policy passes.
4. The user publishes immediately or chooses an embargo date.
5. The system creates a stable public record with citations, download rules,
   author/ORCID attribution, and a clear trust/completeness display.

### C. Discover and discuss

1. A visitor searches the public commons by objective scientific fields.
2. They inspect quality, provenance, license, processing history, and the
   linked publication before using a record.
3. They run only scientifically compatible Raman similarity searches.
4. They can view related community posts, comment, react, report abuse, or
   share the public record without altering scientific ranking.

### D. Analyze a collection

1. A researcher selects spectra they are allowed to use.
2. The system records the selection, preprocessing contract, analysis
   parameters, software versions, and output artifacts.
3. Light analysis runs in the workspace; heavier work can later be sent to a
   local worker or an explicitly metered hosted worker using the same contract.
4. Results remain private unless the owner intentionally publishes them.

## 7. Scientific data and provenance contracts

These contracts are the prerequisite for trustworthy publishing and for any
future modality work.

### 7.1 Canonical Raman representation

For Raman v1, the canonical processed representation is a one-dimensional,
ordered set of:

- **Raman shift / wavenumber** in `cm⁻¹`
- **Intensity** with declared source/normalized units

The canonicalization contract must define:

- Axis direction, monotonicity, duplicate-point handling, missing-value rules,
  numeric precision, and permitted interpolation behavior
- A representation version and canonicalization version
- The original raw object as the authoritative archival source
- Whether the output is raw, processed, resampled, or normalized
- The valid input range and any information lost during canonicalization

NMR complex data, multidimensional arrays, MS `m/z` data, chromatograms, and
vendor binary formats must be stored and modeled as modality-specific assets;
they cannot be coerced into the Raman representation.

### 7.2 Metadata contract

Each modality owns a versioned metadata profile made of:

| Level | Raman examples | Publication behavior |
| --- | --- | --- |
| Required | modality, axis/intensity meaning, excitation wavelength, acquisition context, material/sample description, owner, data license | Must pass before public publication |
| Recommended | integration time, laser power, instrument/vendor, objective/grating, sample preparation, concentration, substrate, replicate details | Display completeness state; may be required for selected record types |
| Optional/domain-specific | temperature, solvent, pH, batch, biological/industrial context, custom fields | Preserved with units and definitions |
| Derived | SNR, axis range, point count, parser confidence, QC flags, processing status | Computed and versioned, never silently edited |

The confirmed metadata schema is not merely free-form JSON. It must validate
against the active modality profile at confirmation and again at publication,
while preserving unknown source fields separately for traceability.

### 7.3 Quality-control contract

Every canonical Raman record should expose machine-readable, versioned flags:

- Source/parser type and confidence
- File integrity and canonicalization result
- Axis monotonicity, range, resolution, point count, duplicates, and gaps
- Signal/noise definition and result
- Possible cosmic-ray spikes, fluorescence/background burden, saturation, or
  invalid intensity conditions
- Metadata completeness and manual-review state
- Processing compatibility warnings

Quality flags inform display, filtering, and similarity eligibility. They do
not overwrite the raw source or claim to be scientific certification.

### 7.4 Reproducibility and lineage contract

A public spectrum or analysis output must be reconstructable from:

- Immutable raw-file identifier, content checksum, storage object version, and
  source filename/format facts
- Parser identifier, parser version, parse source, and canonicalization version
- User-confirmed metadata revision and active modality schema version
- Ordered processing ledger schema, algorithm versions, exact parameters, and
  generated ledger hash
- Processing runtime/environment version and derived-output checksum
- Parent/fork/source relationships and routine template, where applicable
- License, publication state history, DOI/publication verification snapshot,
  and timestamps

Raw bytes are never overwritten. Corrections create a new metadata or derived
revision linked to the same immutable source, rather than erasing history.

### 7.5 Publication, license, embargo, and DOI contract

- **Draft:** owner-visible private work; not present in public discovery.
- **Embargoed:** owner-visible private work with a declared release date; public
  visibility must be evaluated consistently in every endpoint and job.
- **Published:** public, licensed, provenance-complete record.
- **Withdrawn/superseded:** a future state that preserves a resolvable record
  and reason without silently deleting citations or lineage.

Publishing requires an accepted license and the required metadata/provenance
gate. A DOI string is not evidence by itself. The system must resolve the DOI,
persist a source snapshot (title, authors, journal, abstract where permitted,
publication date, resolver/source, and retrieval time), record validation
outcome, and reserve the **DOI-verified** label for records that pass the
agreed policy.

## 8. Platform contracts and safety boundaries

### Identity and ORCID

**Provisional recommendation:** use Google as the first sign-in method and let
researchers link and verify an ORCID iD from their profile. This minimizes
account-recovery ambiguity while still presenting ORCID on public scientific
records. A second ORCID sign-in method should only be introduced after account
linking, conflict resolution, and recovery behavior are explicitly designed.

Guest access may support low-friction private exploration, but publishing,
social interactions, saved routines, and persistent collections require a
verified account.

### Access control and storage

Every resource has a consistent visibility policy: raw files, metadata,
processed outputs, analysis artifacts, downloads, comments, posts, and
publication snapshots. Public IDs must not become an authorization mechanism.

Before a public beta, choose and document one enforcement model:

1. database row-level security with a non-owner application role, or
2. a central policy layer applied by every data access path and backed by
   authorization regression tests.

Object storage must remain private by default. Serve private assets through
short-lived authorized URLs or a policy-enforcing application endpoint; never
make a bucket broadly public to simplify previews.

### AI-assisted ingestion

The ingestion sequence is deterministic parser → validated structured fallback
→ user confirmation. The fallback may extract metadata or propose a declarative
mapping that a sandboxed, reviewed converter understands. It must never run
arbitrary AI-generated code against production data or use raw file content
beyond the user-approved processing boundary. Cache successful structural
parses, enforce spending/time limits, and retain an auditable parse result.

### Durable jobs and compute tiers

In-process background jobs are acceptable for local development only. Before
public beta or paid compute, ingestion, AI parsing, batch processing, and
analysis must use durable, idempotent jobs with retry, cancellation,
observability, and owner-aware authorization.

The same versioned analysis contract must be executed by:

- a **local worker** for free, user-controlled heavy workloads, and
- a **hosted worker** for paid, quota-governed workloads.

Hosted compute must have resource isolation, usage accounting, cancellation,
audit logs, and an explicit payment/subscription decision before it is offered.

### API and compatibility

The platform has one stable API namespace at `api.spectra-in.site`. Before any
external client, local worker, or modality-specific application depends on it,
public endpoints must be versioned (for example, `/v1/...`) and their response
schemas documented. Additive fields may be introduced within a version; removed
or meaning-changing fields require a new major version, documented migration
guidance, and a published deprecation window.

The current unversioned internal API is a prototype interface. It must be
migrated behind the first public API version before external integrations,
public SDKs, or NMR/MS applications rely on it. Processing, metadata, QC, and
similarity records continue to carry their own domain-specific versions; an API
version does not replace scientific provenance versions.

### Search and similarity

Core discovery ranks by documented scientific inputs: modality, metadata,
quality flags, provenance/trust filters, and a versioned similarity method.
Social activity never participates.

Raman similarity begins with exact small-corpus comparison only when records
meet compatible axis, overlap, QC, and preprocessing requirements. Persist
versioned feature vectors and benchmarks before adding a vector index or
external search service. Indexing is an optimization decision driven by corpus
size, latency, and relevance evaluation—not a substitute for a valid method.

### Community, moderation, and legal readiness

The community layer requires rate limits, reporting, moderation states, content
retention/deletion policy, notification preferences, and clear separation
between author claims and platform trust indicators. Terms, privacy, acceptable
use, copyright/takedown, and data-license guidance must be reviewed before
public launch; placeholder policy pages are not sufficient.

### Operations

Production requires:

- Secrets only in the hosting secret manager; startup must reject insecure
  default secrets in production.
- Separate migration and runtime database credentials with least privilege.
- Tested automated backups, off-primary retention, and restoration drills.
- Structured application and job logs, error tracking, metrics, and alerts.
- Dependency-update automation and a repeatable security review.
- A documented incident, data-removal, and user-support process.

## 9. Staged delivery roadmap

### Stage 0 — Ratify the Spectra Insight foundation

**Purpose:** make one product/technical source of truth before adding features.

**Deliverables**

- This architecture, decision register, and consistent brand/domain plan
- Canonical Raman, metadata, QC, provenance, DOI, and publication contracts
- Product-owner decisions for identity, license, moderation, hosting, and
  local/hosted compute

**Exit criteria**

- A contributor can state exactly what qualifies as a publishable Raman record.
- Private workspace, public commons, social feed, and objective search have
  distinct data/visibility/ranking rules.
- NMR/MS expansion criteria are documented rather than implied by enum values.

### Stage 1 — Trustworthy private Raman beta

**Purpose:** make the personal workspace reliable enough for invited researchers.

**Deliverables**

- Durable and recoverable ingestion with parser confidence and structured
  failure states
- Validated Raman metadata review and atomic draft creation
- Reproducible pipelines, routines, QC display, provenance capture, and
  private-library workflow improvements
- Full private-data authorization audit and user-journey regression coverage

**Exit criteria**

- A researcher can upload, correct, process, save, reopen, and download a
  private Raman record without data loss or ambiguous ownership.
- A restart does not lose an accepted ingestion/processing job.
- No unauthorized user can read a private raw or derived resource.

### Stage 2 — Trusted publication and public Raman commons

**Purpose:** make published records citable and scientifically defensible.

**Deliverables**

- Publish gates for metadata, license, quality, provenance, and DOI policy
- Persisted publication/DOI records, stable public pages, and citation/export
- Reliable embargo behavior, provenance/lineage views, and permanent redirects
  from any temporary legacy public URLs
- Public profiles and the approved ORCID-linking experience
- Domain/OAuth/CORS/redirect migration to the accepted Spectra Insight hosts
  before issuing stable public citations

**Exit criteria**

- Every public record clearly communicates its source, processing, metadata
  completeness, license, and trust state.
- DOI-verified has a documented and enforced meaning.
- Public links remain stable and no private content leaks through previews,
  downloads, or search.
- No public record is issued a stable citation URL on a temporary or
  legacy-domain host; the Spectra Insight domain release has been verified.

### Stage 3 — Public commons and community

**Purpose:** make public records discoverable and discussable without turning
the scientific database into an engagement-ranking system.

**Deliverables**

- Dataset/paper announcements, comments, reactions, reporting, moderation,
  notifications, and share previews
- Public author/profile pages and clear community/trust labels

**Exit criteria**

- A visitor can find a public Raman record through objective search, inspect
  its publication context, and participate in a moderated discussion.
- Trending/community surfaces cannot change core scientific search results.

### Stage 4 — Analysis, discovery, and measured scale

**Purpose:** support meaningful multi-spectrum exploration and prepare demand-led
scaling.

**Deliverables**

- Reproducible PCA/clustering-style analysis runs and visual outputs
- Safe dataset selection/export and analysis provenance
- Compatibility-gated, benchmarked Raman similarity with precomputed features
- Durable local-worker and hosted-worker execution contracts

**Exit criteria**

- Analysis outputs can be reproduced from saved inputs and versions.
- Similarity relevance and latency are measured against a representative corpus.
- Hosted workloads have explicit limits, auditability, and a commercial model
  before payment is enabled.

### Stage 5 — New modalities, one vertical at a time

**Purpose:** expand only when the shared platform has proved its trust model.

**Recommended order:** NMR, then mass spectrometry, subject to user demand and
available scientific validation partners.

**Per-modality entry criteria**

- Accepted canonical data and metadata/QC contract
- Real vendor/sample fixtures and domain-expert validation
- Modality-specific parsers, algorithms, visualization, and discovery rules
- Clear rules for what can and cannot be compared to existing records

**Exit criteria**

- A new modality delivers a complete trustworthy journey, rather than a partial
  upload form attached to Raman assumptions.

## 10. Launch gates

Do not announce a public service until all of the following are true:

1. Production secrets are configured and insecure defaults cause startup failure.
2. Private raw and derived data access has been independently tested.
3. Ingestion jobs survive redeployments and report understandable failures.
4. Published Raman records enforce metadata, license, provenance, and DOI
   verification policy.
5. Terms, privacy, content/moderation, data licensing, retention, and takedown
   policies are reviewed for the jurisdictions and users being served.
6. Backups run off the primary system and restoration has been tested.
7. Error tracking, logs, basic alerts, and an owner response process exist.
8. The custom-domain/OAuth/CORS/redirect configuration is deployed as one
   verified release.

## 11. Explicit product-owner decisions

The following must be decided before the affected delivery stage begins:

| Decision | Accountable role | Recommended default | Needed by |
| --- | --- | --- | --- |
| Initial login methods | Product owner | Google sign-in; verified ORCID profile link | Stage 1 |
| ORCID as a second sign-in method | Product owner + technical lead | Defer until account-linking/recovery policy is designed | Stage 2 |
| Default publication license | Product owner + scientific lead | CC BY 4.0, with CC0 where appropriate | Stage 2 |
| DOI verification standard | Scientific lead + technical lead | Resolver-backed snapshot plus stated match/validation rules | Stage 2 |
| Private-data enforcement model | Technical lead | Central policy coverage immediately; evaluate PostgreSQL RLS before public beta | Stage 1 |
| Initial hosting path | Product owner + operations owner | Managed Postgres + private S3-compatible storage + one durable worker path | Stage 1 |
| Hosted compute pricing | Product owner + operations owner | Do not enable until quotas, costs, billing, and support model are approved | Stage 4 |
| Community moderation | Product owner | Named policy, reporting workflow, reviewer roles, retention/takedown rules | Stage 3 |
| NMR versus MS next | Product owner + scientific lead | Choose using validated user demand, fixtures, and scientific partners | Stage 5 |

See `docs/architecture-decisions.md` for the detailed decision register.

## 12. Implementation boundaries

This roadmap does **not** authorize automatic changes to scientific data,
unreviewed generated parsers, NMR/MS support, payment providers, production
hosting, or public launch. Each subsequent delivery task must implement its
accepted contract, add targeted tests, and update this document when a
provisional decision becomes final.
