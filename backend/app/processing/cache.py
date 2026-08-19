"""Processed-output cache: read-through cache of "raw file + ledger ->
processed (wavenumbers, intensities) numpy pair", backed by `ProcessedCache`
rows plus `.npz` blobs in `settings.S3_BUCKET_PROCESSED`.

Raw-spectrum loading itself lives in `app.spectra_io` (shared with Module 3
visualization and Module 4 search, which also need spectrum arrays) — see
that module's docstring for the Module 1 <-> Module 2 integration seam this
was originally built around.
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
from app.spectra_io import load_raw_spectrum
from app.storage.s3_client import download_bytes, upload_bytes


def compute_cache_key(raw_file_id: UUID, ledger_hash: str) -> str:
    return hashlib.sha256(f"{raw_file_id}:{ledger_hash}".encode()).hexdigest()


def get_or_compute(raw_file_id: UUID, ledger: Ledger, db: Session) -> tuple[np.ndarray, np.ndarray]:
    """Read-through cache for a ledger's processed output. Returns
    `(wavenumbers, intensities)` — the wavenumber axis passes through each
    algorithm step unchanged (all current algorithms only transform
    intensity), while intensities are replayed through the ledger's steps.

    On hit: downloads the cached `.npz` from `S3_BUCKET_PROCESSED`, bumps
    `hit_count`/`last_accessed_at`, returns the pair.

    On miss: loads the raw spectrum (`app.spectra_io.load_raw_spectrum`),
    replays each ledger step in `order` via `algorithms.registry.get_algorithm`
    against the intensity array, serializes both arrays to a compressed
    `.npz`, uploads it to `S3_BUCKET_PROCESSED` under
    `f"{raw_file_id}/{ledger_hash}.npz"`, writes a `ProcessedCache` row, and
    returns the pair.

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
        npz = np.load(io.BytesIO(payload))
        cached.hit_count += 1
        cached.last_accessed_at = datetime.now(UTC)
        db.add(cached)
        db.commit()
        return npz["wavenumbers"], npz["intensities"]

    ledger_row = db.query(ProcessingLedger).filter_by(ledger_hash=ledger_hash).one_or_none()
    if ledger_row is None:
        raise ValueError(
            f"No persisted ProcessingLedger found for hash {ledger_hash!r} — "
            "create/dedupe the ledger row before computing its cache."
        )

    raw_file = db.get(RawFile, raw_file_id)
    if raw_file is None:
        raise ValueError(f"RawFile {raw_file_id} not found")

    wavenumbers, intensities = load_raw_spectrum(raw_file)
    for step in sorted(ledger.steps, key=lambda s: s.order):
        algorithm, _version = get_algorithm(step.type)
        intensities = algorithm(intensities, **step.params)

    buffer = io.BytesIO()
    np.savez_compressed(buffer, wavenumbers=wavenumbers, intensities=intensities)
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
    return wavenumbers, intensities
