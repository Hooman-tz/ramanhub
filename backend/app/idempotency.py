"""HTTP request idempotency — the fix for duplicate drafts / posts / votes.

A slow backend plus a retrying proxy (Vercel rewrite) or an HTTP/2 stream
reset can replay a `POST` transparently. The client
(`packages/api-client`) generates one `Idempotency-Key` per logical request,
so a transparent replay carries the *same* key. Mutating handlers call
`check()` first; if the key was already handled they return the stored
response verbatim instead of writing a second row. `record()` persists the
success payload after the handler builds it.

No header present -> `check()` returns None and `record()` is a no-op, so a
caller that doesn't send the header behaves exactly as before.

Scope: import this from routers; never add feed/social logic to
`app/processing/` or `app/ingestion/`.
"""
from __future__ import annotations

import uuid
from typing import Any

from fastapi import Request
from fastapi.encoders import jsonable_encoder
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.idempotency import IdempotencyRecord

HEADER_NAME = "Idempotency-Key"


def _key(request: Request) -> str | None:
    raw = request.headers.get(HEADER_NAME)
    if raw is None:
        return None
    raw = raw.strip()
    return raw or None


def check(db: Session, user_id: uuid.UUID, request: Request) -> dict | None:
    """Return `{"status": int, "body": <json>}` if this `(user_id,
    Idempotency-Key)` was already recorded, else None. None when no header
    is sent."""
    key = _key(request)
    if key is None:
        return None
    record_row = db.execute(
        select(IdempotencyRecord).where(
            IdempotencyRecord.user_id == user_id,
            IdempotencyRecord.idem_key == key,
        )
    ).scalar_one_or_none()
    if record_row is None:
        return None
    return {"status": record_row.response_status, "body": record_row.response_body}


def record(
    db: Session,
    user_id: uuid.UUID,
    request: Request,
    status: int,
    body: Any,
) -> None:
    """Persist a handler's success response for later replay. No-op when no
    `Idempotency-Key` header is present.

    Commits its own row. A concurrent first-request that already inserted the
    same `(user_id, idem_key)` makes this raise `IntegrityError` on commit —
    caught and treated as "already recorded", since the other request's body
    is an equally valid answer.
    """
    key = _key(request)
    if key is None:
        return
    db.add(
        IdempotencyRecord(
            user_id=user_id,
            idem_key=key,
            method=request.method,
            path=request.url.path,
            response_status=status,
            response_body=jsonable_encoder(body),
        )
    )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
