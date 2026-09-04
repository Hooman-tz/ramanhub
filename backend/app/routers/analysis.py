"""Owner-scoped multi-spectrum datasets and reproducible analysis runs."""
from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.analysis.engine import (
    ANALYSIS_CONTRACT_VERSION,
    MAX_ANALYSIS_SPECTRA,
    build_input_manifest,
    sign_run,
    software_versions,
)
from app.auth.deps import get_current_full_user, get_current_user, get_current_user_optional
from app.db.session import get_db
from app.models.accession import next_dataset_accession
from app.models.analysis import AnalysisDataset, AnalysisDatasetSpectrum, AnalysisRun
from app.models.enums import DatasetState, FindingState, Modality, SpectrumState
from app.models.finding import Finding, FindingCoAuthor, FindingSpectrum
from app.models.license import License
from app.models.spectrum import Spectrum
from app.models.user import User
from app.processing.state_machine import (
    effective_state,
    require_dataset_readable,
    require_owner_or_public,
)

router = APIRouter(prefix="/analysis", tags=["analysis"])

# The single source of truth for a project's visual identity. Mirrored in
# `apps/web/src/components/project-identity.ts`; the web side falls back to
# slot 0 on an unknown value, so adding a slot here is backwards-compatible
# and the two lists need not be deployed together.
PROJECT_COLORS = ("teal", "amber", "blue", "violet", "rose", "green", "cyan", "slate")
PROJECT_ICONS = ("folder", "flask", "atom", "microscope", "beaker", "dna", "layers", "hexagon")

ProjectColor = Literal["teal", "amber", "blue", "violet", "rose", "green", "cyan", "slate"]
ProjectIcon = Literal["folder", "flask", "atom", "microscope", "beaker", "dna", "layers", "hexagon"]


class DatasetCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=2000)
    # Datasets behave like project folders: they may start empty and grow over
    # time. The >=2 requirement lives on the analysis run, not the container.
    spectrum_ids: list[UUID] = Field(default_factory=list, max_length=MAX_ANALYSIS_SPECTRA)
    # Omit both and the server assigns the next slot in the palette, so a
    # user who never opens the picker still gets projects that look different
    # from one another.
    color: ProjectColor | None = None
    icon: ProjectIcon | None = None


class DatasetUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=2000)
    color: ProjectColor | None = None
    icon: ProjectIcon | None = None


class DatasetSpectraAdd(BaseModel):
    spectrum_ids: list[UUID] = Field(min_length=1, max_length=MAX_ANALYSIS_SPECTRA)


class DatasetSpectrumOut(BaseModel):
    id: UUID
    title: str | None
    modality: str
    state: str
    # Carried on the membership payload so a reader rendering a dataset (or a
    # post's data card) gets accession + excitation without one extra request
    # per member.
    accession: str | None = None
    excitation_wavelength_nm: float | None = None
    parent_spectrum_id: UUID | None = None


class DatasetOut(BaseModel):
    id: UUID
    name: str
    description: str | None
    modality: str
    spectra: list[DatasetSpectrumOut]
    created_at: datetime | None
    updated_at: datetime | None
    # Owner-chosen presentation. Typed `str`, not the Literal, so a value
    # written by a newer server never fails serialisation on an older one.
    color: str = PROJECT_COLORS[0]
    icon: str = PROJECT_ICONS[0]
    # Publishing + lineage. `accession` is NULL until the dataset is published.
    accession: str | None = None
    state: str = DatasetState.draft.value
    published_at: datetime | None = None
    license_id: str | None = None
    doi: str | None = None
    parent_dataset_id: UUID | None = None
    owner_id: UUID | None = None
    owner_handle: str | None = None
    is_owner: bool = False


class DatasetContributorOut(BaseModel):
    """One person's credited work inside a project.

    Derived, not stored: there is no dataset membership table. A contributor is
    anyone who owns a spectrum in the folder, or who authored / co-authored a
    Finding that points at the folder or at one of its spectra.
    """

    user_id: UUID
    handle: str | None
    display_name: str | None
    avatar_url: str | None
    affiliation: str | None
    spectra: int
    findings: int
    is_owner: bool


