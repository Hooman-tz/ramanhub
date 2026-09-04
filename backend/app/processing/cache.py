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
from app.models.spectrum import Spectrum
from app.processing.algorithms.registry import apply_step
from app.processing.ledger import compute_ledger_hash
from app.schemas.ledger import Ledger
from app.spectra_io import DEFAULT_TRACE_INDEX, load_raw_spectrum, load_spectrum_trace
from app.storage.s3_client import download_bytes, upload_bytes


def _trace_suffix(trace_index: int | None) -> str:
    """The part of a cache key that distinguishes traces of the same file.

    Empty for the default trace, deliberately: a raw file used to yield
    exactly one spectrum, so every array cached before multi-trace ingestion
    is keyed without a suffix. Keeping that key means the existing cache and
    every persisted ledger stay valid instead of being silently orphaned.
    """
    if trace_index is None or trace_index == DEFAULT_TRACE_INDEX:
        return ""
    return f":trace{trace_index}"


def compute_cache_key(raw_file_id: UUID, ledger_hash: str, trace_index: int | None = None) -> str:
    return hashlib.sha256(
        f"{raw_file_id}:{ledger_hash}{_trace_suffix(trace_index)}".encode()
    ).hexdigest()


def get_or_compute(
    raw_file_id: UUID,
    ledger: Ledger,
    db: Session,
    *,
    spectrum: Spectrum | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Read-through cache for a ledger's processed output. Returns
    `(wavenumbers, intensities)`, both replayed through the ledger's steps —
    most steps only transform intensity, but `raman.crop`/`raman.resample`
    change the wavenumber axis too, so both arrays are threaded through
    `algorithms.registry.apply_step` and both are cached.

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
    # A ledger describes a recipe and is legitimately shared by every trace of
    # a file; the *result* of applying it is not, so the trace belongs in the
    # cache key. Without this, two spectra from one file would serve each
    # other's processed arrays.
    trace_index = spectrum.source_trace_index if spectrum is not None else None
    ledger_hash = compute_ledger_hash(ledger.raw_file_id, ledger.schema_version, ledger.steps)
    cache_key = compute_cache_key(raw_file_id, ledger_hash, trace_index)

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

    if spectrum is not None:
        wavenumbers, intensities = load_spectrum_trace(spectrum, db)
    else:
        raw_file = db.get(RawFile, raw_file_id)
        if raw_file is None:
            raise ValueError(f"RawFile {raw_file_id} not found")
        wavenumbers, intensities = load_raw_spectrum(raw_file)
    for step in sorted(ledger.steps, key=lambda s: s.order):
        wavenumbers, intensities = apply_step(step.type, wavenumbers, intensities, step.params)

    buffer = io.BytesIO()
    np.savez_compressed(buffer, wavenumbers=wavenumbers, intensities=intensities)
    storage_key = f"{raw_file_id}/{ledger_hash}{_trace_suffix(trace_index)}.npz"
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
