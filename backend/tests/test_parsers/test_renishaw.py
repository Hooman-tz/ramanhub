from __future__ import annotations

from app.ingestion.parsers.renishaw import RenishawParser
from tests.test_parsers._fixtures import ALL_FIXTURES, RENISHAW, load

parser = RenishawParser()


def test_can_parse_accepts_own_format():
    assert parser.can_parse(load(RENISHAW), "sample.wdf") is True


def test_can_parse_rejects_other_formats():
    for fixture in ALL_FIXTURES:
        if fixture == RENISHAW:
            continue
        assert parser.can_parse(load(fixture), fixture) is False, fixture


def test_can_parse_handles_garbage_without_raising():
    assert parser.can_parse(b"\x00\x01\x02", "x.bin") is False
    assert parser.can_parse(b"", "empty") is False


def test_parse_best_effort_sets_vendor_and_leaves_rest_null():
    metadata = parser.parse(load(RENISHAW))
    assert metadata.instrument_vendor == "Renishaw"
    assert metadata.laser_wavelength_nm == 785.0  # embedded "785 nm" hint in fixture
    assert metadata.integration_time_ms is None
    assert metadata.instrument_model is None
