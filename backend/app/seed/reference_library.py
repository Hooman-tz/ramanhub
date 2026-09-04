"""Import bundled open reference spectra into the public library.

Source-pluggable by design. `ReferenceSource` is the whole contract a new
dataset has to satisfy, so adding NIST, an IRUG subset, or a curated slice of
RamanBench later is a new class in this file and a CLI flag — not a schema
change and not a migration.

Two sources ship today.

**Raman Open Database (ROD)** is the one to reach for first: ~1,133 entries
across 500+ phases — minerals, organics, polymers, pigments, drugs — collected
specifically for material identification, and dedicated to the public domain
under CC0. That last part is verified rather than assumed: the statement
appears on the ROD site *and* in the header of every `.rod` file it serves
("All data on this site have been placed in the public domain by the
contributors"). CC0 carries no attribution obligation and no commercial
restriction, so nothing has to be negotiated before importing it.

**RRUFF** is the deeper mineral set (~8,583 unoriented high-resolution
spectra) but its licence is *not* confirmed. Third-party registries describe
it as CC-BY; RRUFF's own about and download pages state no licence at all.
`RruffUnorientedHighRes.license_id` therefore encodes an assumption, and the
importer writes that assumption onto every row it creates. Confirm the terms
with RRUFF in writing before running it.

Scope of the RRUFF import is its **unoriented high-resolution** set. The low-resolution unoriented set is deliberately excluded:
it is largely the same minerals measured worse, so every low-res twin would
inflate candidate sets and can outrank its own high-res original on cosine.

RamanBench is excluded for a different reason. Its 325k spectra across 74
datasets are overwhelmingly *replicate measurements for classification tasks*
(many spectra of "tumour tissue"), not pure-compound references. Dropped into
a reference library they would swamp real standards in every prefilter. It is
also an aggregator — 58 of its 74 datasets are pulled from HuggingFace, Kaggle
and Zenodo — so its CC-BY covers the paper, not each constituent dataset, and
importing it means inheriting 74 separate licence situations.

Two sources that get asked about and are *not* candidates:

* **SDBS** (AIST) forbids the mechanism outright: "Automatically collect data
  by robots or downloading large amounts of data are prohibited", and its FAQ
  limits free use to non-commercial purposes. A seeder is exactly the
  prohibited automated bulk collection. It needs written permission from AIST,
  not code.
* **NIST** publishes Raman *calibration standards* (SRMs for relative
  intensity) and metrology, not a bulk reference spectral library. Their
  licence is permissive; the dataset simply does not exist.

Manufacturer libraries (Aldrich/Sigma, Wiley, Bio-Rad, S.T. Japan) are sold
products under single-user or network licences. Redistributing one inside
RamanHub is a negotiated commercial data licence, not an import.

Cost, before you run the full import: roughly 400 MB in object storage and
8,583 Class-A PUTs, plus ~85 MB of `similarity_features.vector` and ~20 MB of
`spectrum_peaks` in Postgres. Check the hosted plan's disk allowance first, and
use `--limit` for a dry run.
"""
from __future__ import annotations

import argparse
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Iterator, Protocol
from uuid import uuid4

import httpx
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
from app.raman_contract import (
    MIN_CANONICAL_POINTS,
    RAMAN_CANONICALIZATION_VERSION,
    canonicalize_raman_arrays,
)
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
            f"seen={self.seen} created={self.created} "
            f"skipped={self.skipped_existing} rejected={self.rejected}"
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


# ---------------------------------------------------------------------------
# Raman Open Database
# ---------------------------------------------------------------------------

ROD_BASE_URL = "https://solsa.crystallography.net/rod"
#: ROD serves one CIF-ish file per entry under a COD-style fanned-out path,
#: e.g. id 1000001 -> cif/1/00/00/1000001.rod.
#:
#: Ids are not one contiguous block: probing found two series, the main
#: deposit series and a smaller second one (RRUFF-derived spectra contributed
#: into ROD). Each range is carried a little past its observed end so newly
#: deposited entries are picked up without editing this file; unused ids just
#: 404 and cost one polite request each.
ROD_ID_RANGES: tuple[tuple[int, int], ...] = (
    (1000001, 1000800),
    (2000001, 2000100),
)


