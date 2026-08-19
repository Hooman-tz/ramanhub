"""Async orchestration of the ingestion pipeline via FastAPI BackgroundTasks.

No Redis/Celery — per the project's "don't build ahead of evidence"
principle, background tasks are enough for v1. `run_ingestion_job` opens its
own DB session rather than depending on the request-scoped `get_db`
dependency, so it can be called from a plain background task today or,
later, a Celery task with no change.
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from fastapi import BackgroundTasks

from app.config import settings
from app.db.base import SessionLocal
from app.ingestion.header_hash import compute_header_hash
from app.ingestion.llm_fallback import extract_metadata_via_llm
from app.ingestion.parsers.registry import find_parser
from app.ingestion.sanity_check import check as run_sanity_check
from app.logging_config import log_event
from app.models.enums import IngestionStatus, UploadStatus
from app.models.ingestion_job import IngestionJob
from app.models.raw_file import RawFile
from app.storage.s3_client import download_bytes

HEADER_SNIFF_BYTES = 65536

logger = logging.getLogger(__name__)


def enqueue_ingestion_job(background_tasks: BackgroundTasks, raw_file_id: uuid.UUID) -> None:
    """Schedule `run_ingestion_job` to run after the current request returns."""
    background_tasks.add_task(run_ingestion_job, raw_file_id)


def run_with_timeout(func: Callable[..., Any], *args: Any, timeout: float, **kwargs: Any) -> Any:
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
    try:
        return future.result(timeout=timeout)
    except concurrent.futures.TimeoutError as exc:
        raise TimeoutError(f"Parsing timed out after {timeout}s") from exc
    finally:
        executor.shutdown(wait=False)


def _extract_header_text(raw_bytes: bytes) -> str:
    """Best-effort header text: decode a leading chunk of the raw bytes.
    Works directly for text-based vendor formats; for binary formats this is
    a lossy approximation used only for hashing/logging, not for parsing —
    `parse()` on binary formats works from the raw bytes directly.
    """
    chunk = raw_bytes[:HEADER_SNIFF_BYTES]
    return chunk.decode("utf-8", errors="ignore")


def _latest_pending_job(db, raw_file_id: uuid.UUID) -> IngestionJob | None:
    return (
        db.query(IngestionJob)
        .filter(IngestionJob.raw_file_id == raw_file_id)
        .order_by(IngestionJob.created_at.desc())
        .first()
    )


def run_ingestion_job(raw_file_id: uuid.UUID) -> None:
    """Download the raw file, run deterministic parsers (falling back to the
    LLM on a miss), sanity-check the result, and persist it onto the
    IngestionJob + RawFile rows. Opens and closes its own DB session.
    """
    db = SessionLocal()
    try:
        raw_file = db.get(RawFile, raw_file_id)
        job = _latest_pending_job(db, raw_file_id)
        if raw_file is None or job is None:
            return

        job.status = IngestionStatus.running
        job.started_at = datetime.now(UTC)
        raw_file.upload_status = UploadStatus.parsing
        db.add_all([job, raw_file])
        db.commit()

        log_event(
            logger,
            "ingestion_job.started",
            ingestion_job_id=str(job.id),
            raw_file_id=str(raw_file_id),
        )

        try:
            raw_bytes = download_bytes(raw_file.storage_bucket, raw_file.storage_key)
            header_text = _extract_header_text(raw_bytes)
            header_hash = compute_header_hash(header_text)

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
                )
                parser_used = parser.vendor_format
            else:
                metadata, source = asyncio.run(extract_metadata_via_llm(header_text, db))
                parser_used = f"llm:{source}"

            flags = run_sanity_check(metadata, metadata.modality, db)

            job.header_hash = header_hash
            job.parser_used = parser_used
            job.extracted_metadata_raw = metadata.model_dump(mode="json")
            job.sanity_check_flags = flags
            job.status = IngestionStatus.succeeded
            job.finished_at = datetime.now(UTC)

            raw_file.vendor_format = parser_used
            raw_file.upload_status = UploadStatus.parsed
            db.add_all([job, raw_file])
            db.commit()

            log_event(
                logger,
                "ingestion_job.succeeded",
                ingestion_job_id=str(job.id),
                raw_file_id=str(raw_file_id),
                parser_used=parser_used,
            )
        except Exception as exc:  # noqa: BLE001 - any failure here must land as a failed job, not crash the background task
            db.rollback()
            job.status = IngestionStatus.failed
            job.error_message = str(exc)
            job.finished_at = datetime.now(UTC)
            raw_file.upload_status = UploadStatus.failed
            db.add_all([job, raw_file])
            db.commit()

            log_event(
                logger,
                "ingestion_job.failed",
                ingestion_job_id=str(job.id),
                raw_file_id=str(raw_file_id),
                error=str(exc),
            )
    finally:
        db.close()
