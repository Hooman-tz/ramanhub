"""The reference-library importer: idempotency, isolation, and index warming."""
from __future__ import annotations

import numpy as np
import pytest

from app.models.enums import ReferenceTrustTier
from app.models.reference import ReferenceEntry
from app.models.similarity import SimilarityFeature
from app.models.spectrum import Spectrum
from app.models.spectrum_peaks import SpectrumPeaks
from app.seed.reference_library import (
    ReferenceRecord,
    get_or_create_system_user,
    import_source,
)


def _two_column(peak_cm1: float) -> bytes:
    x = np.linspace(200.0, 1800.0, 600)
    y = 100.0 * np.exp(-0.5 * ((x - peak_cm1) / 10.0) ** 2)
    return "\n".join(f"{a:.4f} {b:.6f}" for a, b in zip(x, y)).encode()


class FakeSource:
    """A stand-in for RRUFF, so the importer is testable without the archive."""

    key = "rruff"
    dataset_key = "test-set"
    license_id = "CC-BY-4.0"

    def __init__(self, records):
        self._records = records

    def records(self):
        yield from self._records


def _record(source_id: str, name: str, peak: float, *, raw: bytes | None = None):
    return ReferenceRecord(
        source="rruff",
        source_id=source_id,
        source_dataset="test-set",
        compound_name=name,
        mineral_name=name,
        provenance_url=f"https://rruff.info/{source_id}",
        laser_wavelength_nm=785.0,
        raw_bytes=raw if raw is not None else _two_column(peak),
        original_filename=f"{name}.txt",
    )


@pytest.fixture()
def seed_s3(fake_s3, monkeypatch):
    """`fake_s3` patches `upload_bytes` per importing module by design (see its
    docstring); the seeder binds its own name, so it needs its own patch."""

    def upload_bytes(bucket, key, data, content_type=None):
        fake_s3[(bucket, key)] = data

    monkeypatch.setattr("app.seed.reference_library.upload_bytes", upload_bytes)
    return fake_s3


@pytest.fixture()
def system_user(db_session):
    return get_or_create_system_user(db_session)


def test_import_creates_published_curated_references(db_session, seed_s3, system_user):
    source = FakeSource(
        [_record("R1", "Calcite", 1085.0), _record("R2", "Quartz", 464.0)]
    )
    stats = import_source(source, db_session, system_user=system_user)

    assert (stats.created, stats.rejected) == (2, 0), stats.describe()

    entries = db_session.query(ReferenceEntry).all()
    assert {e.compound_name for e in entries} == {"Calcite", "Quartz"}
    for entry in entries:
        assert entry.trust_tier == ReferenceTrustTier.curated
        spectrum = db_session.get(Spectrum, entry.spectrum_id)
        assert spectrum.state.value == "published"
        assert spectrum.license_id == "CC-BY-4.0"
        assert spectrum.accession
        assert spectrum.owner_id == system_user.id


def test_rerunning_the_import_creates_nothing_new(db_session, seed_s3, system_user):
    """Idempotency comes from UNIQUE(source, source_id) — a re-run must be safe."""
    records = [_record("R1", "Calcite", 1085.0), _record("R2", "Quartz", 464.0)]

    first = import_source(FakeSource(records), db_session, system_user=system_user)
    second = import_source(FakeSource(records), db_session, system_user=system_user)

    assert first.created == 2
    assert second.created == 0
    assert second.skipped_existing == 2
    assert db_session.query(ReferenceEntry).count() == 2


def test_one_bad_record_does_not_abort_the_batch(db_session, seed_s3, system_user):
    source = FakeSource(
        [
            _record("R1", "Calcite", 1085.0),
            _record("R2", "Broken", 0.0, raw=b"this is not a spectrum"),
            _record("R3", "Quartz", 464.0),
        ]
    )
    stats = import_source(source, db_session, system_user=system_user)

    assert stats.created == 2
    assert stats.rejected == 1
    assert stats.reject_reasons
    assert db_session.query(ReferenceEntry).count() == 2


def test_imported_references_are_indexed_and_immediately_matchable(
    db_session, seed_s3, system_user
):
    """An unwarmed reference is invisible to the prefilter."""
    source = FakeSource([_record("R1", "Calcite", 1085.0)])
    import_source(source, db_session, system_user=system_user, warm=True)

    entry = db_session.query(ReferenceEntry).one()
    assert (
        db_session.query(SimilarityFeature)
        .filter(SimilarityFeature.spectrum_id == entry.spectrum_id)
        .one()
        .qc_eligible
    )
    peaks = (
        db_session.query(SpectrumPeaks)
        .filter(SpectrumPeaks.spectrum_id == entry.spectrum_id)
        .one()
    )
    assert peaks.qc_eligible
    assert peaks.binned_cm1
    assert peaks.primary_peak_cm1 == pytest.approx(1085.0, abs=5.0)


def test_the_system_user_is_reused_not_duplicated(db_session):
    first = get_or_create_system_user(db_session)
    second = get_or_create_system_user(db_session)
    assert first.id == second.id


def test_rruff_filenames_yield_the_record_id_not_the_mineral_name(tmp_path):
    """Regression: matching on a leading "R" captures the mineral name for
    every mineral that starts with one, which mislabels the record and breaks
    the (source, source_id) dedup the importer relies on for idempotency."""
    from app.seed.reference_library import RruffUnorientedHighRes

    for stem in (
        "Rutile__R040049__Raman__785__unoriented",
        "Realgar__R060284__Raman__532__unoriented",
        "Calcite__R040070__Raman__785__unoriented",
    ):
        (tmp_path / f"{stem}.txt").write_text("100 1.0\n200 2.0\n")

    records = {r.compound_name: r for r in RruffUnorientedHighRes(tmp_path).records()}

    assert records["Rutile"].source_id == "R040049"
    assert records["Realgar"].source_id == "R060284"
    assert records["Calcite"].source_id == "R040070"
    assert records["Rutile"].provenance_url == "https://rruff.info/R040049"
    assert records["Rutile"].laser_wavelength_nm == 785.0
