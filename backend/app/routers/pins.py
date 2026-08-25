"""Pinned items — the owner-curated top of a profile.

Mounted with no prefix: `/users/{handle}/pins` (read) and `/pins` (write).

## Why pinning exists

A profile ordered only by recency is a log, and a log is a bad way to judge a
scientist: the work someone wants to be known for is frequently not the thing
they touched most recently. Four slots force a choice — a profile that could
pin twenty items has ranked nothing.

Reads are public (a pin is a public statement about your own work). Writes are
owner-only, and there is no way to pin something you do not own: pinning
someone else's spectrum to your profile would misrepresent authorship.
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.deps import get_current_full_user
from app.db.session import get_db
from app.models.curation import MAX_PINS, Pin
from app.models.finding import Finding
from app.models.handles import normalize_handle
from app.models.spectrum import Spectrum
from app.models.user import User

router = APIRouter(tags=["pins"])


class PinIn(BaseModel):
    kind: str  # "spectrum" | "finding"
    id: UUID


class PinOut(BaseModel):
    kind: str
    id: UUID
    accession: str | None = None
    title: str | None = None
    position: int


def _user_by_handle_or_404(handle: str, db: Session) -> User:
    user = db.scalar(select(User).where(User.handle == normalize_handle(handle)))
    if user is None or not user.is_active or user.is_guest:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    return user


def _pins_for(user_id, db: Session) -> list[PinOut]:
    rows = db.scalars(
        select(Pin).where(Pin.user_id == user_id).order_by(Pin.position, Pin.id)
    ).all()

    out: list[PinOut] = []
    for pin in rows:
        if pin.spectrum_id is not None:
            spectrum = db.get(Spectrum, pin.spectrum_id)
            if spectrum is None:
                continue
            out.append(
                PinOut(
                    kind="spectrum",
                    id=spectrum.id,
                    accession=spectrum.accession,
                    title=spectrum.title,
                    position=pin.position,
                )
            )
        elif pin.finding_id is not None:
            finding = db.get(Finding, pin.finding_id)
            if finding is None:
                continue
            out.append(
                PinOut(
                    kind="finding",
                    id=finding.id,
                    accession=finding.accession,
                    title=finding.title,
                    position=pin.position,
                )
            )
    return out


@router.get("/users/{handle}/pins", response_model=list[PinOut])
def list_pins(handle: str, db: Session = Depends(get_db)) -> list[PinOut]:
    return _pins_for(_user_by_handle_or_404(handle, db).id, db)


@router.post("/pins", response_model=list[PinOut], status_code=status.HTTP_201_CREATED)
def add_pin(
    body: PinIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_full_user),
) -> list[PinOut]:
    if body.kind not in ("spectrum", "finding"):
        raise HTTPException(status_code=422, detail="kind must be 'spectrum' or 'finding'")

    # Ownership, not merely readability. Pinning someone else's work to your
    # own profile would misrepresent who produced it.
    if body.kind == "spectrum":
        target = db.get(Spectrum, body.id)
        owner_id = target.owner_id if target else None
    else:
        target = db.get(Finding, body.id)
        owner_id = target.owner_id if target else None
    if target is None or owner_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    existing = db.scalar(select(func.count()).select_from(Pin).where(Pin.user_id == user.id)) or 0
    if existing >= MAX_PINS:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"You can pin at most {MAX_PINS} items — unpin one first.",
        )

    pin = Pin(user_id=user.id, position=existing)
    if body.kind == "spectrum":
        pin.spectrum_id = body.id
    else:
        pin.finding_id = body.id

    try:
        with db.begin_nested():
            db.add(pin)
            db.flush()
    except IntegrityError:
        # Already pinned. Idempotent rather than an error — the button is a
        # toggle in the UI and a double submit should not 500.
        #
        # Deliberately NOT db.rollback(): exiting the `begin_nested()` block
        # has already unwound the SAVEPOINT, and a full rollback here would
        # discard everything else the session had done, not just this insert.
        # `routers.votes` handles the same conflict the same way.
        return _pins_for(user.id, db)

    db.commit()
    return _pins_for(user.id, db)


@router.delete("/pins/{kind}/{item_id}", response_model=list[PinOut])
def remove_pin(
    kind: str,
    item_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_full_user),
) -> list[PinOut]:
    column = Pin.spectrum_id if kind == "spectrum" else Pin.finding_id
    pin = db.scalar(select(Pin).where(Pin.user_id == user.id, column == item_id))
    if pin is not None:
        db.delete(pin)
        db.commit()
    return _pins_for(user.id, db)
