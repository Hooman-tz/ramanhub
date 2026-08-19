"""Current-user profile endpoints. Mounted at prefix `/users`."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.auth import UserOut, UserUpdate

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=UserOut)
def get_me(current_user: User = Depends(get_current_user)) -> User:
    return current_user


@router.patch("/me", response_model=UserOut)
def patch_me(
    payload: UserUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> User:
    if payload.display_name is not None:
        current_user.display_name = payload.display_name
    if payload.orcid_id is not None:
        current_user.orcid_id = payload.orcid_id

    db.add(current_user)
    db.commit()
    db.refresh(current_user)
    return current_user
