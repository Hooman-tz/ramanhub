"""Create (or dedupe-and-reuse) a processing ledger for a raw file, and
synchronously materialize its processed output via the cache.

Mounted with no prefix — `POST /raw-files/{raw_file_id}/ledgers`.
"""
from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth.deps import get_current_user
from app.db.session import get_db
from app.models.processing_ledger import ProcessingLedger
from app.models.raw_file import RawFile
from app.models.user import User
from app.processing.algorithms.registry import get_algorithm
from app.processing.cache import get_or_compute
from app.processing.ledger import LedgerValidationError, compute_ledger_hash, validate_ledger_steps
from app.schemas.ledger import Ledger, LedgerStep

router = APIRouter(tags=["ledgers"])


class LedgerStepIn(BaseModel):
    """Client-supplied step shape — no `version`: the server resolves the
    step type to whichever algorithm version this codebase currently
    implements (see `_default_version_for`), since the client shouldn't need
    to know internal version numbers."""

    type: str
    params: dict = {}
    order: int


class LedgerCreateRequest(BaseModel):
    steps: list[LedgerStepIn]


class LedgerCreateResponse(BaseModel):
    ledger: Ledger
    ledger_id: UUID
    ledger_hash: str
    reused_existing: bool
    # Summary of the processed array rather than the full payload — the
    # array itself is available via the processed-cache storage object
    # (`ProcessedCache.storage_bucket`/`storage_key`); returning just the
    # length here keeps this response small and avoids re-serializing
    # potentially large arrays over the API on every ledger write.
    processed: dict


def _default_version_for(step_type: str) -> str:
    _, version = get_algorithm(step_type)
    return version


def build_and_persist_ledger(
    raw_file: RawFile,
    steps_in: list[LedgerStepIn],
    db: Session,
    user: User,
    derived_from_routine_id: UUID | None = None,
) -> tuple[ProcessingLedger, Ledger, bool]:
    """Build `LedgerStep`s (server-assigned `step_id`/`applied_at`), validate
    them, compute the content hash, and either reuse an existing
    `ProcessingLedger` row with that hash or create a new one.

    Returns `(ledger_row, ledger_pydantic, reused_existing)`.
    """
    now = datetime.now(UTC)
    steps: list[LedgerStep] = []
    for step_in in steps_in:
        try:
            version = _default_version_for(step_in.type)
        except KeyError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        steps.append(
            LedgerStep(
                step_id=uuid4(),
                type=step_in.type,
                version=version,
                params=step_in.params,
                order=step_in.order,
                applied_at=now,
            )
        )

    try:
        validate_ledger_steps(steps, raw_file.modality, db)
    except LedgerValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    ledger_hash = compute_ledger_hash(raw_file.id, 1, steps)
    existing = db.query(ProcessingLedger).filter_by(ledger_hash=ledger_hash).one_or_none()
    if existing is not None:
        ledger_pydantic = Ledger(
            schema_version=existing.schema_version,
            raw_file_id=existing.raw_file_id,
            steps=[LedgerStep.model_validate(step) for step in existing.steps],
        )
        return existing, ledger_pydantic, True

    ledger_row = ProcessingLedger(
        raw_file_id=raw_file.id,
        modality=raw_file.modality,
        schema_version=1,
        steps=[step.model_dump(mode="json") for step in steps],
        ledger_hash=ledger_hash,
        derived_from_routine_id=derived_from_routine_id,
        created_by=user.id,
    )
    db.add(ledger_row)
    db.commit()
    db.refresh(ledger_row)

    ledger_pydantic = Ledger(schema_version=1, raw_file_id=raw_file.id, steps=steps)
    return ledger_row, ledger_pydantic, False


@router.post(
    "/raw-files/{raw_file_id}/ledgers",
    response_model=LedgerCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_ledger(
    raw_file_id: UUID,
    body: LedgerCreateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> LedgerCreateResponse:
    raw_file = db.get(RawFile, raw_file_id)
    if raw_file is None or raw_file.owner_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Raw file not found")

    ledger_row, ledger_pydantic, reused = build_and_persist_ledger(raw_file, body.steps, db, user)
    _wavenumbers, intensities = get_or_compute(raw_file.id, ledger_pydantic, db)

    return LedgerCreateResponse(
        ledger=ledger_pydantic,
        ledger_id=ledger_row.id,
        ledger_hash=ledger_row.ledger_hash,
        reused_existing=reused,
        processed={"length": int(intensities.shape[0])},
    )
