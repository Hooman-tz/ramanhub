from __future__ import annotations

from app.ingestion.parsers.horiba import HoribaParser
from tests.test_parsers._fixtures import ALL_FIXTURES, HORIBA, load

parser = HoribaParser()


def test_can_parse_accepts_own_format():
    assert parser.can_parse(load(HORIBA), "sample.txt") is True


def test_can_parse_rejects_other_formats():
    for fixture in ALL_FIXTURES:
        if fixture == HORIBA:
            continue
        assert parser.can_parse(load(fixture), fixture) is False, fixture


def test_can_parse_handles_garbage_without_raising():
    assert parser.can_parse(b"\x00\x01\x02", "x.bin") is False
    assert parser.can_parse(b"", "empty") is False


def test_parse_extracts_best_effort_fields():
    metadata = parser.parse(load(HORIBA))
    assert metadata.instrument_vendor == "Horiba"
    assert metadata.instrument_model == "iHR320"
    assert metadata.laser_wavelength_nm == 532.0
    assert metadata.integration_time_ms == 10000.0  # 10s -> 10000ms
    assert metadata.accumulations == 4
    assert metadata.grating_lines_mm == 1800.0
    assert metadata.objective_magnification == 50.0
    assert metadata.spectral_range_cm1 == "100-3200"
    assert metadata.acquisition_datetime == "01/31/2026 12:00:00"