class DatasetPublish(BaseModel):
    license_id: str


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


def _visible_to(spectrum: Spectrum, viewer: User | None) -> bool:
    """Whether `viewer` is allowed to know this spectrum exists.

    The same rule `require_owner_or_public` enforces per row, expressed as a
    predicate so list-shaped endpoints can *filter* where a single-row read
    would *raise*. Published (including a lapsed embargo) is visible to
    everyone; a draft only to its owner.
    """
    if effective_state(spectrum) == SpectrumState.published.value:
        return True
    return viewer is not None and spectrum.owner_id == viewer.id


def _visible_spectra(spectra: list[Spectrum], viewer: User | None) -> list[Spectrum]:
    """Filter dataset members down to what `viewer` may see.

    A published dataset is supposed to contain only published spectra — the
    publish endpoint enforces exactly that. But membership can be edited after
    publication, and rows predating that guard still exist, so every read path
    filters as well rather than trusting the invariant. Without this, a folder
    published today and added to tomorrow would hand a stranger the titles and
    accessions of its owner's drafts.
    """
    return [spectrum for spectrum in spectra if _visible_to(spectrum, viewer)]


def _dataset_payload(
    dataset: AnalysisDataset, db: Session, viewer: User | None = None
) -> DatasetOut:
    spectra = _visible_spectra(_dataset_spectra(dataset, db), viewer)
    owner = db.get(User, dataset.owner_id)
    state = dataset.state.value if isinstance(dataset.state, DatasetState) else dataset.state
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
                # Read-time evaluation, so an embargo that has lapsed reads as
                # published here exactly as it does on the spectrum itself.
                state=effective_state(spectrum),
                accession=spectrum.accession,
                excitation_wavelength_nm=(
                    float(spectrum.excitation_wavelength_nm)
                    if spectrum.excitation_wavelength_nm is not None
                    else None
                ),
                parent_spectrum_id=spectrum.parent_spectrum_id,
            )
            for spectrum in spectra
        ],
        created_at=dataset.created_at,
        updated_at=dataset.updated_at,
        color=dataset.color,
        icon=dataset.icon,
        accession=dataset.accession,
        state=state,
        published_at=dataset.published_at,
        license_id=dataset.license_id,
        doi=dataset.doi,
        parent_dataset_id=dataset.parent_dataset_id,
        owner_id=dataset.owner_id,
        owner_handle=owner.profile_handle if owner else None,
        is_owner=viewer is not None and dataset.owner_id == viewer.id,
    )


def _unique_dataset_name(base: str, owner_id: UUID, db: Session) -> str:
    """Find a free name under `uq_analysis_dataset_owner_name`.

    Forking the same dataset twice is a normal thing to do — you tried one
    pipeline, you want to try another. Returning 409 "you already have a
    folder with that name" would make the second fork the user's problem to
    solve, so suffix instead: "Name (fork)", "Name (fork 2)", ...
    """
    base = base.strip()[:140] or "Dataset"
    taken = {
        name
        for (name,) in db.query(AnalysisDataset.name)
        .filter(AnalysisDataset.owner_id == owner_id)
        .all()
    }
    candidate = f"{base} (fork)"
    suffix = 2
    # Bounded: the unique constraint is still the real guard, this loop just
    # avoids handing the user an avoidable error.
    while candidate in taken and suffix < 1000:
        candidate = f"{base} (fork {suffix})"
        suffix += 1
    return candidate[:160]


