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

## Modality verticals

Raman is the sole accepted analysis and similarity adapter today. NMR and mass
spectrometry must each arrive as independent verticals with their own
canonical-array format and units, parser set, metadata profile, QC policy,
processing catalog, fixtures, feature extractor, overlap/compatibility rules,
and benchmark evidence. Cross-modality analysis and similarity are rejected.