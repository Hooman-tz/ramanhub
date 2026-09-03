"""Tests for app.ingestion.llm_fallback — the shared LLM client
(`app.llm.complete_json`) is always mocked here; the real API is never
called.

Covers the required scenarios:
(a) well-formed JSON response -> validated ExtractedMetadata + cache write
(b) schema-violating response -> clean failure, no partial state written
(c) LLM API error -> LLMExtractionError, no partial state written
(d) cache hit -> the LLM client is never called
(e) cache key is FORMAT-ONLY: a second file with the same header template but
    a different name is a pure cache hit with ZERO LLM calls
(f) no OpenRouter key -> valid ExtractedMetadata(modality="raman") + filename
    overlay, never raises
(g) guardrail: the model only ever sees header[:MAX_HEADER_CHARS] + filename,
    and no ingestion call site passes whole-file content
"""
from __future__ import annotations

import asyncio
import inspect
from unittest.mock import AsyncMock, patch

import pytest

from app.ingestion import jobs as jobs_module
from app.ingestion.header_hash import compute_header_hash
from app.ingestion.jobs import _fallback_provenance
from app.ingestion.llm_fallback import (
    MAX_HEADER_CHARS,
    MAX_OUTPUT_TOKENS,
    LLMExtractionError,
    extract_metadata_via_llm,
)
from app.llm import LLMError
from app.models.enums import ParseSource
from app.models.vendor_parse_cache import VendorParseCache

HEADER_TEXT = "Some Unknown Vendor Header\nLaser: 785nm\nExposure: 1000ms"


@pytest.fixture(autouse=True)
def _llm_key_configured():
    """Default every test in this module to "an OpenRouter key IS set" so the
    LLM path is exercised; the no-key test overrides this locally."""
    with patch("app.ingestion.llm_fallback.llm_configured", return_value=True):
        yield


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


def test_cache_write_stores_format_only_template_not_filename_fields():
    """The cached template must be the FORMAT-ONLY parse: a filename hint is
    applied to the returned value but NOT baked into the cache row, so a later
    file with the same header does not inherit this file's filename fields."""
    db = _FakeDB(cached_row=None)
    payload = {"modality": "raman", "instrument_vendor": "Acme"}

    with _patch_complete_json(return_value=payload):
        metadata, source = _run(
            extract_metadata_via_llm(
                HEADER_TEXT, db, filename="graphene_532nm_x100.txt"
            )
        )

    assert source == "llm"
    # Returned value carries the filename overlay...
    assert metadata.laser_wavelength_nm == 532.0
    assert metadata.objective_magnification == 100.0
    assert metadata.sample_description == "graphene"
    # ...but the cache row's template does not.
    cache_row = db.added[0]
    assert cache_row.header_hash == compute_header_hash(HEADER_TEXT)
    assert cache_row.parsed_template.get("laser_wavelength_nm") is None
    assert cache_row.parsed_template.get("objective_magnification") is None
    assert cache_row.parsed_template.get("sample_description") is None


# ---------------------------------------------------------------------------
# (e) cache key is FORMAT-ONLY
# ---------------------------------------------------------------------------


def test_second_file_same_header_different_name_is_pure_cache_hit():
    """A previous edit folded the filename into the cache key, defeating the
    cache. The key must derive from the normalized header text alone."""
    cached_row = VendorParseCache(
        header_hash=compute_header_hash(HEADER_TEXT),
        modality="raman",
        vendor_format=None,
        parser_version="openrouter-llm",
        source=ParseSource.llm,
        parsed_template={"modality": "raman", "instrument_vendor": "Cached Vendor"},
        hit_count=0,
    )
    db = _FakeDB(cached_row=cached_row)

    with _patch_complete_json() as mock_cj:
        metadata, source = _run(
            extract_metadata_via_llm(
                HEADER_TEXT, db, filename="a_completely_different_file_999nm.txt"
            )
        )

    assert source == "cache"
    mock_cj.assert_not_awaited()  # ZERO LLM calls
    assert metadata.instrument_vendor == "Cached Vendor"
    # Overlay still fills a null field deterministically, no model involved.
    assert metadata.laser_wavelength_nm == 999.0


# ---------------------------------------------------------------------------
# (f) no OpenRouter key -> graceful degrade
# ---------------------------------------------------------------------------