def rod_entry_path(rod_id: int) -> str:
    """The COD-style fanned-out path for one entry."""
    digits = f"{rod_id:07d}"
    return f"cif/{digits[0]}/{digits[1:3]}/{digits[3:5]}/{digits}.rod"


def _cif_values(text: str) -> dict[str, str]:
    """Pull simple `_tag value` pairs out of a ROD file.

    A deliberately small reader, not a CIF parser. ROD entries only need three
    shapes: `_tag value`, `_tag 'quoted value'`, and a tag whose value is a
    semicolon-delimited text block on following lines. Pulling in a full CIF
    library to read four fields would be a dependency for no benefit, and the
    spectrum itself is read separately by `_cif_spectrum`.
    """
    values: dict[str, str] = {}
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        i += 1
        if not line.startswith("_"):
            continue
        parts = line.split(None, 1)
        tag = parts[0]
        if len(parts) == 2:
            raw = parts[1].strip()
            if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "'\"":
                raw = raw[1:-1]
            values.setdefault(tag, raw.strip())
            continue
        # Bare tag: a semicolon-delimited block may follow.
        if i < len(lines) and lines[i].startswith(";"):
            block: list[str] = [lines[i][1:].strip()]
            i += 1
            while i < len(lines) and not lines[i].startswith(";"):
                block.append(lines[i].strip())
                i += 1
            i += 1  # closing semicolon
            values.setdefault(tag, " ".join(b for b in block if b).strip())
    return values


def _cif_spectrum(text: str) -> list[tuple[float, float]]:
    """Read the `_raman_spectrum.raman_shift` / `.intensity` loop."""
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if line.strip() != "loop_":
            continue
        headers: list[str] = []
        cursor = index + 1
        while cursor < len(lines) and lines[cursor].strip().startswith("_"):
            headers.append(lines[cursor].strip())
            cursor += 1
        if "_raman_spectrum.raman_shift" not in headers:
            continue
        shift_at = headers.index("_raman_spectrum.raman_shift")
        intensity_at = headers.index("_raman_spectrum.intensity")

        points: list[tuple[float, float]] = []
        while cursor < len(lines):
            row = lines[cursor].strip()
            cursor += 1
            if not row or row.startswith(("_", "loop_", "#", "data_")):
                break
            cells = row.split()
            if len(cells) <= max(shift_at, intensity_at):
                break
            try:
                points.append((float(cells[shift_at]), float(cells[intensity_at])))
            except ValueError:
                break
        return points
    return []


def parse_rod_entry(text: str, *, fallback_id: str) -> ReferenceRecord | None:
    """Turn one ROD file into a `ReferenceRecord`, or None if it has no spectrum.

    The spectrum is re-emitted as plain two-column text rather than kept as
    CIF. That is what lets a ROD entry travel the identical path as every other
    upload — `parse_two_column_raman`, canonicalization, storage, similarity
    and peak indexing all stay unaware that CIF was ever involved.
    """
    points = _cif_spectrum(text)
    if len(points) < MIN_CANONICAL_POINTS:
        return None

    values = _cif_values(text)
    rod_id = values.get("_rod_database.code") or fallback_id
    mineral = values.get("_chemical_name_mineral")
    systematic = values.get("_chemical_name_systematic")
    formula = values.get("_chemical_formula_sum")
    name = mineral or systematic or formula or f"ROD {rod_id}"

    laser: float | None = None
    raw_laser = values.get("_raman_measurement_device.excitation_laser_wavelength")
    if raw_laser:
        try:
            laser = float(raw_laser)
        except ValueError:
            laser = None

    payload = "\n".join(f"{x:.6f} {y:.6f}" for x, y in points).encode()
    return ReferenceRecord(
        source="rod",
        source_id=str(rod_id),
        source_dataset=RamanOpenDatabase.dataset_key,
        compound_name=name,
        mineral_name=mineral,
        chemical_formula=formula.replace(" ", "") if formula else None,
        provenance_url=f"{ROD_BASE_URL}/{rod_id}.html",
        laser_wavelength_nm=laser,
        raw_bytes=payload,
        original_filename=f"{rod_id}.rod",
    )


