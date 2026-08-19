from __future__ import annotations

from app.ingestion.parsers.registry import PARSERS, find_parser
from tests.test_parsers._fixtures import (
    BRUKER_OPUS,
    HORIBA,
    OCEAN_INSIGHT,
    RENISHAW,
    THERMO,
    WITEC,
    load,
)

EXPECTED = {
    OCEAN_INSIGHT: "ocean_insight",
    HORIBA: "horiba_labspec",
    THERMO: "thermo_jcamp_dx",
    RENISHAW: "renishaw_wdf",
    WITEC: "witec_project",
    BRUKER_OPUS: "bruker_opus",
}


def test_all_six_parsers_registered():
    assert len(PARSERS) == 6
    formats = {p.vendor_format for p in PARSERS}
    assert formats == set(EXPECTED.values())


def test_find_parser_dispatches_each_fixture_to_the_right_parser():
    for fixture, expected_format in EXPECTED.items():
        found = find_parser(load(fixture), fixture)
        assert found is not None, fixture
        assert found.vendor_format == expected_format, fixture


def test_find_parser_returns_none_for_unrecognized_content():
    assert find_parser(b"totally unrecognized content with no markers", "x.txt") is None
    assert find_parser(b"", "empty") is None
