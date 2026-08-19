from __future__ import annotations

import pytest

from app.ratelimit import RateLimiter
from tests._social_app import build_social_client


@pytest.fixture()
def social_client(db_session):
    return build_social_client(db_session)


def _create_spectrum(client, raw_file, title="Test spectrum"):
    resp = client.post("/spectra", json={"raw_file_id": str(raw_file.id), "title": title})
    assert resp.status_code == 201, resp.text
    return resp.json()


def _publish(client, spectrum_id):
    resp = client.post(f"/spectra/{spectrum_id}/publish", json={"license_id": "CC-BY-4.0"})
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_toggle_vote_on_then_off(social_client, make_user, make_raw_file):
    owner = make_user()
    voter = make_user()
    social_client.set_current_user(owner)
    raw_file = make_raw_file(owner)
    spectrum = _create_spectrum(social_client, raw_file)
    _publish(social_client, spectrum["id"])

    social_client.set_current_user(voter)
    resp = social_client.post(f"/spectra/{spectrum['id']}/votes")
    assert resp.status_code == 200
    assert resp.json() == {"voted": True, "count": 1}

    # Toggle off: not a duplicate row, just removes the existing vote.
    resp = social_client.post(f"/spectra/{spectrum['id']}/votes")
    assert resp.status_code == 200
    assert resp.json() == {"voted": False, "count": 0}


def test_double_vote_is_idempotent_toggle_not_duplicate(social_client, make_user, make_raw_file):
    owner = make_user()
    voter = make_user()
    social_client.set_current_user(owner)
    raw_file = make_raw_file(owner)
    spectrum = _create_spectrum(social_client, raw_file)
    _publish(social_client, spectrum["id"])

    social_client.set_current_user(voter)
    social_client.post(f"/spectra/{spectrum['id']}/votes")
    social_client.post(f"/spectra/{spectrum['id']}/votes")
    social_client.post(f"/spectra/{spectrum['id']}/votes")

    resp = social_client.get(f"/spectra/{spectrum['id']}/votes")
    assert resp.status_code == 200
    # 3 toggles: on, off, on -> currently voted, count 1.
    assert resp.json() == {"count": 1, "voted_by_me": True}


def test_vote_count_accurate_across_multiple_users(social_client, make_user, make_raw_file):
    owner = make_user()
    voter1 = make_user()
    voter2 = make_user()
    social_client.set_current_user(owner)
    raw_file = make_raw_file(owner)
    spectrum = _create_spectrum(social_client, raw_file)
    _publish(social_client, spectrum["id"])

    social_client.set_current_user(voter1)
    social_client.post(f"/spectra/{spectrum['id']}/votes")
    social_client.set_current_user(voter2)
    social_client.post(f"/spectra/{spectrum['id']}/votes")

    social_client.set_current_user(None)
    resp = social_client.get(f"/spectra/{spectrum['id']}/votes")
    assert resp.json() == {"count": 2, "voted_by_me": False}


def test_voting_on_private_draft_not_owned_is_404(social_client, make_user, make_raw_file):
    owner = make_user()
    other = make_user()
    social_client.set_current_user(owner)
    raw_file = make_raw_file(owner)
    spectrum = _create_spectrum(social_client, raw_file)
    # Never published -> still a draft.

    social_client.set_current_user(other)
    resp = social_client.post(f"/spectra/{spectrum['id']}/votes")
    assert resp.status_code == 404

    resp = social_client.get(f"/spectra/{spectrum['id']}/votes")
    assert resp.status_code == 404


def test_owner_can_vote_on_own_spectrum(social_client, make_user, make_raw_file):
    owner = make_user()
    social_client.set_current_user(owner)
    raw_file = make_raw_file(owner)
    spectrum = _create_spectrum(social_client, raw_file)
    _publish(social_client, spectrum["id"])

    resp = social_client.post(f"/spectra/{spectrum['id']}/votes")
    assert resp.status_code == 200
    assert resp.json() == {"voted": True, "count": 1}


def test_vote_rate_limit_triggers_after_threshold(social_client, make_user, make_raw_file, monkeypatch):
    monkeypatch.setattr("app.ratelimit._vote_limiter", RateLimiter(max_calls=2, window_seconds=3600))

    owner = make_user()
    voter = make_user()
    social_client.set_current_user(owner)
    raw_file = make_raw_file(owner)
    spectrum = _create_spectrum(social_client, raw_file)
    _publish(social_client, spectrum["id"])

    social_client.set_current_user(voter)
    assert social_client.post(f"/spectra/{spectrum['id']}/votes").status_code == 200
    assert social_client.post(f"/spectra/{spectrum['id']}/votes").status_code == 200
    resp = social_client.post(f"/spectra/{spectrum['id']}/votes")
    assert resp.status_code == 429
