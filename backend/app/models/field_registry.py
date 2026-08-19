from sqlalchemy import Boolean, Integer, Numeric, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import FieldDataType, Modality, field_data_type_enum, modality_enum


class MetadataFieldDefinition(Base):
    """Registry of expected/allowed metadata fields per modality, used to
    validate and drive UI for confirmed spectrum metadata."""

    __tablename__ = "metadata_field_definitions"
    __table_args__ = (UniqueConstraint("modality", "field_key", name="uq_metadata_field_modality_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    modality: Mapped[Modality] = mapped_column(modality_enum)
    field_key: Mapped[str] = mapped_column(String)
    data_type: Mapped[FieldDataType] = mapped_column(field_data_type_enum)
    required: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    min_value: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    max_value: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    allowed_values: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    unit: Mapped[str | None] = mapped_column(String, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)


class LedgerStepDefinition(Base):
    """Registry of known processing-ledger step types per modality, each
    version-stamped by algorithm_version so ledgers stay replayable as the
    codebase evolves."""

    __tablename__ = "ledger_step_definitions"
    __table_args__ = (
        UniqueConstraint(
            "modality", "step_type", "algorithm_version", name="uq_ledger_step_modality_type_version"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    modality: Mapped[Modality] = mapped_column(modality_enum)
    step_type: Mapped[str] = mapped_column(String)
    algorithm_version: Mapped[str] = mapped_column(String)
    param_schema: Mapped[dict] = mapped_column(JSONB)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
