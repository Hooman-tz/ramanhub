"""Reassign a guest session's work to a real account on sign-in.

Extracted from `routers/auth.py` so every sign-in path (Google, GitHub,
ORCID) can call the exact same logic without importing a router.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.processing_ledger import ProcessingLedger
from app.models.processing_routine import ProcessingRoutine
from app.models.raw_file import RawFile
from app.models.spectrum import Spectrum
from app.models.user import User


def migrate_guest_data(guest: User, target: User, db: Session) -> int:
    """Reassign everything a guest session created to `target`, so "sign in
    to keep your work" is literal. Returns the number of rows moved. The
    guest row itself is deactivated (not deleted) so its id stays valid in
    any logs/history. Commit is left to the caller."""
    moved = 0
    for model, column in (
        (RawFile, RawFile.owner_id),
        (Spectrum, Spectrum.owner_id),
        (ProcessingRoutine, ProcessingRoutine.owner_id),
        (ProcessingLedger, ProcessingLedger.created_by),
    ):
        moved += (
            db.query(model)
            .filter(column == guest.id)
            .update({column: target.id}, synchronize_session=False)
        )
    guest.is_active = False
    db.add(guest)
    return moved
