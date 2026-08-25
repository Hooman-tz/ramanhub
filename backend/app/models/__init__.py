"""Aggregator module — import every model here so Base.metadata (and
therefore Alembic autogenerate, and `Base.metadata.create_all()`) sees all
tables regardless of which module the caller imports directly.
"""
from app.models.accession import (
    FINDING_ACCESSION_SEQ,
    SPECTRUM_ACCESSION_SEQ,
    next_finding_accession,
    next_spectrum_accession,
)
from app.models.curation import MAX_PINS, Collection, CollectionSpectrum, Pin
from app.models.enums import (
    FieldDataType,
    FindingEntryKind,
    FindingState,
    IngestionStatus,
    Modality,
    ParseSource,
    SpectrumState,
    UploadStatus,
)
from app.models.field_registry import LedgerStepDefinition, MetadataFieldDefinition
from app.models.finding import Finding, FindingEntry, FindingSpectrum
from app.models.graph import Follow, HandleHistory
from app.models.ingestion_job import IngestionJob
from app.models.license import License
from app.models.processed_cache import ProcessedCache
from app.models.processing_ledger import ProcessingLedger
from app.models.processing_routine import ProcessingRoutine
from app.models.raw_file import RawFile
from app.models.social import Comment, Share, Vote
from app.models.spectrum import Spectrum
from app.models.user import User
from app.models.vendor_parse_cache import VendorParseCache

__all__ = [
    "FINDING_ACCESSION_SEQ",
    "MAX_PINS",
    "SPECTRUM_ACCESSION_SEQ",
    "Collection",
    "CollectionSpectrum",
    "Comment",
    "FieldDataType",
    "Finding",
    "FindingEntry",
    "FindingEntryKind",
    "FindingSpectrum",
    "FindingState",
    "Follow",
    "HandleHistory",
    "IngestionJob",
    "IngestionStatus",
    "LedgerStepDefinition",
    "License",
    "MetadataFieldDefinition",
    "Modality",
    "ParseSource",
    "Pin",
    "ProcessedCache",
    "ProcessingLedger",
    "ProcessingRoutine",
    "RawFile",
    "Share",
    "Spectrum",
    "SpectrumState",
    "UploadStatus",
    "User",
    "VendorParseCache",
    "Vote",
    "next_finding_accession",
    "next_spectrum_accession",
]
