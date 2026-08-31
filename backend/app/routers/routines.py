"""Reusable ledger-template ("routine") CRUD-lite + apply-to-raw-file.

Mounted with no prefix — `POST /routines`, `GET /routines`,
`POST /raw-files/{raw_file_id}/apply-routine/{routine_id}`.
"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth.deps import get_current_user
from app.db.session import get_db
from app.models.enums import Modality
from app.models.processing_routine import ProcessingRoutine
from app.models.raw_file import RawFile
from app.models.user import User
from app.processing.cache import get_or_compute
from app.routers.ledgers import LedgerCreateResponse, LedgerStepIn, build_and_persist_ledger

router = APIRouter(tags=["routines"])


class RoutineCreate(BaseModel):
    modality: str
    name: str
    description: str | None = None
    # Same shape as LedgerCreateRequest.steps: [{type, params, order}, ...]
    steps_template: list[dict]


class RoutineResponse(BaseModel):
    id: UUID
    owner_id: UUID
    modality: str
    name: str
    description: str | None
    steps_template: list[dict]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


@router.post("/routines", response_model=RoutineResponse, status_code=status.HTTP_201_CREATED)
def create_routine(
    body: RoutineCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> RoutineResponse:
    try:
        modality = Modality(body.modality)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"Unknown modality: {body.modality!r}") from exc

    routine = ProcessingRoutine(
        owner_id=user.id,
        modality=modality,
        name=body.name,
        description=body.description,
        steps_template=body.steps_template,
    )
    db.add(routine)
    db.commit()
    db.refresh(routine)
    return RoutineResponse.model_validate(routine)


@router.get("/routines", response_model=list[RoutineResponse])
def list_routines(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[RoutineResponse]:
    routines = (
        db.query(ProcessingRoutine)
        .filter_by(owner_id=user.id)
        .order_by(ProcessingRoutine.created_at.desc())
        .all()
    )
    return [RoutineResponse.model_validate(routine) for routine in routines]


@router.delete("/routines/{routine_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_routine(
    routine_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    routine = db.get(ProcessingRoutine, routine_id)
    if routine is None or routine.owner_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Routine not found")
    db.delete(routine)
    db.commit()


@router.post(
    "/raw-files/{raw_file_id}/apply-routine/{routine_id}",
    response_model=LedgerCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
def apply_routine(
    raw_file_id: UUID,
    routine_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> LedgerCreateResponse:
    raw_file = db.get(RawFile, raw_file_id)
    if raw_file is None or raw_file.owner_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Raw file not found")

    routine = db.get(ProcessingRoutine, routine_id)
    if routine is None or routine.owner_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Routine not found")

    steps_in = [LedgerStepIn(**step) for step in routine.steps_template]
    ledger_row, ledger_pydantic, reused = build_and_persist_ledger(
        raw_file, steps_in, db, user, derived_from_routine_id=routine.id
    )
    _wavenumbers, intensities = get_or_compute(raw_file.id, ledger_pydantic, db)

    return LedgerCreateResponse(
        ledger=ledger_pydantic,
        ledger_id=ledger_row.id,
        ledger_hash=ledger_row.ledger_hash,
        reused_existing=reused,
        processed={"length": int(intensities.shape[0])},
    )
