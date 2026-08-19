from __future__ import annotations

from app.ingestion.parsers.thermo import ThermoParser
from tests.test_parsers._fixtures import ALL_FIXTURES, THERMO, load

parser = ThermoParser()


def test_can_parse_accepts_own_format():
    assert parser.can_parse(load(THERMO), "sample.dx") is True


def test_can_parse_rejects_other_formats():
    for fixture in ALL_FIXTURES:
        if fixture == THERMO:
            continue
        assert parser.can_parse(load(fixture), fixture) is False, fixture


def test_can_parse_handles_garbage_without_raising():
    assert parser.can_parse(b"\x00\x01\x02", "x.bin") is False
    assert parser.can_parse(b"", "empty") is False


def test_parse_extracts_best_effort_fields():
    metadata = parser.parse(load(THERMO))
    assert metadata.instrument_vendor == "Thermo Fisher Scientific"
    assert metadata.resolution_cm1 == 4.0
    assert metadata.laser_wavelength_nm == 785.0
    assert metadata.spectral_range_cm1 == "100-3200"
    assert metadata.acquisition_datetime == "2026/01/31 12:00:00"
    assert metadata.sample_description == "sample_001"
