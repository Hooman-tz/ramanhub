"""Durable, database-backed orchestration of the ingestion pipeline.

The API only persists jobs. A separate worker claims rows with a lease, so
uploads survive API restarts and duplicate workers cannot process one job at
the same time. This keeps the deployment small without making request-bound
FastAPI background tasks responsible for scientific ingestion.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import or_

from app.config import settings
from app.db.base import SessionLocal
from app.ingestion import filename_overlay
from app.ingestion.header_hash import compute_header_hash
from app.ingestion.llm_fallback import extract_metadata_via_llm
from app.ingestion.parsers.registry import find_parser
from app.ingestion.sanity_check import check as run_sanity_check
from app.ingestion.structure import build_preview, extract_trace, resolve_layout
from app.llm_credentials import resolve_for_user
from app.logging_config import log_event
from app.models.enums import IngestionStatus, UploadStatus
from app.models.ingestion_job import IngestionJob
from app.models.raw_file import RawFile
from app.raman_contract import (
    RAMAN_CANONICALIZATION_VERSION,
    canonicalize_raman_arrays,
    checksum_bytes,
)
from app.schemas.ingestion import FileLayout
from app.spectra_io import parse_two_column_raman
from app.storage.s3_client import download_bytes

HEADER_SNIFF_BYTES = 65536
LEASE_SECONDS = 300
HEARTBEAT_INTERVAL_SECONDS = 20
LLM_EXTRACTION_TIMEOUT_SECONDS = min(120, LEASE_SECONDS - HEARTBEAT_INTERVAL_SECONDS)
RETRY_DELAYS_SECONDS = (5, 20, 60)

logger = logging.getLogger(__name__)


class LeaseLostError(RuntimeError):
    """A worker lost its exclusive lease and must not persist stale results."""


@dataclass(frozen=True)
class IngestionClaim:
    job_id: uuid.UUID
    lease_token: str


def run_with_timeout(
    func: Callable[..., Any],
    *args: Any,
    timeout: float,
    on_heartbeat: Callable[[], bool] | None = None,
    **kwargs: Any,
) -> Any:
    """Run `func(*args, **kwargs)` in a worker thread and enforce a
    wall-clock `timeout` (seconds), raising `TimeoutError` if it's exceeded.

    Used to bound vendor-parser execution against a malformed/adversarial
    upload, so it can't hang the ingestion background task indefinitely.
    `concurrent.futures.ThreadPoolExecutor` is used rather than
    `signal.alarm` since the latter is Unix-only and this needs to work
    cross-platform (e.g. under a Windows dev environment or in tests).

    Note: Python cannot forcibly kill a running thread, so on timeout the
    underlying call may still be executing in the background after this
    function returns — the executor is shut down without waiting
    (`wait=False`) specifically so *this* call doesn't itself block on that
    leaked thread. That's an acceptable tradeoff for the goal here (don't
    let the ingestion job / server hang), not a full sandboxing guarantee.
    """
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    future = executor.submit(func, *args, **kwargs)
    deadline = time.monotonic() + timeout
    try:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"Parsing timed out after {timeout}s")
            try:
                return future.result(timeout=min(HEARTBEAT_INTERVAL_SECONDS, remaining))
            except concurrent.futures.TimeoutError:
                if on_heartbeat is not None and not on_heartbeat():
                    raise LeaseLostError("Worker lease was lost while parsing.")
    finally:
        executor.shutdown(wait=False)


async def await_with_lease_heartbeats(
    awaitable: Awaitable[Any],
    *,
    on_heartbeat: Callable[[], bool],
    timeout: float = LLM_EXTRACTION_TIMEOUT_SECONDS,
    heartbeat_interval: float = HEARTBEAT_INTERVAL_SECONDS,
) -> Any:
    """Await network-backed extraction without allowing its worker claim to expire."""
    task = asyncio.ensure_future(awaitable)
    try:
        async with asyncio.timeout(timeout):
            while True:
                done, _pending = await asyncio.wait({task}, timeout=heartbeat_interval)
                if task in done:
                    return task.result()
                if not on_heartbeat():
                    raise LeaseLostError(
                        "Worker lease was lost while awaiting AI metadata extraction."
                    )
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


def _extract_header_text(raw_bytes: bytes) -> str:
    """Best-effort header text: decode a leading chunk of the raw bytes.
    Works directly for text-based vendor formats; for binary formats this is
    a lossy approximation used only for hashing/logging, not for parsing —
    `parse()` on binary formats works from the raw bytes directly.
    """
    chunk = raw_bytes[:HEADER_SNIFF_BYTES]
    return chunk.decode("utf-8", errors="ignore")


def _recover_expired_leases(db) -> None:
    """Return abandoned worker leases to the queue before the next claim."""
    now = datetime.now(UTC)
    recovered = (
        db.query(IngestionJob)
        .filter(
            IngestionJob.status == IngestionStatus.running,
            or_(
                IngestionJob.lease_expires_at.is_(None),
                IngestionJob.lease_expires_at < now,
            ),
        )
        .update(
            {
                IngestionJob.status: IngestionStatus.pending,
                IngestionJob.run_after: now,
                IngestionJob.error_message: "Worker lease expired; safely queued for retry.",
                IngestionJob.lease_token: None,
                IngestionJob.lease_expires_at: None,
            },
            synchronize_session=False,
        )
    )
    if recovered:
        db.commit()


def claim_next_ingestion_job() -> IngestionClaim | None:
    """Atomically lease the next ready job for one worker process."""
    db = SessionLocal()
    try:
        _recover_expired_leases(db)
        now = datetime.now(UTC)
        job = (
            db.query(IngestionJob)
            .filter(
                IngestionJob.status == IngestionStatus.pending,
                or_(IngestionJob.run_after.is_(None), IngestionJob.run_after <= now),
            )
            .order_by(IngestionJob.created_at.asc())
            .with_for_update(skip_locked=True)
            .first()
        )
        if job is None:
            return None
        lease_token = uuid.uuid4().hex
        job.status = IngestionStatus.running
        job.started_at = now
        job.last_heartbeat_at = now
        job.lease_expires_at = now + timedelta(seconds=LEASE_SECONDS)
        job.lease_token = lease_token
        job.attempt_count += 1
        db.add(job)
        db.commit()
        return IngestionClaim(job_id=job.id, lease_token=lease_token)
    finally:
        db.close()


def _claim_job_by_id(db, job_id: uuid.UUID) -> IngestionJob | None:
    """Test/CLI helper that only claims a pending row once."""
    now = datetime.now(UTC)
    job = (
        db.query(IngestionJob)
        .filter(IngestionJob.id == job_id, IngestionJob.status == IngestionStatus.pending)
        .with_for_update(skip_locked=True)
        .one_or_none()
    )
    if job is None:
        return None
    job.lease_token = uuid.uuid4().hex
    job.status = IngestionStatus.running
    job.started_at = now
    job.last_heartbeat_at = now
    job.lease_expires_at = now + timedelta(seconds=LEASE_SECONDS)
    job.attempt_count += 1
    db.add(job)
    db.commit()
    return job


def _renew_lease(db, job_id: uuid.UUID, lease_token: str) -> bool:
    """Extend a lease only if this worker still owns an unexpired claim."""
    now = datetime.now(UTC)
    updated = (
        db.query(IngestionJob)
        .filter(
            IngestionJob.id == job_id,
            IngestionJob.status == IngestionStatus.running,
            IngestionJob.lease_token == lease_token,
            IngestionJob.lease_expires_at >= now,
        )
        .update(
            {
                IngestionJob.last_heartbeat_at: now,
                IngestionJob.lease_expires_at: now + timedelta(seconds=LEASE_SECONDS),
            },
            synchronize_session=False,
        )
    )
    db.commit()
    return updated == 1


def _quality_flags_for_arrays(raw_bytes: bytes, layout: FileLayout | None = None) -> dict[str, str]:
    """Report canonical-array readiness without mutating the immutable raw file.

    Checks the first trace of the detected layout, falling back to the
    historical two-column read when no layout was resolved.
    """
    try:
        if layout is not None and layout.traces:
            x, y = extract_trace(raw_bytes, layout, layout.default_trace_index)
        else:
            x, y = parse_two_column_raman(raw_bytes)
        _canonical_x, _canonical_y, repairs = canonicalize_raman_arrays(x, y)
    except Exception as exc:  # noqa: BLE001 - parser support gaps are actionable QC, not worker crashes
        return {"array": f"canonical Raman array unavailable: {exc}"}
    flags = {f"array.{repair}": "canonicalization repair applied" for repair in repairs}
    if layout is not None and len(layout.traces) > 1:
        flags["array.multi_trace"] = f"{len(layout.traces)} spectra found in this file"
    return flags


def _retry_or_fail(
    db, job: IngestionJob, raw_file: RawFile, lease_token: str, exc: Exception
) -> None:
    now = datetime.now(UTC)
    if job.attempt_count < job.max_attempts:
        delay = RETRY_DELAYS_SECONDS[min(job.attempt_count - 1, len(RETRY_DELAYS_SECONDS) - 1)]
        job_values = {
            IngestionJob.error_message: str(exc)[:2_000],
            IngestionJob.lease_token: None,
            IngestionJob.lease_expires_at: None,
            IngestionJob.last_heartbeat_at: now,
            IngestionJob.status: IngestionStatus.pending,
            IngestionJob.run_after: now + timedelta(seconds=delay),
        }
        raw_status = UploadStatus.uploaded
    else:
        job_values = {
            IngestionJob.error_message: str(exc)[:2_000],
            IngestionJob.lease_token: None,
            IngestionJob.lease_expires_at: None,
            IngestionJob.last_heartbeat_at: now,
            IngestionJob.status: IngestionStatus.failed,
            IngestionJob.finished_at: now,
        }
        raw_status = UploadStatus.failed
    updated = (
        db.query(IngestionJob)
        .filter(
            IngestionJob.id == job.id,
            IngestionJob.status == IngestionStatus.running,
            IngestionJob.lease_token == lease_token,
        )
        .update(job_values, synchronize_session=False)
    )
    if updated != 1:
        db.rollback()
        return
    db.query(RawFile).filter(RawFile.id == raw_file.id).update(
        {RawFile.upload_status: raw_status}, synchronize_session=False
    )
    db.commit()


def _park_for_user_input(
    db,
    job: IngestionJob,
    raw_file: RawFile,
    lease_token: str,
    *,
    metadata,
    flags: dict[str, str],
    header_hash: str,
    parser: tuple[str, str, float],
    preview,
) -> None:
    """Stop and ask the owner what shape this file is.

    Everything already worked out is persisted first — the header metadata,
    the quality flags, and the preview grid the UI will show — so answering
    the question is the *only* work left. Deliberately not a failure and
    deliberately not retried: no number of retries will make an unrecognisable
    layout recognisable, and the bytes are fine.
    """
    parser_used, parser_version, parser_confidence = parser
    now = datetime.now(UTC)
    updated = (
        db.query(IngestionJob)
        .filter(
            IngestionJob.id == job.id,
            IngestionJob.status == IngestionStatus.running,
            IngestionJob.lease_token == lease_token,
        )
        .update(
            {
                IngestionJob.header_hash: header_hash,
                IngestionJob.parser_used: parser_used,
                IngestionJob.parser_version: parser_version,
                IngestionJob.parser_confidence: parser_confidence,
                IngestionJob.canonicalization_version: RAMAN_CANONICALIZATION_VERSION,
                IngestionJob.extracted_metadata_raw: metadata.model_dump(mode="json"),
                IngestionJob.sanity_check_flags: flags,
                IngestionJob.structure_preview: preview.model_dump(mode="json"),
                IngestionJob.layout_source: "unresolved",
                IngestionJob.status: IngestionStatus.needs_input,
                IngestionJob.error_message: (
                    "We couldn't work out how this file is laid out. Tell us where the "
                    "wavenumbers and intensities are and we'll finish reading it."
                ),
                IngestionJob.lease_token: None,
                IngestionJob.lease_expires_at: None,
                IngestionJob.last_heartbeat_at: now,
            },
            synchronize_session=False,
        )
    )
    if updated != 1:
        db.rollback()
        return
    db.query(RawFile).filter(RawFile.id == raw_file.id).update(
        {RawFile.upload_status: UploadStatus.uploaded}, synchronize_session=False
    )
    db.commit()


def _fallback_provenance(source: str, model: str | None = None) -> tuple[str, str, float]:
    """Map an `extract_metadata_via_llm` source to `(parser_used, version,
    confidence)`.

    `parser_used` is written to `RawFile.vendor_format` and
    `IngestionJob.parser_used`, so it is a provenance claim about how a
    spectrum's metadata came to exist. It must not say an LLM read the file
    when none did: `"filename-only"` is the no-key path, where nothing but the
    upload's filename informed those fields, and it is scored well below a
    real header parse to say so.

    `model`, when known, is the model that actually read the header and
    becomes the recorded version — under the free router the configured slug
    is a router, so "which model produced this metadata" is only answerable
    after the call. Falls back to `source` so provenance is never blank.
    """
    if source == "filename-only":
        return "filename-only", source, 0.2
    return f"llm:{source}", model or source, 0.7 if source == "cache" else 0.55


def run_ingestion_job(
    job_id: uuid.UUID,
    *,
    already_claimed: bool = False,
    lease_token: str | None = None,
) -> None:
    """Download the raw file, run deterministic parsers (falling back to the
    LLM on a miss), sanity-check the result, and persist it onto the
    IngestionJob + RawFile rows. Opens and closes its own DB session.
    """
    db = SessionLocal()
    try:
        job = db.get(IngestionJob, job_id) if already_claimed else _claim_job_by_id(db, job_id)
        if job is None or job.status != IngestionStatus.running:
            return
        active_lease_token = lease_token if already_claimed else job.lease_token
        if active_lease_token is None or job.lease_token != active_lease_token:
            return
        if not _renew_lease(db, job.id, active_lease_token):
            return
        raw_file = db.get(RawFile, job.raw_file_id)
        if raw_file is None:
            return
        db.query(RawFile).filter(RawFile.id == raw_file.id).update(
            {RawFile.upload_status: UploadStatus.parsing}, synchronize_session=False
        )
        db.commit()

        log_event(
            logger,
            "ingestion_job.started",
            ingestion_job_id=str(job.id),
            raw_file_id=str(raw_file.id),
        )

        try:
            raw_bytes = download_bytes(raw_file.storage_bucket, raw_file.storage_key)
            if checksum_bytes(raw_bytes) != raw_file.content_hash:
                raise ValueError("raw object checksum does not match the immutable upload record")
            if not _renew_lease(db, job.id, active_lease_token):
                raise LeaseLostError("Worker lease was lost while downloading the raw object.")
            header_text = _extract_header_text(raw_bytes)
            header_hash = compute_header_hash(header_text)

            # This runs in a background worker, so there is no request user —
            # the file's owner is who the LLM work is being done for, and
            # whose own provider key (if they set one) it must use.
            credential = resolve_for_user(db, raw_file.owner_id)

            parser = find_parser(raw_bytes, raw_file.original_filename)
            if parser is not None:
                # Resource-limited parsing: bound vendor-parser execution so
                # a malformed/adversarial file can't hang this background
                # task (and, transitively, the server) indefinitely. See
                # `run_with_timeout`'s docstring for why a thread-based
                # timeout rather than `signal.alarm`.
                metadata = run_with_timeout(
                    parser.parse,
                    raw_bytes,
                    timeout=settings.INGESTION_PARSE_TIMEOUT_SECONDS,
                    on_heartbeat=lambda: _renew_lease(db, job.id, active_lease_token),
                )
                parser_used = parser.vendor_format
                parser_version = parser.version
                parser_confidence = 1.0
                # Deterministic filename overlay: fill only fields the vendor
                # parser left null, from regex hints in the upload's original
                # filename. Never overwrites a file-derived value. The LLM
                # fallback below already applies this to its own result, so
                # this belongs on the parser branch only.
                metadata = filename_overlay.apply(metadata, raw_file.original_filename)
            else:
                llm_meta: dict = {}
                metadata, source = asyncio.run(
                    await_with_lease_heartbeats(
                        extract_metadata_via_llm(
                            header_text,
                            db,
                            filename=raw_file.original_filename,
                            credential=credential,
                            meta=llm_meta,
                        ),
                        on_heartbeat=lambda: _renew_lease(db, job.id, active_lease_token),
                    )
                )
                parser_used, parser_version, parser_confidence = _fallback_provenance(
                    source, llm_meta.get("model")
                )

            # Where the numbers are is a separate question from what the
            # header says, and it has to be answered for every file — a
            # deterministic vendor parser reads metadata, not the data body.
            layout, layout_source = asyncio.run(
                await_with_lease_heartbeats(
                    resolve_layout(
                        raw_bytes,
                        db,
                        filename=raw_file.original_filename,
                        credential=credential,
                    ),
                    on_heartbeat=lambda: _renew_lease(db, job.id, active_lease_token),
                )
            )
            preview = build_preview(raw_bytes)

            flags = run_sanity_check(metadata, metadata.modality, db)
            flags.update(_quality_flags_for_arrays(raw_bytes, layout))
            now = datetime.now(UTC)

            if layout is None:
                # Not a failure: the header parsed, the bytes are intact, and
                # the owner can tell us the shape. Parking here rather than
                # retrying avoids burning attempts on a question only a human
                # can answer.
                _park_for_user_input(
                    db,
                    job,
                    raw_file,
                    active_lease_token,
                    metadata=metadata,
                    flags=flags,
                    header_hash=header_hash,
                    parser=(parser_used, parser_version, parser_confidence),
                    preview=preview,
                )
                log_event(
                    logger,
                    "ingestion_job.needs_input",
                    ingestion_job_id=str(job.id),
                    raw_file_id=str(raw_file.id),
                    reason="file layout unresolved",
                )
                return
            succeeded = (
                db.query(IngestionJob)
                .filter(
                    IngestionJob.id == job.id,
                    IngestionJob.status == IngestionStatus.running,
                    IngestionJob.lease_token == active_lease_token,
                )
                .update(
                    {
                        IngestionJob.header_hash: header_hash,
                        IngestionJob.parser_used: parser_used,
                        IngestionJob.parser_version: parser_version,
                        IngestionJob.parser_confidence: parser_confidence,
                        IngestionJob.canonicalization_version: RAMAN_CANONICALIZATION_VERSION,
                        IngestionJob.extracted_metadata_raw: metadata.model_dump(mode="json"),
                        IngestionJob.sanity_check_flags: flags,
                        IngestionJob.file_layout: layout.model_dump(mode="json"),
                        IngestionJob.structure_preview: preview.model_dump(mode="json"),
                        IngestionJob.layout_source: layout_source,
                        IngestionJob.status: IngestionStatus.succeeded,
                        IngestionJob.finished_at: now,
                        IngestionJob.lease_token: None,
                        IngestionJob.lease_expires_at: None,
                        IngestionJob.last_heartbeat_at: now,
                    },
                    synchronize_session=False,
                )
            )
            if succeeded != 1:
                db.rollback()
                return
            db.query(RawFile).filter(RawFile.id == raw_file.id).update(
                {
                    RawFile.vendor_format: parser_used,
                    RawFile.upload_status: UploadStatus.parsed,
                    RawFile.checksum_verified_at: now,
                },
                synchronize_session=False,
            )
            db.commit()

            log_event(
                logger,
                "ingestion_job.succeeded",
                ingestion_job_id=str(job.id),
                raw_file_id=str(raw_file.id),
                parser_used=parser_used,
                layout_source=layout_source,
                trace_count=len(layout.traces),
            )
        except Exception as exc:  # noqa: BLE001 - any failure here must land as a failed job, not crash the background task
            db.rollback()
            _retry_or_fail(db, job, raw_file, active_lease_token, exc)

            log_event(
                logger,
                "ingestion_job.failed",
                ingestion_job_id=str(job.id),
                raw_file_id=str(raw_file.id),
                error=str(exc),
            )
    finally:
        db.close()
