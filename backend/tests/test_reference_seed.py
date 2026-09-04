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


# ---------------------------------------------------------------------------
# Raman Open Database
# ---------------------------------------------------------------------------

ROD_ENTRY = """#\\#CIF_2.0
#
# This file is available in the Raman Open Database (ROD),
# http://solsa.crystallography.net/rod/
#
# All data on this site have been placed in the public domain by the
# contributors.
#
data_1000001
loop_
_publ_author_name
'El Mendili, Yassine'
_publ_section_title
;
 Insights into the Mechanism Related to the Phase Transition
 from a-Fe2O3 to g-Fe2O3 Nanoparticles
;
_chemical_formula_sum            'Fe2 O3'
_chemical_name_mineral           Hematite
_chemical_name_systematic        'iron(III) oxide'
_raman_measurement_device.excitation_laser_wavelength 514
_rod_database.code               1000001
loop_
_space_group_symop_id
_space_group_symop_operation_xyz
1 x,y,z
2 -y,x-y,z
loop_
_raman_spectrum.raman_shift
_raman_spectrum.intensity
100.0 10.0
110.0 25.0
120.0 90.0
130.0 30.0
140.0 12.0
"""


def test_rod_entry_is_parsed_into_a_reference_record():
    from app.seed.reference_library import parse_rod_entry

    record = parse_rod_entry(ROD_ENTRY, fallback_id="unused")

    assert record is not None
    assert record.source == "rod"
    assert record.source_id == "1000001"
    assert record.compound_name == "Hematite"
    assert record.mineral_name == "Hematite"
    # Whitespace is stripped so the formula is comparable across sources.
    assert record.chemical_formula == "Fe2O3"
    assert record.laser_wavelength_nm == 514.0
    assert record.provenance_url.endswith("/1000001.html")


def test_rod_spectra_are_re_emitted_as_plain_two_column_text():
    """That is what lets a ROD entry travel the same path as any upload."""
    from app.seed.reference_library import parse_rod_entry
    from app.spectra_io import parse_two_column_raman

    record = parse_rod_entry(ROD_ENTRY, fallback_id="unused")
    x, y = parse_two_column_raman(record.raw_bytes)

    assert x.tolist() == [100.0, 110.0, 120.0, 130.0, 140.0]
    assert y.tolist() == [10.0, 25.0, 90.0, 30.0, 12.0]


def test_the_symmetry_loop_is_not_mistaken_for_the_spectrum():
    """A ROD file has several `loop_` blocks; only one is the spectrum."""
    from app.seed.reference_library import _cif_spectrum

    points = _cif_spectrum(ROD_ENTRY)
    assert len(points) == 5
    assert points[0] == (100.0, 10.0)


def test_semicolon_delimited_blocks_do_not_break_the_reader():
    from app.seed.reference_library import _cif_values

    values = _cif_values(ROD_ENTRY)
    assert values["_chemical_name_mineral"] == "Hematite"
    # Quoted values keep their spaces and lose their quotes.
    assert values["_chemical_name_systematic"] == "iron(III) oxide"
    assert "Phase Transition" in values["_publ_section_title"]


def test_an_entry_with_no_spectrum_is_skipped_not_imported():
    from app.seed.reference_library import parse_rod_entry

    header_only = ROD_ENTRY.split("loop_\n_raman_spectrum.raman_shift")[0]
    assert parse_rod_entry(header_only, fallback_id="1000001") is None


def test_rod_ids_fan_out_the_way_the_server_lays_them_out():
    """Entries live at cif/<d1>/<d2d3>/<d4d5>/<id>.rod, COD-style."""
    from app.seed.reference_library import rod_entry_path

    assert rod_entry_path(1000001) == "cif/1/00/00/1000001.rod"
    assert rod_entry_path(1001133) == "cif/1/00/11/1001133.rod"


def test_rod_is_registered_as_a_source_under_cc0():
    from app.seed.reference_library import SOURCES, RamanOpenDatabase

    assert SOURCES[RamanOpenDatabase.dataset_key] is RamanOpenDatabase
    # Verified on the ROD site and in every file header — not an assumption.
    assert RamanOpenDatabase.license_id == "CC0-1.0"
