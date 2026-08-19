"""Ocean Insight is the one vendor parser with full, tested `parse()`
coverage — positive/negative detection plus field-level extraction
correctness against a realistic synthetic fixture.
"""
from __future__ import annotations

from app.ingestion.parsers.ocean_insight import OceanInsightParser
from tests.test_parsers._fixtures import (
    ALL_FIXTURES,
    BRUKER_OPUS,
    OCEAN_INSIGHT,
    RENISHAW,
    THERMO,
    WITEC,
    load,
)

parser = OceanInsightParser()


def test_can_parse_accepts_own_format():
    assert parser.can_parse(load(OCEAN_INSIGHT), "sample.txt") is True


def test_can_parse_rejects_other_formats():
    for fixture in ALL_FIXTURES:
        if fixture == OCEAN_INSIGHT:
            continue
        assert parser.can_parse(load(fixture), fixture) is False, fixture


def test_can_parse_handles_garbage_without_raising():
    assert parser.can_parse(b"\x00\x01\x02not text at all", "x.bin") is False
    assert parser.can_parse(b"", "empty") is False


def test_parse_extracts_known_fields_correctly():
    metadata = parser.parse(load(OCEAN_INSIGHT))

    assert metadata.modality == "raman"
    assert metadata.instrument_vendor == "Ocean Insight"
    assert metadata.instrument_model == "USB2000+H15466"
    # 100000 usec -> 100.0 ms
    assert metadata.integration_time_ms == 100.0
    assert metadata.accumulations == 3
    assert metadata.laser_wavelength_nm == 785.0
    assert metadata.acquisition_datetime == "Thu Jan 01 00:00:00 GMT 2026"


def test_parse_never_populates_unmapped_fields():
    metadata = parser.parse(load(OCEAN_INSIGHT))
    assert metadata.resolution_cm1 is None
    assert metadata.grating_lines_mm is None
    assert metadata.objective_magnification is None


def test_parse_raw_extra_fields_are_flat_scalars():
    metadata = parser.parse(load(OCEAN_INSIGHT))
    for key, value in metadata.raw_extra_fields.items():
        assert isinstance(key, str)
        assert isinstance(value, (str, int, float))


def test_registry_dispatches_ocean_insight_first():
    from app.ingestion.parsers.registry import find_parser

    found = find_parser(load(OCEAN_INSIGHT), OCEAN_INSIGHT)
    assert found is not None
    assert found.vendor_format == "ocean_insight"


def test_sanity_negative_fixtures_are_distinguishable():
    # Cross-check a couple of the trickiest neighbors explicitly (binary vs
    # text) so a regression in the marker detection shows up clearly.
    assert parser.can_parse(load(BRUKER_OPUS), BRUKER_OPUS) is False
    assert parser.can_parse(load(WITEC), WITEC) is False
    assert parser.can_parse(load(RENISHAW), RENISHAW) is False
    assert parser.can_parse(load(THERMO), THERMO) is False
