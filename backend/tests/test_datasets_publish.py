"""Tests for publishing an `AnalysisDataset`.

Datasets began as strictly private project folders. Publishing is what turns
one into the citable destination a post links to, so the rules that matter
here are: the accession is minted at publish time (not create time), a
non-owner sees a draft as 404 rather than 403, and a dataset can't advertise
data its readers can't actually fetch.
"""

from __future__ import annotations

import uuid


def _published_spectrum(lab_client, raw_file, title="Member") -> dict:
    spectrum = lab_client.post(
        "/spectra", json={"raw_file_id": str(raw_file.id), "title": title}
    ).json()
    published = lab_client.post(
        f"/spectra/{spectrum['id']}/publish", json={"license_id": "CC-BY-4.0"}
    )
    assert published.status_code == 200, published.text
    return published.json()


def _dataset_with(lab_client, name, spectrum_ids) -> dict:
    resp = lab_client.post(
        "/analysis/datasets",
        json={"name": name, "spectrum_ids": [str(s) for s in spectrum_ids]},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_new_dataset_is_a_draft_with_no_accession(lab_client, make_user, make_raw_file):
    owner = make_user()
    lab_client.set_current_user(owner)
    raw_file = make_raw_file(owner)
    member = _published_spectrum(lab_client, raw_file)

    dataset = _dataset_with(lab_client, "Folder", [member["id"]])

    assert dataset["state"] == "draft"
    # Minted at publish, not create — abandoned drafts must not burn citable ids.
    assert dataset["accession"] is None
    assert dataset["published_at"] is None
    assert dataset["is_owner"] is True


def test_publish_mints_a_dataset_accession(lab_client, make_user, make_raw_file):
    owner = make_user()
    lab_client.set_current_user(owner)
    raw_file = make_raw_file(owner)
    member = _published_spectrum(lab_client, raw_file)
    dataset = _dataset_with(lab_client, "Polymer series", [member["id"]])

    resp = lab_client.post(
        f"/analysis/datasets/{dataset['id']}/publish", json={"license_id": "CC-BY-4.0"}
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["state"] == "published"
    assert body["accession"].startswith("RH-D-")
    assert body["published_at"] is not None
    assert body["license_id"] == "CC-BY-4.0"


def test_a_draft_dataset_is_404_for_a_stranger_and_200_once_published(
    lab_client, make_user, make_raw_file
):
    owner = make_user()
    lab_client.set_current_user(owner)
    raw_file = make_raw_file(owner)
    member = _published_spectrum(lab_client, raw_file)
    dataset = _dataset_with(lab_client, "Private folder", [member["id"]])

    stranger = make_user()
    lab_client.set_current_user(stranger)
    # 404, never 403 — a stranger must not be able to tell a private folder
    # from an id that doesn't exist.
    assert lab_client.get(f"/analysis/datasets/{dataset['id']}").status_code == 404

    lab_client.set_current_user(owner)
    lab_client.post(f"/analysis/datasets/{dataset['id']}/publish", json={"license_id": "CC-BY-4.0"})

    lab_client.set_current_user(stranger)
    resp = lab_client.get(f"/analysis/datasets/{dataset['id']}")
    assert resp.status_code == 200
    assert resp.json()["is_owner"] is False


def test_published_dataset_is_readable_logged_out(lab_client, make_user, make_raw_file):
    owner = make_user()
    lab_client.set_current_user(owner)
    raw_file = make_raw_file(owner)
    member = _published_spectrum(lab_client, raw_file)
    dataset = _dataset_with(lab_client, "Public folder", [member["id"]])
    lab_client.post(f"/analysis/datasets/{dataset['id']}/publish", json={"license_id": "CC-BY-4.0"})

    lab_client.set_current_user(None)
    resp = lab_client.get(f"/analysis/datasets/{dataset['id']}")
    assert resp.status_code == 200, resp.text
    assert resp.json()["accession"].startswith("RH-D-")


def test_cannot_publish_a_dataset_holding_a_draft_spectrum(lab_client, make_user, make_raw_file):
    """A published dataset whose members 404 for readers advertises data it
    can't hand over."""
    owner = make_user()
    lab_client.set_current_user(owner)
    raw_file = make_raw_file(owner)
    draft = lab_client.post(
        "/spectra", json={"raw_file_id": str(raw_file.id), "title": "Still a draft"}
    ).json()
    dataset = _dataset_with(lab_client, "Half-baked", [draft["id"]])

    resp = lab_client.post(
        f"/analysis/datasets/{dataset['id']}/publish", json={"license_id": "CC-BY-4.0"}
    )

    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert "published first" in detail["message"]
    assert detail["unpublished"] == [draft["accession"] or draft["id"]]


def test_cannot_publish_an_empty_dataset(lab_client, make_user):
    owner = make_user()
    lab_client.set_current_user(owner)
    dataset = _dataset_with(lab_client, "Empty", [])

    resp = lab_client.post(
        f"/analysis/datasets/{dataset['id']}/publish", json={"license_id": "CC-BY-4.0"}
    )
    assert resp.status_code == 422
    assert "at least one spectrum" in resp.json()["detail"]


def test_publishing_twice_is_refused(lab_client, make_user, make_raw_file):
    owner = make_user()
    lab_client.set_current_user(owner)
    raw_file = make_raw_file(owner)
    member = _published_spectrum(lab_client, raw_file)
    dataset = _dataset_with(lab_client, "Once only", [member["id"]])
    lab_client.post(f"/analysis/datasets/{dataset['id']}/publish", json={"license_id": "CC-BY-4.0"})

    again = lab_client.post(
        f"/analysis/datasets/{dataset['id']}/publish", json={"license_id": "CC-BY-4.0"}
    )
    assert again.status_code == 400


def test_publish_rejects_an_unknown_license(lab_client, make_user, make_raw_file):
    owner = make_user()
    lab_client.set_current_user(owner)
    raw_file = make_raw_file(owner)
    member = _published_spectrum(lab_client, raw_file)
    dataset = _dataset_with(lab_client, "Bad license", [member["id"]])

    resp = lab_client.post(
        f"/analysis/datasets/{dataset['id']}/publish", json={"license_id": "NOT-A-LICENSE"}
    )
    assert resp.status_code == 422


def test_a_stranger_cannot_publish_your_dataset(lab_client, make_user, make_raw_file):
    owner = make_user()
    lab_client.set_current_user(owner)
    raw_file = make_raw_file(owner)
    member = _published_spectrum(lab_client, raw_file)
    dataset = _dataset_with(lab_client, "Mine", [member["id"]])

    stranger = make_user()
    lab_client.set_current_user(stranger)
    resp = lab_client.post(
        f"/analysis/datasets/{dataset['id']}/publish", json={"license_id": "CC-BY-4.0"}
    )
    assert resp.status_code == 404


def test_dataset_payload_carries_member_accession_for_the_data_card(
    lab_client, make_user, make_raw_file
):
    owner = make_user()
    lab_client.set_current_user(owner)
    raw_file = make_raw_file(owner)
    member = _published_spectrum(lab_client, raw_file, title="Control")
    dataset = _dataset_with(lab_client, "With accessions", [member["id"]])

    row = dataset["spectra"][0]
    assert row["accession"] == member["accession"]
    assert row["state"] == "published"


def test_publish_of_unknown_dataset_is_404(lab_client, make_user):
    lab_client.set_current_user(make_user())
    resp = lab_client.post(
        f"/analysis/datasets/{uuid.uuid4()}/publish", json={"license_id": "CC-BY-4.0"}
    )
    assert resp.status_code == 404
