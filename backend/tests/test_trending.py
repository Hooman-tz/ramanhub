from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from tests._social_app import build_social_client


@pytest.fixture()
def social_client(db_session):
    return build_social_client(db_session)


def _create_spectrum(client, make_raw_file, owner, title="Test spectrum"):
    # A fresh raw file per spectrum: `POST /spectra` is idempotent per
    # raw_file_id (it returns the existing draft with 200 on a repeat), so
    # every spectrum this test needs must originate from its own upload.
    raw_file = make_raw_file(owner)
    resp = client.post("/spectra", json={"raw_file_id": str(raw_file.id), "title": title})
    assert resp.status_code == 201, resp.text
    return resp.json()


def _publish(client, spectrum_id):
    resp = client.post(f"/spectra/{spectrum_id}/publish", json={"license_id": "CC-BY-4.0"})
    assert resp.status_code == 200, resp.text
    return resp.json()


def _embargo(client, spectrum_id):
    future = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    resp = client.post(
        f"/spectra/{spectrum_id}/publish",
        json={"license_id": "CC-BY-4.0", "embargo_release_at": future},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_trending_ranks_by_recent_vote_count(social_client, make_user, make_raw_file):
    owner = make_user()
    voter1 = make_user()
    voter2 = make_user()
    voter3 = make_user()
    social_client.set_current_user(owner)

    low = _publish(social_client, _create_spectrum(social_client, make_raw_file, owner, "low")["id"])
    high = _publish(social_client, _create_spectrum(social_client, make_raw_file, owner, "high")["id"])

    # "high" gets 3 votes, "low" gets 1 vote -> "high" should rank first
    # regardless of creation/publish order (this is NOT search relevance
    # ordering, which is owned by app.routers.search).
    social_client.set_current_user(voter1)
    social_client.post(f"/spectra/{low['id']}/votes")
    social_client.post(f"/spectra/{high['id']}/votes")

    social_client.set_current_user(voter2)
    social_client.post(f"/spectra/{high['id']}/votes")

    social_client.set_current_user(voter3)
    social_client.post(f"/spectra/{high['id']}/votes")

    resp = social_client.get("/trending")
    assert resp.status_code == 200
    items = resp.json()
    ids_in_order = [item["id"] for item in items]
    assert ids_in_order.index(high["id"]) < ids_in_order.index(low["id"])

    high_item = next(item for item in items if item["id"] == high["id"])
    low_item = next(item for item in items if item["id"] == low["id"])
    assert high_item["vote_count"] == 3
    assert low_item["vote_count"] == 1


def test_trending_excludes_drafts_and_embargoed(social_client, make_user, make_raw_file):
    owner = make_user()
    voter = make_user()
    social_client.set_current_user(owner)

    draft = _create_spectrum(social_client, make_raw_file, owner, "draft-spectrum")
    embargoed = _embargo(
        social_client, _create_spectrum(social_client, make_raw_file, owner, "embargoed-spectrum")["id"]
    )
    published = _publish(
        social_client, _create_spectrum(social_client, make_raw_file, owner, "published-spectrum")["id"]
    )

    social_client.set_current_user(voter)
    # Note: draft can't even be voted on (404), so it stays at 0 votes.
    social_client.post(f"/spectra/{embargoed['id']}/votes")
    social_client.post(f"/spectra/{published['id']}/votes")

    resp = social_client.get("/trending")
    ids = [item["id"] for item in resp.json()]
    assert published["id"] in ids
    assert draft["id"] not in ids
    assert embargoed["id"] not in ids


def test_trending_excludes_zero_vote_spectra(social_client, make_user, make_raw_file):
    owner = make_user()
    voter = make_user()
    social_client.set_current_user(owner)

    voted = _publish(social_client, _create_spectrum(social_client, make_raw_file, owner, "voted")["id"])
    unvoted = _publish(social_client, _create_spectrum(social_client, make_raw_file, owner, "unvoted")["id"])

    social_client.set_current_user(voter)
    social_client.post(f"/spectra/{voted['id']}/votes")

    resp = social_client.get("/trending")
    ids = [item["id"] for item in resp.json()]
    assert voted["id"] in ids
    assert unvoted["id"] not in ids
