"""Tests for app.doi_lookup — httpx is always mocked here; the real
Crossref API is never called.

Covers:
(a) well-formed response -> parses into DoiMetadata correctly
(b) 404 / not-found -> returns None
(c) malformed/partial response (e.g. missing title) -> doesn't crash, fields
    come back None/empty where absent
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from app.doi_lookup import DoiMetadata, lookup_doi, normalize_doi

DOI = "10.1021/acs.analchem.0c00001"


def _run(coro):
    return asyncio.run(coro)


def _fake_response(status_code: int, json_body=None):
    response = MagicMock()
    response.status_code = status_code
    response.json = MagicMock(return_value=json_body)
    return response


def _patched_client(response):
    fake_client = AsyncMock()
    fake_client.get = AsyncMock(return_value=response)
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=False)
    return patch("app.doi_lookup.httpx.AsyncClient", return_value=fake_client)


# ---------------------------------------------------------------------------
# (a) well-formed response
# ---------------------------------------------------------------------------


def test_well_formed_response_parses_correctly():
    body = {
        "message": {
            "DOI": DOI,
            "title": ["Raman Spectroscopy of Something Interesting"],
            "author": [
                {"given": "Ada", "family": "Lovelace"},
                {"given": "Alan", "family": "Turing"},
            ],
            "container-title": ["Analytical Chemistry"],
            "published": {"date-parts": [[2020, 5, 1]]},
            "URL": "https://doi.org/10.1021/acs.analchem.0c00001",
        }
    }
    with _patched_client(_fake_response(200, body)):
        result = _run(lookup_doi(DOI))

    assert isinstance(result, DoiMetadata)
    assert result.doi == DOI
    assert result.title == "Raman Spectroscopy of Something Interesting"
    assert result.authors == ["Ada Lovelace", "Alan Turing"]
    assert result.journal == "Analytical Chemistry"
    assert result.year == 2020
    assert result.url == "https://doi.org/10.1021/acs.analchem.0c00001"


# ---------------------------------------------------------------------------
# (b) 404 / not found
# ---------------------------------------------------------------------------


def test_404_returns_none():
    with _patched_client(_fake_response(404, {"status": "not found"})):
        result = _run(lookup_doi(DOI))
    assert result is None


def test_empty_doi_returns_none_without_a_request():
    fake_client = AsyncMock()
    fake_client.get = AsyncMock()
    with patch("app.doi_lookup.httpx.AsyncClient", return_value=fake_client):
        result = _run(lookup_doi("   "))
    assert result is None
    fake_client.get.assert_not_called()


def test_normalize_doi_accepts_resolver_urls_and_removes_case_variation():
    assert normalize_doi(" https://doi.org/10.1021/ACS.ANALCHEM.0C00001 ") == DOI
    assert normalize_doi("doi:10.1021/ACS.ANALCHEM.0C00001") == DOI
    assert normalize_doi("not a doi") is None


# ---------------------------------------------------------------------------
# (c) malformed / partial response
# ---------------------------------------------------------------------------


def test_missing_title_does_not_crash():
    body = {
        "message": {
            "DOI": DOI,
            "author": [{"given": "Ada", "family": "Lovelace"}],
        }
    }
    with _patched_client(_fake_response(200, body)):
        result = _run(lookup_doi(DOI))

    assert result is not None
    assert result.title is None
    assert result.authors == ["Ada Lovelace"]
    assert result.journal is None
    assert result.year is None
    # No explicit URL in the response -> falls back to the canonical doi.org link.
    assert result.url == f"https://doi.org/{DOI}"


def test_completely_empty_message_does_not_crash():
    with _patched_client(_fake_response(200, {"message": {}})):
        result = _run(lookup_doi(DOI))

    assert result is not None
    assert result.title is None
    assert result.authors == []
    assert result.journal is None
    assert result.year is None


def test_missing_message_key_returns_none():
    with _patched_client(_fake_response(200, {"status": "ok"})):
        result = _run(lookup_doi(DOI))
    assert result is None


def test_non_json_response_returns_none():
    response = MagicMock()
    response.status_code = 200
    response.json = MagicMock(side_effect=ValueError("not json"))
    with _patched_client(response):
        result = _run(lookup_doi(DOI))
    assert result is None


def test_author_with_only_org_name_field():
    body = {
        "message": {
            "DOI": DOI,
            "title": ["A Paper"],
            "author": [{"name": "Some Consortium"}],
        }
    }
    with _patched_client(_fake_response(200, body)):
        result = _run(lookup_doi(DOI))

    assert result is not None
    assert result.authors == ["Some Consortium"]
