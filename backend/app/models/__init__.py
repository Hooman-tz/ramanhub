"""Aggregator module — import every model here so Base.metadata (and
therefore Alembic autogenerate, and `Base.metadata.create_all()`) sees all
tables regardless of which module the caller imports directly.
"""
from app.models.analysis import AnalysisDataset, AnalysisDatasetSpectrum, AnalysisRun
from app.models.enums import (
    FieldDataType,
    IngestionStatus,
    Modality,
    ParseSource,
    SpectrumState,
    UploadStatus,
)
from app.models.field_registry import LedgerStepDefinition, MetadataFieldDefinition
from app.models.ingestion_job import IngestionJob
from app.models.license import License
from app.models.processed_cache import ProcessedCache
from app.models.processing_ledger import ProcessingLedger
from app.models.processing_routine import ProcessingRoutine
from app.models.publication import Publication, PublicationSnapshot
from app.models.raw_file import RawFile
from app.models.similarity import SimilarityFeature
from app.models.social import (
    Comment,
    CommunityPost,
    CommunityPostSpectrum,
    Notification,
    NotificationPreference,
    PostReaction,
    Report,
    Vote,
)
from app.models.spectrum import Spectrum
from app.models.user import User
from app.models.vendor_parse_cache import VendorParseCache

__all__ = [
    "AnalysisDataset",
    "AnalysisDatasetSpectrum",
    "AnalysisRun",
    "Comment",
    "CommunityPost",
    "CommunityPostSpectrum",
    "FieldDataType",
    "IngestionJob",
    "IngestionStatus",
    "LedgerStepDefinition",
    "License",
    "MetadataFieldDefinition",
    "Modality",
    "Notification",
    "NotificationPreference",
    "ParseSource",
    "PostReaction",
    "ProcessedCache",
    "ProcessingLedger",
    "ProcessingRoutine",
    "Publication",
    "PublicationSnapshot",
    "RawFile",
    "Report",
    "SimilarityFeature",
    "Spectrum",
    "SpectrumState",
    "UploadStatus",
    "User",
    "VendorParseCache",
    "Vote",
]