def fork_spectra_into_dataset(
    spectra: list[Spectrum],
    user: User,
    db: Session,
    name: str,
    parent_dataset_id: UUID | None = None,
) -> AnalysisDataset:
    """Fork every spectrum in `spectra` and bundle the copies into a new draft
    dataset owned by `user`. Flushed, NOT committed — the caller commits.

    This is the single "fork it to my lab" primitive behind both
    `POST /analysis/datasets/{id}/fork` and
    `POST /v1/findings/{id}/fork-data`: one call gets you a working folder
    with your own copies of the data, ledgers replayed, ready to process.

    Callers MUST have already gated each spectrum for readability.
    """
    if not spectra:
        raise HTTPException(status_code=422, detail="There is no data here to fork.")
    if len(spectra) > MAX_ANALYSIS_SPECTRA:
        raise HTTPException(
            status_code=422,
            detail=f"A dataset can hold at most {MAX_ANALYSIS_SPECTRA} spectra.",
        )
    _check_single_raman_modality(spectra)

    # Lazily imported to keep the router import graph acyclic-by-construction,
    # the same way spectra.py reaches into ledgers.py.
    from app.routers.spectra import fork_spectrum_record

    # A fork gets the next free slot rather than inheriting the source's
    # colour: it lands in *your* lab next to your other folders, and two
    # identically-marked projects side by side is the thing the palette exists
    # to prevent.
    fork_color, fork_icon = _next_identity(user.id, db)
    dataset = AnalysisDataset(
        owner_id=user.id,
        modality=spectra[0].modality,
        name=_unique_dataset_name(name, user.id, db),
        description=None,
        state=DatasetState.draft,
        color=fork_color,
        icon=fork_icon,
        parent_dataset_id=parent_dataset_id,
    )
    db.add(dataset)
    db.flush()

    for position, source in enumerate(spectra):
        fork = fork_spectrum_record(source, user, db)
        db.add(
            AnalysisDatasetSpectrum(
                dataset_id=dataset.id, spectrum_id=fork.id, position=position
            )
        )
    db.flush()
    return dataset


