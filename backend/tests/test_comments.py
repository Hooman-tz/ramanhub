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


def test_post_and_list_comments(social_client, make_user, make_raw_file):
    owner = make_user()
    commenter = make_user()
    social_client.set_current_user(owner)
    raw_file = make_raw_file(owner)
    spectrum = _create_spectrum(social_client, raw_file)
    _publish(social_client, spectrum["id"])

    social_client.set_current_user(commenter)
    resp = social_client.post(f"/spectra/{spectrum['id']}/comments", json={"body": "Nice spectrum!"})
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["body"] == "Nice spectrum!"
    assert body["user_id"] == str(commenter.id)

    resp = social_client.get(f"/spectra/{spectrum['id']}/comments")
    assert resp.status_code == 200
    comments = resp.json()
    assert len(comments) == 1
    assert comments[0]["body"] == "Nice spectrum!"


def test_comments_ordered_oldest_first(social_client, make_user, make_raw_file):
    owner = make_user()
    commenter = make_user()
    social_client.set_current_user(owner)
    raw_file = make_raw_file(owner)
    spectrum = _create_spectrum(social_client, raw_file)
    _publish(social_client, spectrum["id"])

    social_client.set_current_user(commenter)
    social_client.post(f"/spectra/{spectrum['id']}/comments", json={"body": "first"})
    social_client.post(f"/spectra/{spectrum['id']}/comments", json={"body": "second"})
    social_client.post(f"/spectra/{spectrum['id']}/comments", json={"body": "third"})

    resp = social_client.get(f"/spectra/{spectrum['id']}/comments")
    bodies = [c["body"] for c in resp.json()]
    assert bodies == ["first", "second", "third"]


def test_comments_pagination(social_client, make_user, make_raw_file):
    owner = make_user()
    commenter = make_user()
    social_client.set_current_user(owner)
    raw_file = make_raw_file(owner)
    spectrum = _create_spectrum(social_client, raw_file)
    _publish(social_client, spectrum["id"])

    social_client.set_current_user(commenter)
    for i in range(5):
        social_client.post(f"/spectra/{spectrum['id']}/comments", json={"body": f"c{i}"})

    resp = social_client.get(f"/spectra/{spectrum['id']}/comments", params={"limit": 2, "offset": 1})
    bodies = [c["body"] for c in resp.json()]
    assert bodies == ["c1", "c2"]


def test_blank_comment_rejected(social_client, make_user, make_raw_file):
    owner = make_user()
    social_client.set_current_user(owner)
    raw_file = make_raw_file(owner)
    spectrum = _create_spectrum(social_client, raw_file)
    _publish(social_client, spectrum["id"])

    resp = social_client.post(f"/spectra/{spectrum['id']}/comments", json={"body": "   "})
    assert resp.status_code in (400, 422)


def test_comment_on_private_draft_not_owned_is_404(social_client, make_user, make_raw_file):
    owner = make_user()
    other = make_user()
    social_client.set_current_user(owner)
    raw_file = make_raw_file(owner)
    spectrum = _create_spectrum(social_client, raw_file)

    social_client.set_current_user(other)
    resp = social_client.post(f"/spectra/{spectrum['id']}/comments", json={"body": "hi"})
    assert resp.status_code == 404

    resp = social_client.get(f"/spectra/{spectrum['id']}/comments")
    assert resp.status_code == 404


def test_comment_rate_limit_triggers_after_threshold(social_client, make_user, make_raw_file, monkeypatch):
    monkeypatch.setattr("app.ratelimit._comment_limiter", RateLimiter(max_calls=2, window_seconds=3600))

    owner = make_user()
    commenter = make_user()
    social_client.set_current_user(owner)
    raw_file = make_raw_file(owner)
    spectrum = _create_spectrum(social_client, raw_file)
    _publish(social_client, spectrum["id"])

    social_client.set_current_user(commenter)
    assert social_client.post(f"/spectra/{spectrum['id']}/comments", json={"body": "a"}).status_code == 201
    assert social_client.post(f"/spectra/{spectrum['id']}/comments", json={"body": "b"}).status_code == 201
    resp = social_client.post(f"/spectra/{spectrum['id']}/comments", json={"body": "c"})
    assert resp.status_code == 429
