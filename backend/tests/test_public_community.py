from __future__ import annotations

import pytest

from tests._social_app import build_social_client


@pytest.fixture()
def community_client(db_session):
    return build_social_client(db_session)


def _create_and_publish(client, raw_file, title: str = "Public Raman spectrum") -> dict:
    response = client.post("/spectra", json={"raw_file_id": str(raw_file.id), "title": title})
    assert response.status_code == 201, response.text
    spectrum = response.json()
    response = client.post(
        f"/spectra/{spectrum['id']}/publish", json={"license_id": "CC-BY-4.0"}
    )
    assert response.status_code == 200, response.text
    return spectrum


def test_public_record_and_profile_expose_only_intentional_identity(
    community_client, db_session, make_raw_file, make_user
):
    owner = make_user("researcher@example.com")
    owner.profile_handle = "raman-researcher"
    owner.is_profile_public = True
    owner.bio = "Studies mineral identification with Raman spectroscopy."
    db_session.add(owner)
    db_session.commit()

    community_client.set_current_user(owner)
    spectrum = _create_and_publish(community_client, make_raw_file(owner))
    community_client.set_current_user(None)

    record = community_client.get(f"/public/spectra/{spectrum['id']}")
    assert record.status_code == 200, record.text
    body = record.json()
    assert body["author"]["display_name"] == "Test User"
    assert body["author"]["profile_path"] == "/profiles/raman-researcher"
    assert "researcher@example.com" not in str(body)
    assert "owner_id" not in body
    assert body["download_url"] == f"/spectra/{spectrum['id']}/data"

    profile = community_client.get("/profiles/raman-researcher")
    assert profile.status_code == 200, profile.text
    assert profile.json()["spectra"][0]["id"] == spectrum["id"]
    assert "email" not in profile.json()
    assert "id" not in profile.json()


def test_private_and_moderated_records_are_not_public(
    community_client, db_session, make_raw_file, make_user
):
    owner = make_user()
    moderator = make_user()
    moderator.is_moderator = True
    db_session.add(moderator)
    db_session.commit()

    community_client.set_current_user(owner)
    draft_response = community_client.post(
        "/spectra", json={"raw_file_id": str(make_raw_file(owner).id), "title": "Draft"}
    )
    assert draft_response.status_code == 201
    draft_id = draft_response.json()["id"]
    community_client.set_current_user(None)
    assert community_client.get(f"/public/spectra/{draft_id}").status_code == 404

    community_client.set_current_user(owner)
    spectrum = _create_and_publish(community_client, make_raw_file(owner))
    community_client.set_current_user(moderator)
    report = community_client.post(
        "/community/reports",
        json={"target_type": "spectrum", "target_id": spectrum["id"], "reason": "other"},
    )
    assert report.status_code == 201, report.text
    resolved = community_client.patch(
        f"/community/moderation/reports/{report.json()['id']}",
        json={"action": "hide", "note": "Removed pending review"},
    )
    assert resolved.status_code == 200, resolved.text
    community_client.set_current_user(None)
    assert community_client.get(f"/public/spectra/{spectrum['id']}").status_code == 404


def test_posts_link_only_to_owners_public_spectra_and_hide_after_moderation(
    community_client, db_session, make_raw_file, make_user
):
    owner = make_user()
    reader = make_user()
    moderator = make_user()
    moderator.is_moderator = True
    db_session.add(moderator)
    db_session.commit()

    community_client.set_current_user(owner)
    spectrum = _create_and_publish(community_client, make_raw_file(owner))
    post_response = community_client.post(
        "/community/posts",
        json={
            "kind": "dataset",
            "title": "New mineral reference set",
            "body": "A reproducible public Raman reference set.",
            "spectrum_ids": [spectrum["id"]],
        },
    )
    assert post_response.status_code == 201, post_response.text
    post = post_response.json()
    assert post["spectrum_ids"] == [spectrum["id"]]

    community_client.set_current_user(None)
    listing = community_client.get("/community/posts")
    assert listing.status_code == 200
    assert listing.json()[0]["author"]["display_name"] == "Test User"
    assert "user_id" not in str(listing.json())

    community_client.set_current_user(reader)
    report = community_client.post(
        "/community/reports",
        json={"target_type": "spectrum", "target_id": spectrum["id"], "reason": "spam"},
    )
    assert report.status_code == 201, report.text
    community_client.set_current_user(moderator)
    resolved = community_client.patch(
        f"/community/moderation/reports/{report.json()['id']}", json={"action": "hide"}
    )
    assert resolved.status_code == 200
    community_client.set_current_user(None)
    assert community_client.get(f"/community/posts/{post['id']}").status_code == 404


def test_guest_cannot_post_and_notification_preferences_are_respected(
    community_client, make_raw_file, make_user
):
    owner = make_user()
    commenter = make_user()
    guest = make_user()
    guest.is_guest = True

    community_client.set_current_user(owner)
    spectrum = _create_and_publish(community_client, make_raw_file(owner))
    preferences = community_client.patch(
        "/community/notification-preferences",
        json={"comment_notifications": False},
    )
    assert preferences.status_code == 200

    community_client.set_current_user(guest)
    post_response = community_client.post(
        "/community/posts",
        json={
            "title": "Guest post",
            "body": "Guests cannot publish community updates.",
            "spectrum_ids": [spectrum["id"]],
        },
    )
    assert post_response.status_code == 403

    community_client.set_current_user(commenter)
    comment = community_client.post(
        f"/spectra/{spectrum['id']}/comments", json={"body": "Useful public reference."}
    )
    assert comment.status_code == 201
    assert "user_id" not in comment.json()

    community_client.set_current_user(owner)
    notifications = community_client.get("/community/notifications")
    assert notifications.status_code == 200
    assert notifications.json() == []