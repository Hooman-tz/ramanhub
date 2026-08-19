"""Public license listing. Mounted at prefix `/licenses`."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.license import License
from app.schemas.auth import LicenseOut

router = APIRouter(prefix="/licenses", tags=["licenses"])


@router.get("", response_model=list[LicenseOut])
def list_licenses(db: Session = Depends(get_db)) -> list[License]:
    return db.query(License).order_by(License.id).all()