class RamanOpenDatabase:
    """Raman Open Database — CC0, ~1,133 entries, 500+ phases.

    Reads `.rod` files from a local directory. ROD publishes no archive
    tarball, so `fetch_rod_archive` populates that directory one entry at a
    time; keeping fetch and import separate means the import is offline,
    repeatable and testable, and a re-run costs their server nothing.
    """

    key = "rod"
    dataset_key = "raman-open-database"
    # Verified on the ROD site and restated in the header of every file it
    # serves — unlike the RRUFF assumption above, this one is checked.
    license_id = "CC0-1.0"

    def __init__(self, archive_dir: Path, limit: int | None = None) -> None:
        self.archive_dir = archive_dir
        self.limit = limit

    def records(self) -> Iterator[ReferenceRecord]:
        paths = sorted(self.archive_dir.rglob("*.rod"))
        if self.limit is not None:
            paths = paths[: self.limit]
        for path in paths:
            record = parse_rod_entry(
                path.read_text(encoding="utf-8", errors="replace"),
                fallback_id=path.stem,
            )
            if record is not None:
                yield record


def fetch_rod_archive(
    target_dir: Path,
    *,
    ranges: tuple[tuple[int, int], ...] = ROD_ID_RANGES,
    delay_seconds: float = 0.5,
    limit: int | None = None,
) -> int:
    """Download ROD entries into `target_dir`, politely.

    ROD is a small volunteer-run academic service with no bulk archive, so this
    walks the id range one request at a time with a delay, skips anything
    already on disk (making it resumable and a no-op on re-run), and treats a
    404 as "that id is unused" rather than an error — the range is sparse.
    """
    target_dir.mkdir(parents=True, exist_ok=True)
    ids = [i for start, end in ranges for i in range(start, end + 1)]
    saved = 0
    with httpx.Client(
        timeout=30.0, headers={"User-Agent": "RamanHub reference-library importer"}
    ) as client:
        for rod_id in ids:
            if limit is not None and saved >= limit:
                break
            destination = target_dir / f"{rod_id}.rod"
            if destination.exists():
                saved += 1
                continue
            url = f"{ROD_BASE_URL}/{rod_entry_path(rod_id)}"
            try:
                response = client.get(url)
            except httpx.HTTPError:
                response = None
            # Delay after *every* request, not just the ones that returned a
            # file. The id range is sparse, so skipping the wait on a 404 would
            # burst through the unused stretches at full speed — the opposite
            # of what a delay is for.
            time.sleep(delay_seconds)
            if response is None or response.status_code != 200:
                continue
            destination.write_bytes(response.content)
            saved += 1
    return saved


SOURCES = {
    RamanOpenDatabase.dataset_key: RamanOpenDatabase,
    RruffUnorientedHighRes.dataset_key: RruffUnorientedHighRes,
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        default=RamanOpenDatabase.dataset_key,
        choices=sorted(SOURCES),
    )
    parser.add_argument(
        "--dir", type=Path, required=True, help="Directory of source files"
    )
    parser.add_argument(
        "--fetch",
        action="store_true",
        help="Download entries into --dir first (Raman Open Database only)",
    )
    parser.add_argument(
        "--limit", type=int, default=None, help="Handle at most N records (dry run)"
    )
    parser.add_argument("--no-warm", action="store_true", help="Skip index warming")
    args = parser.parse_args()

    if args.fetch:
        if args.source != RamanOpenDatabase.dataset_key:
            print(
                "--fetch is only implemented for the Raman Open Database; other "
                "sources are obtained manually.",
                file=sys.stderr,
            )
            raise SystemExit(2)
        print(f"Fetching ROD entries into {args.dir} ...")
        count = fetch_rod_archive(args.dir, limit=args.limit)
        print(f"  {count} entries available locally")

    if not args.dir.is_dir():
        print(
            f"Not a directory: {args.dir}"
            + ("" if args.fetch else " (pass --fetch to download it)"),
            file=sys.stderr,
        )
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
