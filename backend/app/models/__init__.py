"""Aggregator module — import every model here so Base.metadata (and
therefore Alembic autogenerate, and `Base.metadata.create_all()`) sees all
tables regardless of which module the caller imports directly.
"""
# Imported for its side effect: binds spectrum_accession_seq /
# finding_accession_seq to Base.metadata so create_all (the test harness)
# emits them.
from app.models import accession as accession
from app.models.analysis import AnalysisDataset, AnalysisDatasetSpectrum, AnalysisRun
from app.models.auth_identity import AuthIdentity
from app.models.curation import Pin
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
from app.models.finding import (
    Finding,
    FindingCoAuthor,
    FindingEntry,
    FindingSpectrum,
)
from app.models.finding_image import FindingImage
from app.models.graph import Follow, HandleHistory
from app.models.idempotency import IdempotencyRecord
from app.models.ingestion_job import IngestionJob
from app.models.journal import Journal
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
    Share,
    Vote,
)
from app.models.spectrum import Spectrum
from app.models.user import User
from app.models.user_llm_credential import UserLLMCredential
from app.models.vendor_parse_cache import VendorParseCache

__all__ = [
    "AnalysisDataset",
    "AnalysisDatasetSpectrum",
    "AnalysisRun",
    "AuthIdentity",
    "Comment",
    "CommunityPost",
    "CommunityPostSpectrum",
    "FieldDataType",
    "Finding",
    "FindingCoAuthor",
    "FindingEntry",
    "FindingEntryKind",
    "FindingImage",
    "FindingSpectrum",
    "FindingState",
    "Follow",
    "HandleHistory",
    "IdempotencyRecord",
    "IngestionJob",
    "IngestionStatus",
    "Journal",
    "LedgerStepDefinition",
    "License",
    "MetadataFieldDefinition",
    "Modality",
    "Notification",
    "NotificationPreference",
    "ParseSource",
    "Pin",
    "PostReaction",
    "ProcessedCache",
    "ProcessingLedger",
    "ProcessingRoutine",
    "Publication",
    "PublicationSnapshot",
    "RawFile",
    "Report",
    "Share",
    "SimilarityFeature",
    "Spectrum",
    "SpectrumState",
    "UploadStatus",
    "User",
    "UserLLMCredential",
    "VendorParseCache",
    "Vote",
]
