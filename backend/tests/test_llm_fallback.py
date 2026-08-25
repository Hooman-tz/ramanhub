"""Tests for app.ingestion.llm_fallback — the LLM provider is always mocked
here; no real API is ever called.

These tests deliberately patch `resolve_provider` rather than any particular
vendor SDK. What this module owns is the *security boundary* — every model
response goes through `ExtractedMetadata.model_validate` and nothing partial
is ever written — and that must hold no matter which provider produced the
dict. Pinning them to one SDK is what made them break when the seam landed.

Covers the three required scenarios:
(a) well-formed tool-call response -> validated ExtractedMetadata + cache write
(b) malformed/schema-violating response -> clean failure, no partial state written
(c) cache hit -> provider never called
"""
from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from app.ingestion.header_hash import compute_header_hash
from app.ingestion.llm_fallback import LLMExtractionError, extract_metadata_via_llm
from app.ingestion.llm_providers import LLMProviderError
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


class _FakeProvider:
    """Returns a canned payload. Deliberately IGNORES the `validate` callback
    so that bad payloads reach `llm_fallback`'s own validation — that is the
    boundary under test. Provider-side retry is covered in
    tests/test_llm_providers.py."""

    model_id = "fake/model-1"

    def __init__(self, payload=None, error: Exception | None = None):
        self._payload = payload
        self._error = error
        self.calls = 0
        self.last_kwargs: dict | None = None

    async def call_tool(self, **kwargs):
        self.calls += 1
        self.last_kwargs = kwargs
        if self._error is not None:
            raise self._error
        return self._payload


def _run(coro):
    return asyncio.run(coro)


def _with_provider(provider):
    return patch("app.ingestion.llm_fallback.resolve_provider", return_value=provider)


# ---------------------------------------------------------------------------
# (a) well-formed tool-call response
# ---------------------------------------------------------------------------


def test_well_formed_response_validates_and_writes_cache():
    db = _FakeDB(cached_row=None)
    provider = _FakeProvider(
        {
            "modality": "raman",
            "instrument_vendor": "Acme Spectro",
            "laser_wavelength_nm": 785.0,
            "integration_time_ms": 1000.0,
            "raw_extra_fields": {"note": "unknown vendor"},
        }
    )

    with _with_provider(provider):
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
    assert provider.calls == 1


def test_cache_records_the_model_that_actually_produced_it():
    """`parser_version` used to be a hardcoded Anthropic model id. With a
    provider seam that would silently mislabel every OpenRouter parse, which
    matters because the cache is replayed later and you need to know what
    produced an entry."""
    db = _FakeDB(cached_row=None)
    provider = _FakeProvider({"modality": "raman", "instrument_vendor": "Acme"})

    with _with_provider(provider):
        _run(extract_metadata_via_llm(HEADER_TEXT, db))

    assert db.added[0].parser_version == "fake/model-1"


def test_only_the_header_is_sent_to_the_model():
    db = _FakeDB(cached_row=None)
    provider = _FakeProvider({"modality": "raman"})

    with _with_provider(provider):
        _run(extract_metadata_via_llm(HEADER_TEXT, db))

    assert HEADER_TEXT in provider.last_kwargs["user_text"]
    assert provider.last_kwargs["tool_name"] == "extract_raman_metadata"


# ---------------------------------------------------------------------------
# (b) malformed/schema-violating response
# ---------------------------------------------------------------------------


def test_malformed_response_raises_and_writes_nothing():
    db = _FakeDB(cached_row=None)
    # extra="forbid" on ExtractedMetadata means this unexpected top-level key
    # must be rejected outright, not silently merged.
    provider = _FakeProvider({"modality": "raman", "not_a_real_field": "smuggled"})

    with _with_provider(provider), pytest.raises(LLMExtractionError):
        _run(extract_metadata_via_llm(HEADER_TEXT, db))

    assert db.added == []
    assert db.commit_count == 0


def test_response_with_wrong_types_raises_and_writes_nothing():
    db = _FakeDB(cached_row=None)
    provider = _FakeProvider({"modality": "raman", "laser_wavelength_nm": "not-a-number"})

    with _with_provider(provider), pytest.raises(LLMExtractionError):
        _run(extract_metadata_via_llm(HEADER_TEXT, db))

    assert db.added == []
    assert db.commit_count == 0


def test_missing_tool_call_raises_and_writes_nothing():
    db = _FakeDB(cached_row=None)
    provider = _FakeProvider(
        error=LLMProviderError("Model did not return the expected tool call")
    )

    with _with_provider(provider), pytest.raises(LLMExtractionError):
        _run(extract_metadata_via_llm(HEADER_TEXT, db))

    assert db.added == []
    assert db.commit_count == 0


def test_provider_transport_failure_is_a_clean_extraction_error():
    """A network/HTTP failure must surface as the same domain error as a bad
    payload — callers (ingestion jobs) have one failure path, not two."""
    db = _FakeDB(cached_row=None)
    provider = _FakeProvider(error=LLMProviderError("OpenRouter HTTP 502: upstream down"))

    with _with_provider(provider), pytest.raises(LLMExtractionError):
        _run(extract_metadata_via_llm(HEADER_TEXT, db))

    assert db.added == []
    assert db.commit_count == 0


# ---------------------------------------------------------------------------
# (c) cache hit -> provider never called
# ---------------------------------------------------------------------------


def test_cache_hit_never_calls_the_provider():
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
    provider = _FakeProvider({"modality": "raman"})

    with _with_provider(provider):
        metadata, source = _run(extract_metadata_via_llm(HEADER_TEXT, db))

    assert source == "cache"
    assert metadata.instrument_vendor == "Cached Vendor"
    assert cached_row.hit_count == 3
    assert provider.calls == 0
    assert db.commit_count == 1