def test_no_llm_key_returns_valid_metadata_plus_overlay_without_raising():
    db = _FakeDB(cached_row=None)

    with (
        patch("app.ingestion.llm_fallback.llm_configured", return_value=False),
        _patch_complete_json() as mock_cj,
    ):
        metadata, source = _run(
            extract_metadata_via_llm(
                HEADER_TEXT, db, filename="polystyrene_785nm_10s_x50.txt"
            )
        )

    assert source == "filename-only"
    mock_cj.assert_not_awaited()
    assert metadata.modality == "raman"
    # Filename overlay still runs.
    assert metadata.laser_wavelength_nm == 785.0
    assert metadata.objective_magnification == 50.0
    assert metadata.integration_time_ms == 10_000.0
    assert metadata.sample_description == "polystyrene"
    # Nothing written to the DB for a keyless degrade.
    assert db.added == []
    assert db.commit_count == 0


def test_no_llm_key_with_no_filename_still_returns_bare_raman_metadata():
    db = _FakeDB(cached_row=None)
    with patch("app.ingestion.llm_fallback.llm_configured", return_value=False):
        metadata, source = _run(extract_metadata_via_llm(HEADER_TEXT, db))
    assert source == "filename-only"
    assert metadata.modality == "raman"
    assert metadata.laser_wavelength_nm is None


# ---------------------------------------------------------------------------
# (g) guardrails: bounded input, typed output, deterministic decoding
# ---------------------------------------------------------------------------


def test_model_only_sees_header_sniff_window_and_capped_tokens():
    db = _FakeDB(cached_row=None)
    huge_header = "A" * (MAX_HEADER_CHARS * 4)
    seen: dict[str, object] = {}

    def _capture(**kwargs):
        seen.update(kwargs)
        return {"modality": "raman"}

    with patch(
        "app.ingestion.llm_fallback.complete_json",
        new=AsyncMock(side_effect=_capture),
    ):
        _run(extract_metadata_via_llm(huge_header, db, filename="x.txt"))

    # The prompt can only contain the sniff window's worth of header, plus a
    # short filename line and a fixed preamble.
    assert len(seen["user"]) <= MAX_HEADER_CHARS + 200
    assert "A" * MAX_HEADER_CHARS in seen["user"]
    assert "A" * (MAX_HEADER_CHARS + 1) not in seen["user"]
    # Deterministic decoding + bounded output.
    assert seen["temperature"] == 0.0
    assert seen["max_tokens"] == MAX_OUTPUT_TOKENS


def test_no_ingestion_call_site_passes_whole_file_to_the_llm():
    """`extract_metadata_via_llm` must be fed `header_text` (already sniffed
    to HEADER_SNIFF_BYTES), never raw file bytes / whole content. This test
    fails if a call site regresses to passing `raw_bytes` or file content."""
    src = inspect.getsource(jobs_module)
    idx = src.index("extract_metadata_via_llm(")
    call_window = src[idx : idx + 200]
    assert "header_text" in call_window, call_window
    assert "raw_bytes" not in call_window, call_window
    assert "content" not in call_window, call_window

    # `jobs` is the only module that calls the fallback outside its own package.
    import pathlib

    app_dir = pathlib.Path(jobs_module.__file__).resolve().parents[1]
    callers = []
    for path in app_dir.rglob("*.py"):
        if path.name == "llm_fallback.py":
            continue
        text = path.read_text(encoding="utf-8")
        if "extract_metadata_via_llm(" in text:
            callers.append(path.name)
    assert callers == ["jobs.py"], callers


def test_filename_only_ingestion_is_not_recorded_as_an_llm_parse():
    """A no-key ingestion must not claim an LLM read the file.

    `parser_used` lands in `RawFile.vendor_format`, which is provenance: it is
    the platform's own record of how a spectrum's metadata came to exist. The
    no-key path derives fields from the filename alone, so labelling it
    `llm:...` would be a false claim about a published record.
    """
    parser_used, version, confidence = _fallback_provenance("filename-only")
    assert parser_used == "filename-only"
    assert not parser_used.startswith("llm")
    assert version == "filename-only"
    # Scored below both real fallback paths — a filename guess is the weakest
    # evidence the pipeline can produce.
    assert confidence < _fallback_provenance("llm")[2]
    assert confidence < _fallback_provenance("cache")[2]


def test_llm_and_cache_sources_keep_their_llm_provenance_label():
    assert _fallback_provenance("llm")[0] == "llm:llm"
    assert _fallback_provenance("cache")[0] == "llm:cache"
    # A cache hit replays a parse the model already did on this exact header
    # template, so it is at least as trustworthy as a fresh call.
    assert _fallback_provenance("cache")[2] >= _fallback_provenance("llm")[2]
