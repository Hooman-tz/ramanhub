"""Tests for app.ingestion.llm_fallback — the Anthropic client is always
mocked here; the real API is never called.

Covers the three required scenarios:
(a) well-formed tool-call response -> validated ExtractedMetadata + cache write
(b) malformed/schema-violating response -> clean failure, no partial state written
(c) cache hit -> client never called
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from app.ingestion.header_hash import compute_header_hash
from app.ingestion.llm_fallback import LLMExtractionError, extract_metadata_via_llm
from app.models.enums import ParseSource
from app.models.vendor_parse_cache import VendorParseCache

HEADER_TEXT = "Some Unknown Vendor Header\nLaser: 785nm\nExposure: 1000ms"


class _FakeToolUseBlock:
    type = "tool_use"

    def __init__(self, name: str, input_: dict):
        self.name = name
        self.input = input_


class _FakeMessage:
    def __init__(self, content):
        self.content = content


class _FakeQuery:
    def __init__(self, row):
        self._row = row

    def filter(self, *args, **kwargs):
        return self

    def one_or_none(self):
        return self._row


class _FakeDB:
    def __init__(self, cached_row=None):
        self._cached_row = cached_row
        self.added = []
        self.commit_count = 0

    def query(self, model):
        return _FakeQuery(self._cached_row)

    def add(self, obj):
        self.added.append(obj)

    def commit(self):
        self.commit_count += 1


def _run(coro):
    return asyncio.run(coro)


def _fake_client_returning(tool_input: dict, tool_name: str = "extract_raman_metadata"):
    fake_client = AsyncMock()
    fake_client.messages.create = AsyncMock(
        return_value=_FakeMessage([_FakeToolUseBlock(tool_name, tool_input)])
    )
    return fake_client


# ---------------------------------------------------------------------------
# (a) well-formed tool-call response
# ---------------------------------------------------------------------------


def test_well_formed_response_validates_and_writes_cache():
    db = _FakeDB(cached_row=None)
    fake_client = _fake_client_returning(
        {
            "modality": "raman",
            "instrument_vendor": "Acme Spectro",
            "laser_wavelength_nm": 785.0,
            "integration_time_ms": 1000.0,
            "raw_extra_fields": {"note": "unknown vendor"},
        }
    )

    with patch("app.ingestion.llm_fallback.anthropic.AsyncAnthropic", return_value=fake_client):
        metadata, source = _run(extract_metadata_via_llm(HEADER_TEXT, db))

    assert source == "llm"
    assert metadata.instrument_vendor == "Acme Spectro"
    assert metadata.laser_wavelength_nm == 785.0
    assert metadata.integration_time_ms == 1000.0

    # A VendorParseCache row was written.
    assert len(db.added) == 1
    cache_row = db.added[0]
    assert isinstance(cache_row, VendorParseCache)
    assert cache_row.source == ParseSource.llm
    assert cache_row.header_hash == compute_header_hash(HEADER_TEXT)
    assert db.commit_count == 1
    fake_client.messages.create.assert_awaited_once()


# ---------------------------------------------------------------------------
# (b) malformed/schema-violating response
# ---------------------------------------------------------------------------


def test_malformed_response_raises_and_writes_nothing():
    db = _FakeDB(cached_row=None)
    # extra="forbid" on ExtractedMetadata means this unexpected top-level key
    # must be rejected outright, not silently merged.
    fake_client = _fake_client_returning({"modality": "raman", "not_a_real_field": "smuggled"})

    with (
        patch("app.ingestion.llm_fallback.anthropic.AsyncAnthropic", return_value=fake_client),
        pytest.raises(LLMExtractionError),
    ):
        _run(extract_metadata_via_llm(HEADER_TEXT, db))

    assert db.added == []
    assert db.commit_count == 0


def test_response_with_wrong_types_raises_and_writes_nothing():
    db = _FakeDB(cached_row=None)
    fake_client = _fake_client_returning(
        {"modality": "raman", "laser_wavelength_nm": "not-a-number"}
    )

    with (
        patch("app.ingestion.llm_fallback.anthropic.AsyncAnthropic", return_value=fake_client),
        pytest.raises(LLMExtractionError),
    ):
        _run(extract_metadata_via_llm(HEADER_TEXT, db))

    assert db.added == []
    assert db.commit_count == 0


def test_missing_tool_call_raises_and_writes_nothing():
    db = _FakeDB(cached_row=None)
    fake_client = AsyncMock()
    fake_client.messages.create = AsyncMock(return_value=_FakeMessage([]))

    with (
        patch("app.ingestion.llm_fallback.anthropic.AsyncAnthropic", return_value=fake_client),
        pytest.raises(LLMExtractionError),
    ):
        _run(extract_metadata_via_llm(HEADER_TEXT, db))

    assert db.added == []
    assert db.commit_count == 0


# ---------------------------------------------------------------------------
# (c) cache hit -> client never called
# ---------------------------------------------------------------------------


def test_cache_hit_never_calls_the_client():
    header_hash = compute_header_hash(HEADER_TEXT)
    cached_row = VendorParseCache(
        header_hash=header_hash,
        modality="raman",
        vendor_format=None,
        parser_version="claude-sonnet-5",
        source=ParseSource.llm,
        parsed_template={"modality": "raman", "instrument_vendor": "Cached Vendor"},
        hit_count=2,
    )
    db = _FakeDB(cached_row=cached_row)
    fake_client = AsyncMock()
    fake_client.messages.create = AsyncMock()

    with patch("app.ingestion.llm_fallback.anthropic.AsyncAnthropic", return_value=fake_client):
        metadata, source = _run(extract_metadata_via_llm(HEADER_TEXT, db))

    assert source == "cache"
    assert metadata.instrument_vendor == "Cached Vendor"
    assert cached_row.hit_count == 3
    fake_client.messages.create.assert_not_awaited()
    assert db.commit_count == 1