def _next_identity(owner_id: UUID, db: Session) -> tuple[str, str]:
    """The next colour/symbol slot for `owner_id`, rotating through the palette.

    Keyed on how many projects the owner already has, so the first eight are
    mutually distinct without the user touching the picker. It is a default,
    not a constraint: nothing stops two projects sharing a colour once you go
    past eight or edit one by hand.
    """
    count = db.query(func.count(AnalysisDataset.id)).filter(AnalysisDataset.owner_id == owner_id).scalar() or 0
    slot = count % len(PROJECT_COLORS)
    return PROJECT_COLORS[slot], PROJECT_ICONS[slot]


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
    return [_dataset_payload(dataset, db, user) for dataset in datasets]


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
            return _dataset_payload(existing, db, user)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A dataset with this name already exists. Rename this selection or reuse the existing dataset.",
        )

    default_color, default_icon = _next_identity(user.id, db)
    dataset = AnalysisDataset(
        owner_id=user.id,
        modality=dataset_modality,
        name=body.name.strip(),
        description=body.description.strip() if body.description else None,
        color=body.color or default_color,
        icon=body.icon or default_icon,
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
    return _dataset_payload(dataset, db, user)


@router.get("/datasets/{dataset_id}", response_model=DatasetOut)
def get_dataset(
    dataset_id: UUID,
    db: Session = Depends(get_db),
    # The one dataset route a non-owner can reach. Published datasets are the
    # citable destination a post links to, so this read has to work for a
    # logged-out reader; every *mutating* dataset route below stays on
    # `_dataset_or_404`.
    user: User | None = Depends(get_current_user_optional),
) -> DatasetOut:
    dataset = db.get(AnalysisDataset, dataset_id)
    require_dataset_readable(dataset, user)
    return _dataset_payload(dataset, db, user)


@router.get("/datasets/{dataset_id}/contributors", response_model=list[DatasetContributorOut])
def list_dataset_contributors(
    dataset_id: UUID,
    db: Session = Depends(get_db),
    # Same reach as `get_dataset`: a published dataset is a citable public
    # destination, so its credit list has to render for a logged-out reader.
    user: User | None = Depends(get_current_user_optional),
) -> list[DatasetContributorOut]:
    """Who contributed to this project, and how much.

    There is no dataset membership table and this endpoint deliberately does
    not add one. A project already accumulates other people's work through two
    existing routes, and both are read back here:

      * `POST /datasets/{id}/spectra` gates each member through
        `require_owner_or_public`, so a folder may hold anyone's *published*
        spectra alongside the owner's own drafts.
      * a Finding points at a project (`findings.dataset_id`) or at one of its
        spectra (`finding_spectra`), and carries an ordered co-author list.

    Visibility is evaluated per requester, not per dataset owner: an item
    counts only if it is published or the requester owns it. Counting someone
    else's draft would leak its existence through an integer, which is the
    same disclosure `require_owner_or_public` exists to prevent.
    """
    dataset = db.get(AnalysisDataset, dataset_id)
    require_dataset_readable(dataset, user)
    viewer_id = user.id if user is not None else None

    members = (
        db.query(Spectrum)
        .join(AnalysisDatasetSpectrum, AnalysisDatasetSpectrum.spectrum_id == Spectrum.id)
        .filter(AnalysisDatasetSpectrum.dataset_id == dataset.id)
        .all()
    )
    visible_spectra = _visible_spectra(members, user)

    # A Finding reaches the project either by pointing at the folder or by
    # citing one of its (visible) spectra.
    reaches = [Finding.dataset_id == dataset.id]
    member_ids = [spectrum.id for spectrum in visible_spectra]
    if member_ids:
        reaches.append(FindingSpectrum.spectrum_id.in_(member_ids))
    findings = (
        db.query(Finding)
        .outerjoin(FindingSpectrum, FindingSpectrum.finding_id == Finding.id)
        .filter(or_(*reaches))
        .distinct()
        .all()
    )
    visible_findings = [
        finding
        for finding in findings
        if finding.state == FindingState.published
        or (viewer_id is not None and finding.owner_id == viewer_id)
    ]

    spectra_counts: Counter[UUID] = Counter(spectrum.owner_id for spectrum in visible_spectra)

    # Credit the author and every co-author once each. The pair set is what
    # keeps an owner who also appears in their own co-author list from being
    # counted twice for the same Finding.
    credited: set[tuple[UUID, UUID]] = {
        (finding.id, finding.owner_id) for finding in visible_findings
    }
    finding_ids = [finding.id for finding in visible_findings]
    if finding_ids:
        for row in (
            db.query(FindingCoAuthor).filter(FindingCoAuthor.finding_id.in_(finding_ids)).all()
        ):
            credited.add((row.finding_id, row.user_id))
    finding_counts: Counter[UUID] = Counter(user_id for _, user_id in credited)

    # The owner always appears, even on an empty folder — a project with no
    # spectra yet still belongs to someone.
    user_ids = set(spectra_counts) | set(finding_counts) | {dataset.owner_id}
    people = {
        row.id: row for row in db.query(User).filter(User.id.in_(user_ids)).all()
    }

    out = [
        DatasetContributorOut(
            user_id=user_id,
            handle=getattr(people.get(user_id), "profile_handle", None),
            display_name=getattr(people.get(user_id), "display_name", None),
            avatar_url=getattr(people.get(user_id), "avatar_url", None),
            affiliation=getattr(people.get(user_id), "affiliation", None),
            spectra=spectra_counts.get(user_id, 0),
            findings=finding_counts.get(user_id, 0),
            is_owner=user_id == dataset.owner_id,
        )
        for user_id in user_ids
    ]
    # Most work first; the owner breaks ties ahead of equally-credited guests,
    # then handle so the order is stable across requests.
    out.sort(key=lambda c: (-(c.spectra + c.findings), not c.is_owner, c.handle or ""))
    return out


@router.post("/datasets/{dataset_id}/publish", response_model=DatasetOut)
def publish_dataset(
    dataset_id: UUID,
    body: DatasetPublish,
    db: Session = Depends(get_db),
    # Publishing is the act that puts a citable identifier into the world, so
    # it needs a full account — same bar as publishing a finding.
    user: User = Depends(get_current_full_user),
) -> DatasetOut:
    """Draft -> published: mint an `RH-D-*` accession and open the dataset up.

    Refuses a dataset whose members aren't all readable by the public. A
    published dataset whose spectra 404 for everyone but the owner is worse
    than no dataset at all — it advertises data it can't hand over.
    """
    dataset = _dataset_or_404(dataset_id, user, db)
    if dataset.state != DatasetState.draft:
        raise HTTPException(status_code=400, detail="Only draft datasets can be published.")

    license_row = db.get(License, body.license_id)
    if license_row is None:
        raise HTTPException(status_code=422, detail="Unknown license.")

    spectra = _dataset_spectra(dataset, db)
    if not spectra:
        raise HTTPException(
            status_code=422, detail="Add at least one spectrum before publishing this dataset."
        )
    unpublished = [
        spectrum.accession or str(spectrum.id)
        for spectrum in spectra
        if effective_state(spectrum) != SpectrumState.published.value
    ]
    if unpublished:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "Every spectrum in the dataset must be published first.",
                "unpublished": unpublished,
            },
        )

    dataset.accession = next_dataset_accession(db)
    dataset.state = DatasetState.published
    dataset.published_at = datetime.now(UTC)
    dataset.license_id = license_row.id
    db.add(dataset)
    db.commit()
    db.refresh(dataset)
    return _dataset_payload(dataset, db, user)


