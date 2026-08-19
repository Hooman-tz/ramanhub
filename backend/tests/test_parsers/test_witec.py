from __future__ import annotations

from app.ingestion.parsers.witec import WitecParser
from tests.test_parsers._fixtures import ALL_FIXTURES, WITEC, load

parser = WitecParser()


def test_can_parse_accepts_own_format_by_extension():
    assert parser.can_parse(load(WITEC), "sample.wip") is True


def test_can_parse_accepts_own_format_by_embedded_marker_regardless_of_extension():
    assert parser.can_parse(load(WITEC), "sample.dat") is True


def test_can_parse_rejects_other_formats():
    for fixture in ALL_FIXTURES:
        if fixture == WITEC:
            continue
        assert parser.can_parse(load(fixture), fixture) is False, fixture


def test_can_parse_rejects_ole2_file_without_witec_marker_or_extension():
    # Generic OLE2 container (e.g. a legacy .doc) should not be misdetected
    # as a WITec project just because it shares the container format.
    ole2_but_not_witec = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 64
    assert parser.can_parse(ole2_but_not_witec, "not_witec.dat") is False


def test_can_parse_handles_garbage_without_raising():
    assert parser.can_parse(b"\x00\x01\x02", "x.bin") is False
    assert parser.can_parse(b"", "empty") is False


def test_parse_best_effort_sets_vendor_only():
    metadata = parser.parse(load(WITEC))
    assert metadata.instrument_vendor == "WITec"
    assert metadata.instrument_model is None
