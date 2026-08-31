"""Tests for app.ingestion.llm_fallback — the shared LLM client
(`app.llm.complete_json`) is always mocked here; the real API is never
called.

Covers the required scenarios:
(a) well-formed JSON response -> validated ExtractedMetadata + cache write
(b) schema-violating response -> clean failure, no partial state written
(c) LLM API error -> LLMExtractionError, no partial state written
(d) cache hit -> the LLM client is never called
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from app.ingestion.header_hash import compute_header_hash
from app.ingestion.llm_fallback import LLMExtractionError, extract_metadata_via_llm
from app.llm import LLMError
from app.models.enums import ParseSource
from app.models.vendor_parse_cache import VendorParseCache

HEADER_TEXT = "Some Unknown Vendor Header\nLaser: 785nm\nExposure: 1000ms"


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


def _patch_complete_json(**kwargs):
    """patch app.ingestion.llm_fallback.complete_json with an AsyncMock."""
    return patch(
        "app.ingestion.llm_fallback.complete_json",
        new=AsyncMock(**kwargs),
    )


# ---------------------------------------------------------------------------
# (a) well-formed response
# ---------------------------------------------------------------------------


def test_well_formed_response_validates_and_writes_cache():
    db = _FakeDB(cached_row=None)
    payload = {
        "modality": "raman",
        "instrument_vendor": "Acme Spectro",
        "laser_wavelength_nm": 785.0,
        "integration_time_ms": 1000.0,
        "raw_extra_fields": {"note": "unknown vendor"},
    }

    with _patch_complete_json(return_value=payload) as mock_cj:
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
    mock_cj.assert_awaited_once()


# ---------------------------------------------------------------------------
# (b) schema-violating response
# ---------------------------------------------------------------------------


def test_malformed_response_raises_and_writes_nothing():
    db = _FakeDB(cached_row=None)
    # extra="forbid" on ExtractedMetadata means this unexpected top-level key
    # must be rejected outright, not silently merged.
    with (
        _patch_complete_json(
            return_value={"modality": "raman", "not_a_real_field": "smuggled"}
        ),
        pytest.raises(LLMExtractionError),
    ):
        _run(extract_metadata_via_llm(HEADER_TEXT, db))

    assert db.added == []
    assert db.commit_count == 0


def test_response_with_wrong_types_raises_and_writes_nothing():
    db = _FakeDB(cached_row=None)
    with (
        _patch_complete_json(
            return_value={"modality": "raman", "laser_wavelength_nm": "not-a-number"}
        ),
        pytest.raises(LLMExtractionError),
    ):
        _run(extract_metadata_via_llm(HEADER_TEXT, db))

    assert db.added == []
    assert db.commit_count == 0


# ---------------------------------------------------------------------------
# (c) LLM API error
# ---------------------------------------------------------------------------


def test_llm_error_raises_and_writes_nothing():
    db = _FakeDB(cached_row=None)
    with (
        _patch_complete_json(side_effect=LLMError("boom")),
        pytest.raises(LLMExtractionError),
    ):
        _run(extract_metadata_via_llm(HEADER_TEXT, db))

    assert db.added == []
    assert db.commit_count == 0


# ---------------------------------------------------------------------------
# (d) cache hit -> client never called
# ---------------------------------------------------------------------------


def test_cache_hit_never_calls_the_client():
    header_hash = compute_header_hash(HEADER_TEXT)
    cached_row = VendorParseCache(
        header_hash=header_hash,
        modality="raman",
        vendor_format=None,
        parser_version="openrouter-llm",
        source=ParseSource.llm,
        parsed_template={"modality": "raman", "instrument_vendor": "Cached Vendor"},
        hit_count=2,
    )
    db = _FakeDB(cached_row=cached_row)

    with _patch_complete_json() as mock_cj:
        metadata, source = _run(extract_metadata_via_llm(HEADER_TEXT, db))

    assert source == "cache"
    assert metadata.instrument_vendor == "Cached Vendor"
    assert cached_row.hit_count == 3
    mock_cj.assert_not_awaited()
    assert db.commit_count == 1
