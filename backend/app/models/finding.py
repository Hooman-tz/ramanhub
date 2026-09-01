"""Findings: the shareable scientific artifact, and the forum layer.

A single spectrum was previously the only thing anyone could publish or
discuss. That leaves no home for the thing scientists actually want to
share — "here is my result, here is the figure, here is the ML run, here is
the paper it became" — and no home for a multi-spectrum comparison or a PCA
plot, neither of which belongs to any one spectrum.

A Finding is a thread:

  Finding                 title, abstract, license, DOI, accession
   |- FindingEntry        an ordered post: note / figure / analysis
   |- FindingEntry        appended later as the work progresses
   `- FindingSpectrum     the spectra the thread is about

The append-only entry list is the "step by step" mechanism. A follow-up
analysis is a NEW entry, not an edit to an existing one, so a reader who saw
the thread last week can see what was added rather than finding the argument
silently rewritten.

Entries store analysis PARAMETERS in `config` — which spectra, which
prominence threshold, how many components — never a rendered image. The
figure is recomputed from live data on every view, so it stays honest if the
underlying processing changes, and a reader can re-run it themselves. That
is the same reproducibility bet the processing ledger makes.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
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
from app.models.enums import (
    FindingEntryKind,
    FindingState,
    finding_entry_kind_enum,
    finding_state_enum,
)


class Finding(Base):
    """One thread: a write-up tying spectra, figures and a publication
    together."""

    __tablename__ = "findings"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    accession: Mapped[str | None] = mapped_column(String, unique=True, nullable=True, index=True)
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String, nullable=False)
    abstract_md: Mapped[str | None] = mapped_column(Text, nullable=True)
    state: Mapped[FindingState] = mapped_column(
        finding_state_enum,
        default=FindingState.draft,
        server_default=FindingState.draft.value,
        index=True,
    )
    license_id: Mapped[str | None] = mapped_column(String, ForeignKey("licenses.id"), nullable=True)
    # The linked publication. `doi` drives the DOI-verified trust tier the
    # same way it does for spectra; `publication_metadata` caches the
    # Crossref lookup (title, authors, journal, year) so rendering a feed
    # card doesn't make an outbound HTTP call per item.
    doi: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    publication_metadata: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # An optional link to the code/analysis repository behind the write-up
    # (a GitHub repo, a notebook archive). Free-text URL, not verified: it is
    # a provenance breadcrumb for readers, the same role `doi` plays for the
    # paper. Kept next to `doi` because they are the two "where does this
    # lead" fields a reader looks for.
    repo_url: Mapped[str | None] = mapped_column(String, nullable=True)
    # Free-text topic tags. JSONB rather than a join table: tags here are a
    # browsing aid, not a controlled vocabulary, and there is no evidence
    # yet of needing to query or rename them at scale (Scaling Posture:
    # don't build ahead of evidence).
    tags: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class FindingEntry(Base):
    """One post within a Finding, ordered by `position`."""

    __tablename__ = "finding_entries"
    __table_args__ = (
        # Ordering is dense and per-thread; the index serves both the
        # "render this thread in order" read and the reorder write.
        Index("ix_finding_entries_finding_position", "finding_id", "position"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    finding_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("findings.id", ondelete="CASCADE"), nullable=False
    )
    # Recorded per entry, not inherited from the Finding: a thread is where
    # collaborators add their own results, so entries can outlive or differ
    # from the thread owner.
    author_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    kind: Mapped[FindingEntryKind] = mapped_column(finding_entry_kind_enum, nullable=False)
    body_md: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Analysis parameters (spectrum ids, prominence, n_components, ...) —
    # never a rendered image. See the module docstring.
    config: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class FindingSpectrum(Base):
    """Ordered membership: which spectra a Finding is about.

    Kept as an explicit table rather than derived from entry configs so
    "download everything in this Finding" and "which Findings cite this
    spectrum" are both single queries.
    """

    __tablename__ = "finding_spectra"
    __table_args__ = (UniqueConstraint("finding_id", "spectrum_id", name="uq_finding_spectrum"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    finding_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("findings.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    spectrum_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("spectra.id"), nullable=False, index=True
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Overrides the spectrum's own title in this Finding's figures ("Control",
    # "Treated 24h") without renaming the underlying record, which belongs to
    # its owner and may be cited elsewhere.
    label: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# Re-exported for the migration and for tests that assert the constraint
# exists — the rule that a vote or comment targets exactly one thing.
SINGLE_TARGET_CHECK = CheckConstraint(
    "(spectrum_id IS NOT NULL)::int + (finding_id IS NOT NULL)::int = 1",
    name="ck_exactly_one_target",
)
