"""Owner-scoped multi-spectrum datasets and reproducible analysis runs."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func
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
from app.models.enums import Modality
from app.models.spectrum import Spectrum
from app.models.user import User
from app.processing.state_machine import require_owner_or_public

router = APIRouter(prefix="/analysis", tags=["analysis"])


class DatasetCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=2000)
    # Datasets behave like project folders: they may start empty and grow over
    # time. The >=2 requirement lives on the analysis run, not the container.
    spectrum_ids: list[UUID] = Field(default_factory=list, max_length=MAX_ANALYSIS_SPECTRA)


class DatasetUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=2000)


class DatasetSpectraAdd(BaseModel):
    spectrum_ids: list[UUID] = Field(min_length=1, max_length=MAX_ANALYSIS_SPECTRA)


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


def _load_and_check_spectra(unique_ids: list[UUID], user: User, db: Session) -> list[Spectrum]:
    """Resolve ids to spectra in request order, 404 on any miss, and gate each
    one through the row-level owner/public check."""
    spectra_by_id = {
        spectrum.id: spectrum for spectrum in db.query(Spectrum).filter(Spectrum.id.in_(unique_ids)).all()
    }
    if len(spectra_by_id) != len(unique_ids):
        raise HTTPException(status_code=404, detail="One or more selected spectra were not found.")
    spectra = [spectra_by_id[spectrum_id] for spectrum_id in unique_ids]
    for spectrum in spectra:
        require_owner_or_public(spectrum, user)
    return spectra


def _check_single_raman_modality(spectra: list[Spectrum]) -> None:
    modalities = {spectrum.modality for spectrum in spectra}
    if len(modalities) != 1:
        raise HTTPException(
            status_code=422,
            detail="Cross-modality analysis is not supported; select spectra from one modality.",
        )
    if next(iter(modalities)).value != "raman":
        raise HTTPException(
            status_code=422,
            detail="Raman is the only supported analysis modality. NMR and mass spectrometry require separate adapters.",
        )


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
    spectra = _load_and_check_spectra(unique_ids, user, db) if unique_ids else []
    if spectra:
        _check_single_raman_modality(spectra)
    dataset_modality = spectra[0].modality if spectra else Modality.raman

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
        modality=dataset_modality,
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


@router.patch("/datasets/{dataset_id}", response_model=DatasetOut)
def update_dataset(
    dataset_id: UUID,
    body: DatasetUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DatasetOut:
    dataset = _dataset_or_404(dataset_id, user, db)
    fields = body.model_fields_set

    if "name" in fields and body.name is not None:
        new_name = body.name.strip()
        if not new_name:
            raise HTTPException(status_code=422, detail="Dataset name cannot be blank.")
        if new_name != dataset.name:
            clash = (
                db.query(AnalysisDataset)
                .filter(
                    AnalysisDataset.owner_id == user.id,
                    AnalysisDataset.name == new_name,
                    AnalysisDataset.id != dataset.id,
                )
                .one_or_none()
            )
            if clash is not None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="A dataset with this name already exists.",
                )
            dataset.name = new_name

    if "description" in fields:
        cleaned = body.description.strip() if body.description else None
        dataset.description = cleaned or None

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A dataset with this name already exists.",
        ) from exc
    db.refresh(dataset)
    return _dataset_payload(dataset, db)


@router.delete("/datasets/{dataset_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_dataset(
    dataset_id: UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> None:
    dataset = _dataset_or_404(dataset_id, user, db)
    run_count = db.query(AnalysisRun).filter(AnalysisRun.dataset_id == dataset.id).count()
    if run_count:
        # `analysis_runs.dataset_id` has no ON DELETE rule and runs are the
        # immutable, reproducible record of an analysis — refuse rather than
        # silently orphan or destroy them.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This dataset has analysis runs. Delete those runs before deleting the dataset.",
        )
    # Membership rows go via the ON DELETE CASCADE FK; the spectra themselves
    # are independent records and are left untouched.
    db.delete(dataset)
    db.commit()


@router.post("/datasets/{dataset_id}/spectra", response_model=DatasetOut)
def add_dataset_spectra(
    dataset_id: UUID,
    body: DatasetSpectraAdd,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DatasetOut:
    dataset = _dataset_or_404(dataset_id, user, db)
    incoming = list(dict.fromkeys(body.spectrum_ids))

    existing_rows = (
        db.query(AnalysisDatasetSpectrum)
        .filter(AnalysisDatasetSpectrum.dataset_id == dataset.id)
        .all()
    )
    present = {row.spectrum_id for row in existing_rows}
    new_ids = [spectrum_id for spectrum_id in incoming if spectrum_id not in present]
    if not new_ids:
        return _dataset_payload(dataset, db)

    if len(present) + len(new_ids) > MAX_ANALYSIS_SPECTRA:
        raise HTTPException(
            status_code=422,
            detail=f"A dataset can hold at most {MAX_ANALYSIS_SPECTRA} spectra.",
        )

    spectra = _load_and_check_spectra(new_ids, user, db)
    if any(spectrum.modality != dataset.modality for spectrum in spectra):
        raise HTTPException(
            status_code=422,
            detail="Every spectrum in a dataset must share its modality.",
        )
    _check_single_raman_modality(spectra)

    next_position = (
        db.query(func.coalesce(func.max(AnalysisDatasetSpectrum.position), -1))
        .filter(AnalysisDatasetSpectrum.dataset_id == dataset.id)
        .scalar()
    ) + 1
    db.add_all(
        [
            AnalysisDatasetSpectrum(
                dataset_id=dataset.id, spectrum_id=spectrum.id, position=next_position + offset
            )
            for offset, spectrum in enumerate(spectra)
        ]
    )
    db.commit()
    db.refresh(dataset)
    return _dataset_payload(dataset, db)


@router.delete(
    "/datasets/{dataset_id}/spectra/{spectrum_id}", status_code=status.HTTP_204_NO_CONTENT
)
def remove_dataset_spectrum(
    dataset_id: UUID,
    spectrum_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    dataset = _dataset_or_404(dataset_id, user, db)
    row = (
        db.query(AnalysisDatasetSpectrum)
        .filter(
            AnalysisDatasetSpectrum.dataset_id == dataset.id,
            AnalysisDatasetSpectrum.spectrum_id == spectrum_id,
        )
        .one_or_none()
    )
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="That spectrum is not a member of this dataset.",
        )
    db.delete(row)
    db.commit()


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
    if len(spectra) < 2:
        raise HTTPException(
            status_code=422,
            detail="An analysis needs at least two spectra in the dataset.",
        )
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