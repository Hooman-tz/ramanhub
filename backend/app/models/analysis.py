"""Durable, reproducible multi-spectrum analysis artifacts and runs."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import DatasetState, Modality, dataset_state_enum, modality_enum


class AnalysisDataset(Base):
    """A named, owner-scoped selection of spectra used as an analysis input."""

    __tablename__ = "analysis_datasets"
    __table_args__ = (UniqueConstraint("owner_id", "name", name="uq_analysis_dataset_owner_name"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    owner_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    modality: Mapped[Modality] = mapped_column(modality_enum, nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Owner-chosen presentation, not semantics: a colour and a symbol so the
    # Office and the Lab can tell one project from another at a glance. Plain
    # varchar rather than an enum because the palette will grow and extending
    # a Postgres enum costs a migration each time; the allowed values are
    # enforced in Pydantic (`ProjectColor` / `ProjectIcon` in
    # `app.routers.analysis`), and readers fall back to the first slot on an
    # unknown value.
    color: Mapped[str] = mapped_column(String(16), nullable=False, default="teal", server_default=text("'teal'"))
    icon: Mapped[str] = mapped_column(String(24), nullable=False, default="folder", server_default=text("'folder'"))

    # Publishing. A dataset starts as a private project folder and only becomes
    # citable when its owner publishes it; the accession is minted at that
    # moment, not at create time, so abandoned drafts don't burn public
    # identifiers. See `app.models.accession` for why gaps are fine and reuse
    # is not.
    accession: Mapped[str | None] = mapped_column(String, nullable=True, unique=True, index=True)
    state: Mapped[DatasetState] = mapped_column(
        dataset_state_enum, nullable=False, default=DatasetState.draft, server_default=DatasetState.draft.value
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    license_id: Mapped[str | None] = mapped_column(String, ForeignKey("licenses.id"), nullable=True)
    doi: Mapped[str | None] = mapped_column(String, nullable=True)

    # Dataset-level lineage, the container equivalent of
    # `Spectrum.parent_spectrum_id`. Set by the dataset fork endpoint so a
    # reader can trace a working copy back to the published original.
    parent_dataset_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("analysis_datasets.id", ondelete="SET NULL"), nullable=True, index=True
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class AnalysisDatasetSpectrum(Base):
    """Ordered dataset membership; duplicates are prevented at the database."""

    __tablename__ = "analysis_dataset_spectra"
    __table_args__ = (UniqueConstraint("dataset_id", "spectrum_id", name="uq_analysis_dataset_spectrum"),)

    dataset_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("analysis_datasets.id", ondelete="CASCADE"), primary_key=True
    )
    spectrum_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("spectra.id", ondelete="CASCADE"), primary_key=True
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)


class AnalysisRun(Base):
    """A signed local/cloud-compatible analysis job and its immutable input snapshot."""

    __tablename__ = "analysis_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    dataset_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("analysis_datasets.id"), nullable=False, index=True)
    owner_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    analysis_type: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", server_default=text("'pending'"), index=True)
    execution_backend: Mapped[str] = mapped_column(String(20), nullable=False, default="local", server_default=text("'local'"))
    parameters: Mapped[dict] = mapped_column(JSONB, nullable=False)
    input_manifest: Mapped[list] = mapped_column(JSONB, nullable=False)
    software_versions: Mapped[dict] = mapped_column(JSONB, nullable=False)
    quality_checks: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default=text("'{}'"))
    output: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    citation: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    output_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    job_signature: Mapped[str] = mapped_column(String(128), nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3, server_default=text("3"))
    cancel_requested: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)