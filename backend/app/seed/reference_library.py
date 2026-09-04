"""Import bundled open reference spectra into the public library.

Source-pluggable by design. `ReferenceSource` is the whole contract a new
dataset has to satisfy, so adding NIST, an IRUG subset, or a curated slice of
RamanBench later is a new class in this file and a CLI flag — not a schema
change and not a migration.

Scope of the v1 import is RRUFF's **unoriented high-resolution** set (~8,583
spectra, CC-BY). The low-resolution unoriented set is deliberately excluded:
it is largely the same minerals measured worse, so every low-res twin would
inflate candidate sets and can outrank its own high-res original on cosine.

RamanBench is excluded for a different reason. Its 325k spectra across 74
datasets are overwhelmingly *replicate measurements for classification tasks*
(many spectra of "tumour tissue"), not pure-compound references. Dropped into
a reference library they would swamp 8.5k real standards in every prefilter.
Importing selected pure-compound datasets from it is a per-dataset curation
job, and a legitimate future `ReferenceSource`.

Cost, before you run the full import: roughly 400 MB in object storage and
8,583 Class-A PUTs, plus ~85 MB of `similarity_features.vector` and ~20 MB of
`spectrum_peaks` in Postgres. Check the hosted plan's disk allowance first, and
use `--limit` for a dry run.
"""
from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from sqlalchemy.orm import Session

from app.config import settings
from app.db.base import SessionLocal
from app.discovery.peak_index import get_or_build_peak_index
from app.discovery.raman_similarity import get_or_build_feature
from app.models.accession import next_spectrum_accession
from app.models.enums import (
    Modality,
    ReferenceCurationStatus,
    ReferenceTrustTier,
    SpectrumState,
    UploadStatus,
)
from app.models.raw_file import RawFile
from app.models.reference import ReferenceEntry
from app.models.spectrum import Spectrum
from app.models.user import User
from app.raman_contract import RAMAN_CANONICALIZATION_VERSION, canonicalize_raman_arrays
from app.spectra_io import compute_snr, parse_two_column_raman
from app.storage.s3_client import upload_bytes

SYSTEM_GOOGLE_SUB = "system:reference-library"
SYSTEM_EMAIL = "reference-library@ramanhub.internal"
DEFAULT_LICENSE_ID = "CC-BY-4.0"


@dataclass(frozen=True)
class ReferenceRecord:
    """One reference spectrum, as a source yields it."""

    source: str
    source_id: str
    source_dataset: str
    compound_name: str
    raw_bytes: bytes
    original_filename: str
    chemical_formula: str | None = None
    mineral_name: str | None = None
    cas_number: str | None = None
    provenance_url: str | None = None
    laser_wavelength_nm: float | None = None


class ReferenceSource(Protocol):
    key: str
    dataset_key: str
    license_id: str

    def records(self) -> Iterator[ReferenceRecord]: ...


@dataclass
class ImportStats:
    seen: int = 0
    created: int = 0
    skipped_existing: int = 0
    rejected: int = 0
    reject_reasons: dict[str, int] = field(default_factory=dict)

    def reject(self, reason: str) -> None:
        self.rejected += 1
        self.reject_reasons[reason] = self.reject_reasons.get(reason, 0) + 1

    def describe(self) -> str:
        lines = [
            (
                f"seen={self.seen} created={self.created} "
                f"skipped={self.skipped_existing} rejected={self.rejected}"
            )
        ]
        for reason, count in sorted(self.reject_reasons.items(), key=lambda kv: -kv[1]):
            lines.append(f"  rejected [{count}]: {reason}")
        return "\n".join(lines)


class RruffUnorientedHighRes:
    """RRUFF unoriented high-resolution Raman, read from a local archive.

    The archive is not downloaded here on purpose: it is a few hundred MB from
    a third party under its own terms, so fetching it is an explicit, auditable
    step the operator takes rather than something a seed command does silently.
    Point `--dir` at the unpacked directory of `.txt` files.

    RRUFF filenames encode the record, e.g.
    `Calcite__R040070__Raman__785__unoriented.txt`.
    """

    #: An RRUFF id is "R" followed by digits. Matching merely on a leading "R"
    #: silently captures the mineral name for every mineral that starts with
    #: one — Rutile, Realgar, Rhodochrosite — which both mislabels the record
    #: and breaks the (source, source_id) dedup the importer relies on.
    _RRUFF_ID = re.compile(r"^R\d+$")

    key = "rruff"
    dataset_key = "rruff-unoriented-highres"
    license_id = DEFAULT_LICENSE_ID

    def __init__(self, archive_dir: Path, limit: int | None = None) -> None:
        self.archive_dir = archive_dir
        self.limit = limit

    def records(self) -> Iterator[ReferenceRecord]:
        paths = sorted(self.archive_dir.rglob("*.txt"))
        if self.limit is not None:
            paths = paths[: self.limit]
        for path in paths:
            parts = path.stem.split("__")
            mineral = parts[0].replace("_", " ").strip() if parts else path.stem
            rruff_id = next(
                (p for p in parts if self._RRUFF_ID.match(p)), path.stem
            )
            laser = None
            for p in parts:
                if p.isdigit():
                    laser = float(p)
                    break
            yield ReferenceRecord(
                source=self.key,
                source_id=rruff_id,
                source_dataset=self.dataset_key,
                compound_name=mineral or rruff_id,
                mineral_name=mineral or None,
                provenance_url=f"https://rruff.info/{rruff_id}",
                laser_wavelength_nm=laser,
                raw_bytes=path.read_bytes(),
                original_filename=path.name,
            )


