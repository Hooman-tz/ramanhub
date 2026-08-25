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
import re
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

# A line consisting only of numbers and separators — i.e. a spectrum data
# row, not header metadata. Covers "200.00<tab>161.082", comma/semicolon
# separated columns, scientific notation, and signed values.
_DATA_ROW_RE = re.compile(
    r"^\s*[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?"
    r"(?:[\s,;]+[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)*\s*$"
)

# How many consecutive data rows must be seen before the header is declared
# over. Not 1: a legitimate header line can be a bare number (Horiba writes
# "#Grating:\t1800", but other vendors emit a lone value on its own line),
# and cutting there would silently truncate the header.
_CONSECUTIVE_DATA_ROWS = 3

# Backstop for formats where no data rows are ever recognized — e.g. a binary
# header decoded to mojibake with no line structure at all.
_MAX_HEADER_LINES = 200

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


def _looks_like_data_row(line: str) -> bool:
    return bool(line.strip()) and _DATA_ROW_RE.match(line) is not None


def _extract_header_text(raw_bytes: bytes) -> str:
    """Best-effort header text: decode a leading chunk of the raw bytes and
    stop at the point the spectrum data begins.

    Works directly for text-based vendor formats; for binary formats this is
    a lossy approximation used only for hashing/logging, not for parsing —
    `parse()` on binary formats works from the raw bytes directly.

    **Why it stops at the data.** This used to return the whole 64 kB sniff
    window. For a text spectrum that is the entire file, and the header is a
    rounding error within it: `sample-data/horiba_acetaminophen_785nm.txt` is
    22 kB of which the header is 9 lines / 182 bytes. Sending all of it cost
    ~5,700 tokens per parse where ~45 suffice, and — worse than the money —
    burying nine useful lines under fifteen hundred rows of numbers is
    exactly the needle-in-a-haystack setup that makes a small model extract
    badly.

    It also repairs the vendor-parse cache. `compute_header_hash` runs over
    whatever this returns, so while that included intensity values, every
    spectrum hashed differently and `VendorParseCache` — whose entire purpose
    is "work out this vendor's header template once" — missed on every single
    upload. Hashing the header alone lets repeat uploads from one instrument
    actually share an entry.

    Returns "" for a file with no header at all (a bare two-column CSV).
    That is deliberate: there is no metadata to extract, and a stable empty
    hash lets all such files share one cache entry instead of each paying for
    a model call to be told there is nothing there.
    """
    chunk = raw_bytes[:HEADER_SNIFF_BYTES]
    text = chunk.decode("utf-8", errors="ignore")
    lines = text.splitlines()

    cutoff = min(len(lines), _MAX_HEADER_LINES)
    run = 0
    for index, line in enumerate(lines[:_MAX_HEADER_LINES]):
        if _looks_like_data_row(line):
            run += 1
            if run >= _CONSECUTIVE_DATA_ROWS:
                cutoff = index - run + 1
                break
        else:
            run = 0

    header = "\n".join(lines[:cutoff])
    return header[: settings.LLM_HEADER_MAX_CHARS]


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
