"""M1: findings threads + the /v1/feed surface, cherry-picked from Track A.

Covers the low-friction "post to the feed" path that M1 adds:
  - a note-only finding (no spectra, no figure entries) publishes freely,
  - a finding with a figure/analysis entry still needs its spectra,
  - published findings appear in /v1/feed; drafts do not and 404 for others.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth.deps import get_current_user, get_current_user_optional
from app.db.session import get_db
from app.routers import feed, findings


@pytest.fixture()
def client(db_session):
    app = FastAPI()
    app.include_router(findings.router)
    app.include_router(feed.router)

    current: dict[str, object] = {"user": None}

    def _get_db():
        yield db_session

    app.dependency_overrides[get_db] = _get_db
    app.dependency_overrides[get_current_user] = lambda: current["user"]
    app.dependency_overrides[get_current_user_optional] = lambda: current["user"]

    c = TestClient(app)
    c.set_current_user = lambda u: current.__setitem__("user", u)
    return c


def test_note_only_finding_publishes_and_lands_in_feed(client, make_user):
    author = make_user()
    client.set_current_user(author)

    created = client.post(
        "/v1/findings",
        json={"title": "First note", "abstract_md": "hello world", "tags": ["raman", "test"]},
    )
    assert created.status_code == 201, created.text
    fid = created.json()["id"]
    assert created.json()["accession"].startswith("RH-F-")
    assert created.json()["state"] == "draft"

    published = client.post(f"/v1/findings/{fid}/publish", json={"license_id": "CC-BY-4.0"})
    assert published.status_code == 200, published.text
    assert published.json()["state"] == "published"

    feed_resp = client.get("/v1/feed", params={"filter": "all"})
    assert feed_resp.status_code == 200, feed_resp.text
    ids = {item["id"] for item in feed_resp.json()}
    assert fid in ids
    card = next(i for i in feed_resp.json() if i["id"] == fid)
    assert card["kind"] == "finding"
    assert card["title"] == "First note"
    assert card["author"]["handle"] == author.profile_handle


def test_draft_finding_is_hidden(client, make_user):
    author, other = make_user(), make_user()
    client.set_current_user(author)
    fid = client.post("/v1/findings", json={"title": "wip"}).json()["id"]

    # not in the feed
    client.set_current_user(None)
    assert fid not in {i["id"] for i in client.get("/v1/feed").json()}

    # 404 for a different user, 200 for the owner
    client.set_current_user(other)
    assert client.get(f"/v1/findings/{fid}").status_code == 404
    client.set_current_user(author)
    assert client.get(f"/v1/findings/{fid}").status_code == 200


def test_figure_entry_without_spectra_blocks_publish(client, make_user):
    author = make_user()
    client.set_current_user(author)
    fid = client.post("/v1/findings", json={"title": "has a figure"}).json()["id"]

    entry = client.post(
        f"/v1/findings/{fid}/entries",
        json={"kind": "figure", "body_md": "see fig 1", "config": {"spectra": []}},
    )
    assert entry.status_code == 201, entry.text

    blocked = client.post(f"/v1/findings/{fid}/publish", json={"license_id": "CC-BY-4.0"})
    assert blocked.status_code == 422
    assert "spectra" in blocked.json()["detail"].lower()


def test_following_feed_is_empty_for_anonymous(client):
    client.set_current_user(None)
    resp = client.get("/v1/feed", params={"filter": "following"})
    assert resp.status_code == 200
    assert resp.json() == []


def _publish(client, author, *, title, abstract=None, tags=None):
    client.set_current_user(author)
    created = client.post(
        "/v1/findings",
        json={"title": title, "abstract_md": abstract, "tags": tags or []},
    )
    assert created.status_code == 201, created.text
    fid = created.json()["id"]
    published = client.post(f"/v1/findings/{fid}/publish", json={"license_id": "CC-BY-4.0"})
    assert published.status_code == 200, published.text
    return fid


def test_feed_free_text_matches_more_than_the_first_word(client, make_user):
    """The bug this fixes: the search box used to keep only the first word and
    treat it as an exact tag, so "graphene oxide" searched the tag "graphene"
    and threw the rest away. Abstracts were never searched at all."""
    author = make_user()
    oxide = _publish(
        client, author,
        title="Reduction kinetics",
        abstract="A study of graphene oxide films under 785 nm excitation.",
        tags=["raman"],
    )
    unrelated = _publish(
        client, author, title="Calcite polymorphs", abstract="Nothing to do with carbon.",
        tags=["raman"],
    )

    client.set_current_user(None)
    ids = [i["id"] for i in client.get("/v1/feed", params={"q": "graphene oxide"}).json()]
    assert oxide in ids
    assert unrelated not in ids


def test_feed_tag_filter_is_unchanged_and_composes_with_q(client, make_user):
    """`tag` stays exact JSONB containment. `q` is additive, so the two
    together mean AND rather than either replacing the other."""
    author = make_user()
    tagged = _publish(
        client, author, title="Graphene on copper", abstract="CVD growth.", tags=["graphene"],
    )
    untagged = _publish(
        client, author, title="Graphene on nickel", abstract="Also CVD.", tags=["metals"],
    )

    client.set_current_user(None)
    by_tag = [i["id"] for i in client.get("/v1/feed", params={"tag": "graphene"}).json()]
    assert by_tag == [tagged]

    both = [
        i["id"]
        for i in client.get("/v1/feed", params={"tag": "metals", "q": "graphene"}).json()
    ]
    assert both == [untagged]


def test_feed_ordering_is_unchanged_without_a_query(client, make_user):
    """Text rank only applies when there is text. With no `q` every rank is
    zero and the feed keeps the engagement ordering it has always had."""
    author = make_user()
    first = _publish(client, author, title="One", abstract="a")
    second = _publish(client, author, title="Two", abstract="b")

    client.set_current_user(None)
    ids = [i["id"] for i in client.get("/v1/feed").json()]
    assert set(ids) == {first, second}
    # Newest first, which is what the existing score ordering yields for two
    # items with no votes between them.
    assert ids[0] == second
