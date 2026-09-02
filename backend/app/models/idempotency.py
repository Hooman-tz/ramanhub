"""Request idempotency records.

The #1 production duplicate-writes bug came from an HTTP-level retry (a proxy
or an HTTP/2 stream reset) transparently replaying a POST while the backend
was slow. The replay carries the *same* client-generated `Idempotency-Key`
header, so a row here — keyed `(user_id, idem_key)` — lets the second run of
a mutating handler short-circuit and return the first run's stored response
instead of creating a second draft / post / vote.

Deliberately generic: `method`, `path`, `response_status` and
`response_body` (the already-serialized success payload) are enough to
replay any create/toggle handler's answer without re-touching the database.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class IdempotencyRecord(Base):
    """One recorded response for a `(user_id, Idempotency-Key)` pair."""

    __tablename__ = "idempotency_records"
    __table_args__ = (
        # The whole mechanism: the second arrival of the same key for the same
        # user must collide here rather than run the handler again.
        UniqueConstraint("user_id", "idem_key", name="uq_idempotency_user_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    idem_key: Mapped[str] = mapped_column(String, nullable=False)
    method: Mapped[str] = mapped_column(String, nullable=False)
    path: Mapped[str] = mapped_column(String, nullable=False)
    response_status: Mapped[int] = mapped_column(Integer, nullable=False)
    response_body: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
