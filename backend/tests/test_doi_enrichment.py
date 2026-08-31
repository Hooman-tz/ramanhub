"""Tests for the M6.1 DOI enrichment path:

- `_parse_crossref_message` now also pulls `ISSN`, `is-referenced-by-count`
  and a tag-stripped `abstract` out of a Crossref `message`.
- `POST /v1/findings/{id}/link-doi` matches the paper's ISSN against a
  seeded `Journal` row and writes quartile / SJR into `publication_metadata`.
- `POST /v1/findings/{id}/enrich` is a 200 no-op when `OPENROUTER_API_KEY`
  is unset (the state of the test environment).
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.auth.deps import (
    get_current_full_user,
    get_current_user,
    get_current_user_optional,
)
from app.db.session import get_db
from app.doi_lookup import DoiMetadata, _parse_crossref_message
from app.models.journal import Journal
from app.routers import findings

DOI = "10.1021/acs.analchem.0c00001"

CROSSREF_MESSAGE = {
    "DOI": DOI,
    "title": ["Raman Markers of Something"],
    "author": [{"given": "Ada", "family": "Lovelace"}],
    "container-title": ["Analytical Chemistry"],
    "published": {"date-parts": [[2021, 3, 2]]},
    "ISSN": ["0003-2700", "1520-6882"],
    "issn-type": [
        {"value": "0003-2700", "type": "print"},
        {"value": "1520-6882", "type": "electronic"},
    ],
    "is-referenced-by-count": 42,
    "abstract": (
        "<jats:p>We report <jats:italic>in situ</jats:italic> Raman spectra "
        "&amp; a new band at 1600&#x2013;1650 cm.</jats:p>"
    ),
}


@pytest.fixture()
def client(db_session):
    app = FastAPI()
    app.include_router(findings.router)
    current: dict[str, object] = {"user": None}

    def _get_db():
        yield db_session

    def _get_user():
        if current["user"] is None:
            raise HTTPException(status_code=401, detail="Not authenticated")
        return current["user"]

    app.dependency_overrides[get_db] = _get_db
    app.dependency_overrides[get_current_user] = _get_user
    app.dependency_overrides[get_current_full_user] = _get_user
    app.dependency_overrides[get_current_user_optional] = lambda: current["user"]

    c = TestClient(app)
    c.set_current_user = lambda u: current.__setitem__("user", u)
    return c


# --------------------------------------------------------------- parser


def test_parse_crossref_message_extracts_new_fields():
    meta = _parse_crossref_message(DOI, CROSSREF_MESSAGE)

    assert isinstance(meta, DoiMetadata)
    assert meta.issn == ["0003-2700", "1520-6882"]
    assert meta.citations == 42
    # JATS/XML tags stripped, entities unescaped, whitespace collapsed.
    assert "<jats" not in meta.abstract
    assert "&amp;" not in meta.abstract
    assert "in situ" in meta.abstract
    assert meta.abstract.startswith("We report")


def test_parse_crossref_message_tolerates_missing_new_fields():
    meta = _parse_crossref_message(DOI, {"title": ["Bare"]})
    assert meta.issn == []
    assert meta.citations is None
    assert meta.abstract is None


# --------------------------------------------------------------- link-doi


def _make_finding(client, author) -> str:
    client.set_current_user(author)
    resp = client.post("/v1/findings", json={"title": "Has a paper"})
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def test_link_doi_enriches_from_seeded_journal(client, db_session, make_user, monkeypatch):
    db_session.add(
        Journal(
            issn="15206882",
            issn_l="00032700",
            title="Analytical Chemistry",
            sjr=2.34,
            quartile="Q1",
            h_index=250,
            country="United States",
            cover_url="https://example.org/anal-chem.png",
            source="scimago",
        )
    )
    db_session.commit()

    async def _fake_lookup(_doi: str) -> DoiMetadata:
        return _parse_crossref_message(DOI, CROSSREF_MESSAGE)

    monkeypatch.setattr("app.routers.findings.lookup_doi", _fake_lookup)

    author = make_user()
    fid = _make_finding(client, author)

    resp = client.post(f"/v1/findings/{fid}/link-doi", json={"doi": DOI})
    assert resp.status_code == 200, resp.text
    pub = resp.json()["publication_metadata"]

    assert pub["resolved"] is True
    assert pub["doi"] == DOI
    assert pub["issn"] == ["0003-2700", "1520-6882"]
    assert pub["citations"] == 42
    assert pub["quartile"] == "Q1"
    assert pub["sjr"] == 2.34
    assert pub["cover_url"] == "https://example.org/anal-chem.png"
    assert pub["abstract_raw"].startswith("We report")
    # No LLM key in the test env -> no inline ai_summary.
    assert "ai_summary" not in pub


def test_link_doi_without_journal_match_leaves_bibliometrics_null(
    client, make_user, monkeypatch
):
    async def _fake_lookup(_doi: str) -> DoiMetadata:
        return _parse_crossref_message(DOI, CROSSREF_MESSAGE)

    monkeypatch.setattr("app.routers.findings.lookup_doi", _fake_lookup)

    fid = _make_finding(client, make_user())
    resp = client.post(f"/v1/findings/{fid}/link-doi", json={"doi": DOI})
    assert resp.status_code == 200, resp.text
    pub = resp.json()["publication_metadata"]

    assert pub["resolved"] is True
    assert pub["quartile"] is None
    assert pub["sjr"] is None
    assert pub["cover_url"] is None


def test_link_doi_unresolved_still_stores_flag(client, make_user, monkeypatch):
    async def _fake_lookup(_doi: str):
        return None

    monkeypatch.setattr("app.routers.findings.lookup_doi", _fake_lookup)

    fid = _make_finding(client, make_user())
    resp = client.post(f"/v1/findings/{fid}/link-doi", json={"doi": DOI})
    assert resp.status_code == 200, resp.text
    assert resp.json()["publication_metadata"] == {"doi": DOI, "resolved": False}


# --------------------------------------------------------------- enrich


def test_enrich_is_noop_without_llm_key(client, make_user):
    fid = _make_finding(client, make_user())
    resp = client.post(f"/v1/findings/{fid}/enrich")
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"enriched": False, "reason": "llm_not_configured", "ai_summary": None}
