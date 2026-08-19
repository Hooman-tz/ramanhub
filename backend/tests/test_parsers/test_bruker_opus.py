from __future__ import annotations

from app.ingestion.parsers.bruker_opus import BrukerOpusParser
from tests.test_parsers._fixtures import ALL_FIXTURES, BRUKER_OPUS, load

parser = BrukerOpusParser()


def test_can_parse_accepts_own_format():
    assert parser.can_parse(load(BRUKER_OPUS), "sample.0") is True


def test_can_parse_rejects_other_formats():
    for fixture in ALL_FIXTURES:
        if fixture == BRUKER_OPUS:
            continue
        assert parser.can_parse(load(fixture), fixture) is False, fixture


def test_can_parse_handles_garbage_without_raising():
    assert parser.can_parse(b"\x00\x01\x02", "x.bin") is False
    assert parser.can_parse(b"", "empty") is False


def test_parse_best_effort_extracts_embedded_instrument_string():
    metadata = parser.parse(load(BRUKER_OPUS))
    assert metadata.instrument_vendor == "Bruker"
    assert metadata.instrument_model is not None
    assert "Bruker" in metadata.instrument_model