def get_or_create_system_user(db: Session) -> User:
    user = db.query(User).filter_by(google_sub=SYSTEM_GOOGLE_SUB).one_or_none()
    if user is not None:
        return user
    user = User(
        google_sub=SYSTEM_GOOGLE_SUB,
        email=SYSTEM_EMAIL,
        display_name="Reference Library",
        is_guest=False,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _already_imported(db: Session, record: ReferenceRecord) -> bool:
    return (
        db.query(ReferenceEntry.id)
        .filter(
            ReferenceEntry.source == record.source,
            ReferenceEntry.source_id == record.source_id,
        )
        .first()
        is not None
    )


def import_record(
    record: ReferenceRecord,
    db: Session,
    *,
    system_user: User,
    license_id: str,
    warm: bool = True,
) -> ReferenceEntry:
    x, y = parse_two_column_raman(record.raw_bytes)
    # Reject unusable data at the door rather than storing a reference nothing
    # can ever match against.
    x, y, flags = canonicalize_raman_arrays(x, y)

    key = f"reference/{record.source}/{record.source_id}-{uuid4().hex[:8]}.txt"
    upload_bytes(settings.S3_BUCKET_RAW, key, record.raw_bytes, "text/plain")

    digest = sha256(record.raw_bytes).hexdigest()
    raw_file = RawFile(
        owner_id=system_user.id,
        modality=Modality.raman,
        storage_bucket=settings.S3_BUCKET_RAW,
        storage_key=key,
        original_filename=record.original_filename,
        content_hash=digest,
        storage_version=f"sha256:{digest}",
        file_size_bytes=len(record.raw_bytes),
        upload_status=UploadStatus.parsed,
        checksum_verified_at=datetime.now(UTC),
    )
    db.add(raw_file)
    db.flush()

    now = datetime.now(UTC)
    spectrum = Spectrum(
        owner_id=system_user.id,
        raw_file_id=raw_file.id,
        modality=Modality.raman,
        title=record.compound_name,
        material_type=record.mineral_name or record.compound_name,
        excitation_wavelength_nm=record.laser_wavelength_nm,
        snr=compute_snr(y),
        state=SpectrumState.published,
        published_at=now,
        moderation_status="visible",
        license_id=license_id,
        canonicalization_version=RAMAN_CANONICALIZATION_VERSION,
        accession=next_spectrum_accession(db),
        quality_flags={name: True for name in flags},
    )
    db.add(spectrum)
    db.flush()

    entry = ReferenceEntry(
        spectrum_id=spectrum.id,
        compound_name=record.compound_name,
        chemical_formula=record.chemical_formula,
        cas_number=record.cas_number,
        mineral_name=record.mineral_name,
        source=record.source,
        source_id=record.source_id,
        source_dataset=record.source_dataset,
        provenance_url=record.provenance_url,
        trust_tier=ReferenceTrustTier.curated,
        curation_status=ReferenceCurationStatus.approved,
        curated_by=system_user.id,
        curated_at=now,
    )
    db.add(entry)
    db.flush()

    if warm:
        # An unwarmed reference is invisible to the prefilter until the
        # background worker reaches it; warming here makes the import
        # immediately useful.
        get_or_build_feature(spectrum, db)
        get_or_build_peak_index(spectrum, db)

    return entry


def import_source(
    source: ReferenceSource,
    db: Session,
    *,
    system_user: User,
    warm: bool = True,
    progress_every: int = 100,
) -> ImportStats:
    stats = ImportStats()
    for record in source.records():
        stats.seen += 1
        if _already_imported(db, record):
            stats.skipped_existing += 1
            continue
        try:
            # A savepoint per record, not a bare rollback. A malformed file
            # must undo only its own partial writes; rolling the whole session
            # back would discard every reference imported before it.
            with db.begin_nested():
                import_record(
                    record,
                    db,
                    system_user=system_user,
                    license_id=source.license_id,
                    warm=warm,
                )
            # Commit per record so the import is resumable after an
            # interruption rather than all-or-nothing across 8,583 rows.
            db.commit()
            stats.created += 1
        except Exception as exc:  # noqa: BLE001 - a bad record is data, not a crash
            stats.reject(f"{type(exc).__name__}: {exc}"[:160])
        if progress_every and stats.seen % progress_every == 0:
            print(f"  ... {stats.seen} seen, {stats.created} created", flush=True)
    return stats


SOURCES = {
    RruffUnorientedHighRes.dataset_key: RruffUnorientedHighRes,
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        default=RruffUnorientedHighRes.dataset_key,
        choices=sorted(SOURCES),
    )
    parser.add_argument(
        "--dir", type=Path, required=True, help="Unpacked archive directory"
    )
    parser.add_argument(
        "--limit", type=int, default=None, help="Import at most N records (dry run)"
    )
    parser.add_argument("--no-warm", action="store_true", help="Skip index warming")
    args = parser.parse_args()

    if not args.dir.is_dir():
        print(f"Not a directory: {args.dir}", file=sys.stderr)
        raise SystemExit(2)

    source = SOURCES[args.source](args.dir, limit=args.limit)
    db = SessionLocal()
    try:
        system_user = get_or_create_system_user(db)
        stats = import_source(source, db, system_user=system_user, warm=not args.no_warm)
        print(stats.describe())
    finally:
        db.close()


if __name__ == "__main__":
    main()
