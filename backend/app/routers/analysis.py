"""Owner-scoped multi-spectrum datasets and reproducible analysis runs."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.analysis.engine import (
    ANALYSIS_CONTRACT_VERSION,
    MAX_ANALYSIS_SPECTRA,
    build_input_manifest,
    sign_run,
    software_versions,
)
from app.auth.deps import get_current_user
from app.db.session import get_db
from app.models.analysis import AnalysisDataset, AnalysisDatasetSpectrum, AnalysisRun
from app.models.spectrum import Spectrum
from app.models.user import User
from app.processing.state_machine import require_owner_or_public

router = APIRouter(prefix="/analysis", tags=["analysis"])


class DatasetCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=2000)
    spectrum_ids: list[UUID] = Field(min_length=2, max_length=MAX_ANALYSIS_SPECTRA)


class DatasetSpectrumOut(BaseModel):
    id: UUID
    title: str | None
    modality: str
    state: str


class DatasetOut(BaseModel):
    id: UUID
    name: str
    description: str | None
    modality: str
    spectra: list[DatasetSpectrumOut]
    created_at: datetime | None
    updated_at: datetime | None


class RunCreate(BaseModel):
    analysis_type: Literal["pca", "pca_kmeans"] = "pca"
    components: int = Field(default=2, ge=1, le=10)
    grid_points: int = Field(default=128, ge=16, le=512)
    clusters: int | None = Field(default=None, ge=2, le=8)
    execution_backend: Literal["local", "hosted"] = "local"


class RunOut(BaseModel):
    id: UUID
    dataset_id: UUID
    analysis_type: str
    status: str
    execution_backend: str
    parameters: dict
    input_manifest: list
    software_versions: dict
    quality_checks: dict
    output: dict | None
    citation: dict | None
    output_hash: str | None
    attempt_count: int
    max_attempts: int
    cancel_requested: bool
    error_message: str | None
    created_at: datetime | None
    started_at: datetime | None
    finished_at: datetime | None


def _dataset_spectra(dataset: AnalysisDataset, db: Session) -> list[Spectrum]:
    return (
        db.query(Spectrum)
        .join(AnalysisDatasetSpectrum, AnalysisDatasetSpectrum.spectrum_id == Spectrum.id)
        .filter(AnalysisDatasetSpectrum.dataset_id == dataset.id)
        .order_by(AnalysisDatasetSpectrum.position)
        .all()
    )


def _dataset_payload(dataset: AnalysisDataset, db: Session) -> DatasetOut:
    spectra = _dataset_spectra(dataset, db)
    return DatasetOut(
        id=dataset.id,
        name=dataset.name,
        description=dataset.description,
        modality=dataset.modality.value,
        spectra=[
            DatasetSpectrumOut(
                id=spectrum.id,
                title=spectrum.title,
                modality=spectrum.modality.value,
                state=spectrum.state.value,
            )
            for spectrum in spectra
        ],
        created_at=dataset.created_at,
        updated_at=dataset.updated_at,
    )


def _dataset_or_404(dataset_id: UUID, user: User, db: Session) -> AnalysisDataset:
    dataset = db.get(AnalysisDataset, dataset_id)
    if dataset is None or dataset.owner_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Analysis dataset not found")
    return dataset


def _run_or_404(run_id: UUID, user: User, db: Session) -> AnalysisRun:
    run = db.get(AnalysisRun, run_id)
    if run is None or run.owner_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Analysis run not found")
    return run


@router.get("/datasets", response_model=list[DatasetOut])
def list_datasets(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> list[DatasetOut]:
    datasets = (
        db.query(AnalysisDataset)
        .filter(AnalysisDataset.owner_id == user.id)
        .order_by(AnalysisDataset.updated_at.desc())
        .all()
    )
    return [_dataset_payload(dataset, db) for dataset in datasets]


@router.post("/datasets", response_model=DatasetOut, status_code=status.HTTP_201_CREATED)
def create_dataset(
    body: DatasetCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> DatasetOut:
    unique_ids = list(dict.fromkeys(body.spectrum_ids))
    if len(unique_ids) < 2:
        raise HTTPException(status_code=422, detail="Choose at least two distinct spectra.")
    spectra_by_id = {
        spectrum.id: spectrum for spectrum in db.query(Spectrum).filter(Spectrum.id.in_(unique_ids)).all()
    }
    if len(spectra_by_id) != len(unique_ids):
        raise HTTPException(status_code=404, detail="One or more selected spectra were not found.")
    spectra = [spectra_by_id[spectrum_id] for spectrum_id in unique_ids]
    for spectrum in spectra:
        require_owner_or_public(spectrum, user)
    modalities = {spectrum.modality for spectrum in spectra}
    if len(modalities) != 1:
        raise HTTPException(
            status_code=422,
            detail="Cross-modality analysis is not supported; select spectra from one modality.",
        )
    if spectra[0].modality.value != "raman":
        raise HTTPException(
            status_code=422,
            detail="Raman is the only supported analysis modality. NMR and mass spectrometry require separate adapters.",
        )

    existing = (
        db.query(AnalysisDataset)
        .filter(AnalysisDataset.owner_id == user.id, AnalysisDataset.name == body.name.strip())
        .one_or_none()
    )
    if existing is not None:
        existing_ids = [spectrum.id for spectrum in _dataset_spectra(existing, db)]
        if existing_ids == unique_ids:
            return _dataset_payload(existing, db)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A dataset with this name already exists. Rename this selection or reuse the existing dataset.",
        )

    dataset = AnalysisDataset(
        owner_id=user.id,
        modality=spectra[0].modality,
        name=body.name.strip(),
        description=body.description.strip() if body.description else None,
    )
    db.add(dataset)
    db.flush()
    db.add_all(
        [
            AnalysisDatasetSpectrum(dataset_id=dataset.id, spectrum_id=spectrum.id, position=position)
            for position, spectrum in enumerate(spectra)
        ]
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A dataset with this name was created concurrently. Choose another name and try again.",
        ) from exc
    db.refresh(dataset)
    return _dataset_payload(dataset, db)


@router.get("/datasets/{dataset_id}", response_model=DatasetOut)
def get_dataset(
    dataset_id: UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> DatasetOut:
    return _dataset_payload(_dataset_or_404(dataset_id, user, db), db)


@router.post("/datasets/{dataset_id}/runs", response_model=RunOut, status_code=status.HTTP_202_ACCEPTED)
def create_run(
    dataset_id: UUID, body: RunCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> AnalysisRun:
    dataset = _dataset_or_404(dataset_id, user, db)
    if body.execution_backend == "hosted":
        raise HTTPException(
            status_code=409,
            detail="Hosted analysis is not enabled. Local runs are free; hosted execution requires quotas, billing, and isolation.",
        )
    if body.analysis_type == "pca" and body.clusters is not None:
        raise HTTPException(status_code=422, detail="clusters is only valid for pca_kmeans runs.")
    if body.analysis_type == "pca_kmeans" and body.clusters is None:
        raise HTTPException(status_code=422, detail="Choose a cluster count for a pca_kmeans run.")

    spectra = _dataset_spectra(dataset, db)
    for spectrum in spectra:
        require_owner_or_public(spectrum, user)
    run = AnalysisRun(
        dataset_id=dataset.id,
        owner_id=user.id,
        analysis_type=body.analysis_type,
        execution_backend=body.execution_backend,
        parameters=body.model_dump(exclude={"analysis_type", "execution_backend"}, exclude_none=True),
        input_manifest=build_input_manifest(spectra, db),
        software_versions=software_versions(),
        quality_checks={"status": "pending"},
        job_signature="pending",
    )
    db.add(run)
    db.flush()
    run.job_signature = sign_run(run)
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


@router.get("/runs/{run_id}", response_model=RunOut)
def get_run(run_id: UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> AnalysisRun:
    return _run_or_404(run_id, user, db)


@router.post("/runs/{run_id}/cancel", response_model=RunOut)
def cancel_run(
    run_id: UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> AnalysisRun:
    run = _run_or_404(run_id, user, db)
    if run.status in {"succeeded", "failed", "cancelled"}:
        return run
    run.cancel_requested = True
    if run.status == "pending":
        run.status = "cancelled"
        run.finished_at = datetime.now(UTC)
    db.commit()
    db.refresh(run)
    return run


@router.get("/contract")
def get_analysis_contract() -> dict[str, object]:
    """Public execution boundary; no hosted capability is implied by this endpoint."""
    return {
        "version": ANALYSIS_CONTRACT_VERSION,
        "supported_local_analysis": ["pca", "pca_kmeans"],
        "hosted_execution": {"enabled": False, "reason": "Requires explicit quotas, billing, and isolated workers."},
        "max_spectra_per_dataset": MAX_ANALYSIS_SPECTRA,
    }