"""Shared draft, provenance, and publication-readiness rules.

Routes call these helpers rather than duplicating partial checks. The browser
may render this status, but the server remains the authority that enforces it.
"""
from __future__ import annotations

from typing import Any

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.models.enums import IngestionStatus, UploadStatus
from app.models.ingestion_job import IngestionJob
from app.models.processing_ledger import ProcessingLedger
from app.models.publication import PublicationSnapshot
from app.models.raw_file import RawFile
from app.models.spectrum import Spectrum
from app.schemas.ingestion import ExtractedMetadata

REQUIRED_PUBLIC_RAMAN_FIELDS = (
    "instrument_vendor",
    "laser_wavelength_nm",
    "spectral_range_cm1",
    "sample_description",
)


def ingestion_job_for_raw(raw_file_id, db: Session) -> IngestionJob | None:
    return db.query(IngestionJob).filter(IngestionJob.raw_file_id == raw_file_id).one_or_none()


def publication_for_spectrum(spectrum_id, db: Session) -> PublicationSnapshot | None:
    return (
        db.query(PublicationSnapshot)
        .filter(PublicationSnapshot.spectrum_id == spectrum_id)
        .one_or_none()
    )


def _required_metadata_errors(metadata: dict | None) -> list[str]:
    if metadata is None:
        return ["Metadata has not been confirmed."]
    try:
        parsed = ExtractedMetadata.model_validate(metadata)
    except ValidationError:
        return ["Confirmed metadata does not satisfy the Raman profile."]
    missing = [field for field in REQUIRED_PUBLIC_RAMAN_FIELDS if getattr(parsed, field) is None]
    return [f"Required Raman metadata is missing: {field}." for field in missing]


def publication_readiness(spectrum: Spectrum, db: Session) -> dict[str, Any]:
    """Return a user-visible, server-derived preflight for draft publication."""
    blockers: list[str] = []
    warnings: list[str] = []
    raw_file = db.get(RawFile, spectrum.raw_file_id)
    job = ingestion_job_for_raw(spectrum.raw_file_id, db)

    if raw_file is None:
        blockers.append("The immutable raw-file record is missing.")
    else:
        if raw_file.upload_status != UploadStatus.parsed:
            blockers.append("The raw file has not completed parsing.")
        if raw_file.checksum_verified_at is None or not raw_file.storage_version:
            blockers.append("The immutable raw-file checksum has not been verified.")

    if job is None or job.status != IngestionStatus.succeeded:
        blockers.append("A completed ingestion record is required.")
        flags: dict[str, str] = {}
    else:
        flags = job.sanity_check_flags or {}
        if job.extracted_metadata_confirmed is None:
            blockers.append("Review and confirm the extracted metadata first.")
        if job.canonicalization_version is None:
            blockers.append("The Raman canonicalization record is missing.")
        for field, reason in flags.items():
            message = f"{field}: {reason}"
            if field == "array" or "required field is missing" in reason:
                blockers.append(message)
            else:
                warnings.append(message)

    blockers.extend(_required_metadata_errors(spectrum.confirmed_metadata))

    publication = publication_for_spectrum(spectrum.id, db)
    if spectrum.doi and (
        publication is None
        or publication.verification_status != "verified"
        or publication.doi != spectrum.doi
    ):
        blockers.append("The attached DOI does not have a verified resolver snapshot.")

    ledger = (
        db.get(ProcessingLedger, spectrum.current_ledger_id)
        if spectrum.current_ledger_id is not None
        else None
    )
    if ledger is None:
        warnings.append("No processing ledger is attached; this record publishes its canonical raw spectrum.")
    elif ledger.processing_environment is None:
        blockers.append("The processing ledger is missing environment provenance.")

    return {
        "ready": not blockers,
        "blockers": blockers,
        "warnings": warnings,
        "metadata_state": "confirmed" if job and job.extracted_metadata_confirmed else "needs_review",
        "qc_state": "blocked" if blockers else ("review" if warnings else "passed"),
        "doi_verification": (
            publication.verification_status if publication is not None else "not_attached"
        ),
    }


def spectrum_provenance(spectrum: Spectrum, db: Session) -> dict[str, Any]:
    """Serialize reproducibility evidence without exposing storage locations."""
    raw_file = db.get(RawFile, spectrum.raw_file_id)
    job = ingestion_job_for_raw(spectrum.raw_file_id, db)
    ledger = (
        db.get(ProcessingLedger, spectrum.current_ledger_id)
        if spectrum.current_ledger_id is not None
        else None
    )
    publication = publication_for_spectrum(spectrum.id, db)
    return {
        "raw_file": (
            {
                "id": str(raw_file.id),
                "checksum_sha256": raw_file.content_hash,
                "object_version": raw_file.storage_version,
                "checksum_verified_at": raw_file.checksum_verified_at,
            }
            if raw_file
            else None
        ),
        "ingestion": (
            {
                "parser": job.parser_used,
                "parser_version": job.parser_version,
                "parser_confidence": job.parser_confidence,
                "header_hash": job.header_hash,
                "canonicalization_version": job.canonicalization_version,
                "confirmed_at": job.confirmed_at,
            }
            if job
            else None
        ),
        "processing": (
            {
                "ledger_id": str(ledger.id),
                "ledger_hash": ledger.ledger_hash,
                "schema_version": ledger.schema_version,
                "environment": ledger.processing_environment,
            }
            if ledger
            else None
        ),
        "lineage": {"parent_spectrum_id": str(spectrum.parent_spectrum_id) if spectrum.parent_spectrum_id else None},
        "publication": (
            {
                "doi": publication.doi,
                "provider": publication.provider,
                "verification_status": publication.verification_status,
                "verified_at": publication.verified_at,
                "snapshot": publication.snapshot,
            }
            if publication
            else None
        ),
    }