@router.post(
    "/datasets/{dataset_id}/fork",
    response_model=DatasetOut,
    status_code=status.HTTP_201_CREATED,
)
def fork_dataset(
    dataset_id: UUID,
    db: Session = Depends(get_db),
    # Guests may fork, same as `POST /spectra/{id}/fork` — trying the tools on
    # public data is the try-before-login loop.
    user: User = Depends(get_current_user),
) -> DatasetOut:
    """Copy a readable dataset and every spectrum in it into the caller's own
    lab as a new draft folder of forks."""
    dataset = db.get(AnalysisDataset, dataset_id)
    require_dataset_readable(dataset, user)

    # Gate every member, not just the folder. `fork_spectra_into_dataset`
    # states that its callers must have already done this, and a fork *copies
    # the data*, not merely its name — so a draft slipping through here would
    # hand a stranger the owner's unpublished spectrum outright, which is a
    # good deal worse than leaking its title.
    spectra = _visible_spectra(_dataset_spectra(dataset, db), user)
    if not spectra:
        raise HTTPException(
            status_code=422, detail="This dataset has no spectra you can fork."
        )

    fork = fork_spectra_into_dataset(
        spectra, user, db, name=dataset.name, parent_dataset_id=dataset.id
    )
    db.commit()
    db.refresh(fork)
    return _dataset_payload(fork, db, user)


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

    # Explicit null is not "reset to default" here — the columns are NOT NULL
    # and a project always has an identity, so only a real value applies.
    if body.color is not None:
        dataset.color = body.color
    if body.icon is not None:
        dataset.icon = body.icon

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A dataset with this name already exists.",
        ) from exc
    db.refresh(dataset)
    return _dataset_payload(dataset, db, user)


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
        return _dataset_payload(dataset, db, user)

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

    # Publishing refuses a folder holding unpublished data, on the grounds
    # that "a published dataset whose spectra 404 for everyone but the owner
    # is worse than no dataset at all". Adding after the fact has to honour
    # the same rule, or the invariant only holds until the next edit.
    if dataset.state != DatasetState.draft:
        unpublished = [
            spectrum.accession or str(spectrum.id)
            for spectrum in spectra
            if effective_state(spectrum) != SpectrumState.published.value
        ]
        if unpublished:
            raise HTTPException(
                status_code=422,
                detail={
                    "message": (
                        "This dataset is published; only published spectra can be added to it."
                    ),
                    "unpublished": unpublished,
                },
            )

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
    return _dataset_payload(dataset, db, user)


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