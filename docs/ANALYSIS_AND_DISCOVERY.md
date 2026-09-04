# Reproducible analysis and discovery

## Analysis artifacts

An analysis dataset is a named, owner-scoped selection of at least two spectra
from exactly one modality. It may include the owner’s private spectra and
visible public spectra; private spectra owned by someone else are never
selectable. Dataset membership is ordered and persisted.

Each run snapshots its input manifest before execution. The manifest records
the selected spectrum and raw-file identifiers, immutable raw checksum/object
version, applied processing-ledger hash, and canonicalization version. The run
also records parameters, software versions, quality checks, output, a
content-derived output hash, and a reproducible citation label.

## Local execution

Local PCA and PCA+k-means runs use a signed durable run record. The worker
claims pending local runs, records attempts, verifies the signature before
executing, retries failures up to the stored limit, and observes cancellation
before persisting a result. The same record is the future hosted-executor
contract; moving a run to another worker must not change its input snapshot,
parameters, versions, or output hashing.

Hosted execution is deliberately disabled. Its API path rejects requests until
isolation, quotas, usage accounting, subscription entitlement, audit review,
and cost monitoring are each configured. Local runs are the no-cost default.

## Raman similarity

Similarity is currently an exact Raman-only comparison over persisted,
versioned feature vectors on one shared **absolute** wavenumber grid. Features
are built from canonical raw or ledger-processed arrays, normalized for cosine
geometry, and carry their source hash, canonicalization version, wavelength
extent, point count, and QC eligibility. Spectra are never range-stretched to
fit one another, so peak locations preserve their physical Raman shifts.

Candidates must be visible published Raman spectra with matching feature and
canonicalization versions, valid QC, and at least 80% overlap relative to the
shorter spectrum. A cold request warms missing compact features; later queries
reuse them. `GET /search/index-status` exposes coverage so any move to a new
index is based on corpus and latency measurements, not speculation.

Search remains objective: reactions, votes, comments, reports, and trending
activity cannot affect feature eligibility, ranking, or similarity scores.

## Reference library and mixture deconvolution

The Data Lab's **Library** tab identifies a spectrum against a public corpus of
named compounds — bundled open reference data (RRUFF unoriented high-resolution,
CC-BY) plus user contributions. A reference is not a separate kind of spectrum:
it is an ordinary published `Spectrum` plus a `reference_entries` row carrying
the identity claim, so imports and contributions share one ingestion, storage
and indexing path.

Matching runs in stages, because cosine over the feature vectors is accurate but
linear in corpus size:

1. **Prefilter (SQL).** `spectrum_peaks.binned_cm1` holds each spectrum's peak
   positions quantized to 4 cm-1 buckets under a GIN index, so "which references
   have a band near 1085?" is one index scan. The query fans out ±8 cm-1 around
   its three strongest bands, because a band landing on a bucket edge would
   otherwise be missed. Peak positions are parabola-refined before binning for
   the same reason.
2. **Score.** Cosine over the existing 512-point similarity vectors, on the
   survivors only, reusing `raman_similarity` unchanged.
3. **Deconvolve, on request.** Non-negative least squares over a caller-chosen
   set of references.

If the narrow rung finds nothing the query widens to the primary band alone, and
only then falls back to a full scan. Which rung answered is reported as
`prefilter_stage` — a full scan is both slow and a hint the match is weak, so it
is surfaced rather than hidden. Finding *few* peak-sharing candidates is a
success, not a shortfall: an early draft treated it as failure and fell through
to the full scan the index exists to avoid.

**Trust tiers.** Bundled references are `curated`; user contributions are
`community` — matchable immediately, with no moderation gate, but ranked below a
curated entry at equal similarity (similarity is rounded to 4 dp before the tier
term, or float noise defeats the tie-break). The tier is returned with every
match so the UI can badge it. This is an accepted, bounded risk: a community
entry with a genuinely higher cosine *will* win, which is what "matchable
immediately" means. Reporting flags an entry for review without removing it;
only a moderator can demote or remove.

**Deconvolution returns spectral weights, not concentrations.** Reference
columns are clipped non-negative and L2-normalized before the fit, so a weight
is the share of *spectral contribution*. Raman cross-sections differ by orders
of magnitude between compounds, so converting these to mole or mass fractions
would need per-compound response factors the platform does not have. Two extra
non-negative design columns (constant and ramp) absorb residual background;
without them NNLS inflates the largest component to soak up a DC pedestal and
the composition is quietly wrong. Near-duplicate references — polymorphs, solid
solutions — make the split between them arbitrary while the residual still looks
excellent, so pairwise collinearity and the design matrix's condition number are
reported and shown, not buried.

The reference corpus is excluded from `/search/spectra` and
`/search/similar/{id}` by an anti-join. Those endpoints are discovery over
user-contributed science; identification against known compounds is
`/v1/library/match`, which is index-served. Without the exclusion, thousands of
seeded minerals sharing one publication timestamp would bury real uploads in a
feed ordered by `published_at`.

## Modality verticals

Raman is the sole accepted analysis and similarity adapter today. NMR and mass
spectrometry must each arrive as independent verticals with their own
canonical-array format and units, parser set, metadata profile, QC policy,
processing catalog, fixtures, feature extractor, overlap/compatibility rules,
and benchmark evidence. Cross-modality analysis and similarity are rejected.