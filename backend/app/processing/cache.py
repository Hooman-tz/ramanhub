"""Processed-output cache: read-through cache of "raw file + ledger ->
processed numpy array", backed by `ProcessedCache` rows plus `.npz` blobs in
`settings.S3_BUCKET_PROCESSED`.

INTEGRATION SEAM (Module 1 <-> Module 2): `RawFile` (owned by the ingestion
module) has no numeric-array accessor as of this writing — Module 1's
parsers (`app/ingestion/parsers/*`) extract *metadata* (`ExtractedMetadata`)
from raw uploads, not a persisted numeric spectrum array. `_load_raw_spectrum`
below is a deliberately minimal placeholder: it downloads the raw bytes and
does a permissive two-column (wavenumber, intensity) text parse, keeping
only the intensity column, skipping blank/header/non-numeric lines. This
mirrors the plain-text vendor formats already supported by ingestion (e.g.
Ocean Insight's `>>>>>Begin Spectral Data<<<<<` blocks) closely enough to be
a reasonable v1 default, but it is NOT vendor-format-aware (no binary
formats, no unit conversion) and should be replaced with whatever proper
parsed-array accessor Module 1 exposes once available.
"""
from __future__ import annotations

import hashlib
import io
from datetime import UTC, datetime
from uuid import UUID

import numpy as np
from sqlalchemy.orm import Session

from app.config import settings
from app.models.processed_cache import ProcessedCache
from app.models.processing_ledger import ProcessingLedger
from app.models.raw_file import RawFile
from app.processing.algorithms.registry import get_algorithm
from app.processing.ledger import compute_ledger_hash
from app.schemas.ledger import Ledger
from app.storage.s3_client import download_bytes, upload_bytes


def compute_cache_key(raw_file_id: UUID, ledger_hash: str) -> str:
    return hashlib.sha256(f"{raw_file_id}:{ledger_hash}".encode()).hexdigest()


def _load_raw_spectrum(raw_file: RawFile) -> np.ndarray:
    """PLACEHOLDER raw-spectrum loader — see module docstring.

    Downloads `raw_file.storage_bucket/storage_key` and attempts a simple
    two-column (wavenumber, intensity) text parse, returning the intensity
    column as a 1-D float array. Lines that aren't a clean "number number"
    pair (headers, blank lines, comments) are skipped rather than raising.
    """
    raw_bytes = download_bytes(raw_file.storage_bucket, raw_file.storage_key)
    text = raw_bytes.decode("utf-8", errors="ignore")

    intensities: list[float] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.replace(",", " ").split()
        if len(parts) < 2:
            continue
        try:
            float(parts[0])
            intensity = float(parts[1])
        except ValueError:
            continue
        intensities.append(intensity)

    return np.asarray(intensities, dtype=float)


def get_or_compute(raw_file_id: UUID, ledger: Ledger, db: Session) -> np.ndarray:
    """Read-through cache for a ledger's processed output.

    On hit: downloads the cached `.npz` from `S3_BUCKET_PROCESSED`, bumps
    `hit_count`/`last_accessed_at`, returns the array.

    On miss: loads the raw spectrum (see `_load_raw_spectrum`), replays each
    ledger step in `order` via `algorithms.registry.get_algorithm`,
    serializes the result to a compressed `.npz`, uploads it to
    `S3_BUCKET_PROCESSED` under `f"{raw_file_id}/{ledger_hash}.npz"`, writes
    a `ProcessedCache` row, and returns the array.

    Requires the ledger to already be persisted as a `ProcessingLedger` row
    (looked up by its content hash) — callers create/dedupe that row first
    (see `app.routers.ledgers.build_and_persist_ledger`) so `ledger_id` is
    available for the `ProcessedCache` foreign key.
    """
    ledger_hash = compute_ledger_hash(ledger.raw_file_id, ledger.schema_version, ledger.steps)
    cache_key = compute_cache_key(raw_file_id, ledger_hash)

    cached = db.query(ProcessedCache).filter_by(cache_key=cache_key).one_or_none()
    if cached is not None:
        payload = download_bytes(cached.storage_bucket, cached.storage_key)
        array = np.load(io.BytesIO(payload))["data"]
        cached.hit_count += 1
        cached.last_accessed_at = datetime.now(UTC)
        db.add(cached)
        db.commit()
        return array

    ledger_row = db.query(ProcessingLedger).filter_by(ledger_hash=ledger_hash).one_or_none()
    if ledger_row is None:
        raise ValueError(
            f"No persisted ProcessingLedger found for hash {ledger_hash!r} — "
            "create/dedupe the ledger row before computing its cache."
        )

    raw_file = db.get(RawFile, raw_file_id)
    if raw_file is None:
        raise ValueError(f"RawFile {raw_file_id} not found")

    array = _load_raw_spectrum(raw_file)
    for step in sorted(ledger.steps, key=lambda s: s.order):
        algorithm, _version = get_algorithm(step.type)
        array = algorithm(array, **step.params)

    buffer = io.BytesIO()
    np.savez_compressed(buffer, data=array)
    storage_key = f"{raw_file_id}/{ledger_hash}.npz"
    upload_bytes(
        settings.S3_BUCKET_PROCESSED, storage_key, buffer.getvalue(), content_type="application/octet-stream"
    )

    cache_row = ProcessedCache(
        cache_key=cache_key,
        raw_file_id=raw_file_id,
        ledger_id=ledger_row.id,
        storage_bucket=settings.S3_BUCKET_PROCESSED,
        storage_key=storage_key,
        hit_count=0,
    )
    db.add(cache_row)
    db.commit()
    return array
