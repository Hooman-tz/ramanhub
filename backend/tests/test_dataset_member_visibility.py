"""A published project must not expose, or hand over, its owner's drafts.

Publishing a dataset already refuses a folder holding unpublished data, on the
stated grounds that "a published dataset whose spectra 404 for everyone but the
owner is worse than no dataset at all". That guard only covered the moment of
publication, so the invariant held exactly until the next edit:

  * `POST /datasets/{id}/spectra` would happily add a draft to an
    already-published folder, after which `GET /datasets/{id}` listed that
    draft's title and accession to any passing stranger; and
  * `POST /datasets/{id}/fork` copied *every* membership row, so forking such a
    folder handed the stranger the draft's data outright — not a metadata leak
    but a data leak.

These tests pin all three sides: the write is refused, the read filters, and
the fork only copies what the caller could have read on its own.
"""

from __future__ import annotations


def _handled(db_session, make_user, handle: str, name: str):
    user = make_user()
    user.profile_handle = handle
    user.display_name = name
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def _published_spectrum(lab_client, raw_file, title="Public") -> dict:
    spectrum = lab_client.post(
        "/spectra", json={"raw_file_id": str(raw_file.id), "title": title}
    ).json()
    published = lab_client.post(
        f"/spectra/{spectrum['id']}/publish", json={"license_id": "CC-BY-4.0"}
    )
    assert published.status_code == 200, published.text
    return published.json()


def _draft_spectrum(lab_client, raw_file, title="Private") -> dict:
    resp = lab_client.post(
        "/spectra", json={"raw_file_id": str(raw_file.id), "title": title}
    )
    assert resp.status_code in (200, 201), resp.text
    return resp.json()


def _published_dataset(lab_client, member_ids, name="Folder") -> dict:
    created = lab_client.post(
        "/analysis/datasets",
        json={"name": name, "spectrum_ids": [str(i) for i in member_ids]},
    )
    assert created.status_code == 201, created.text
    published = lab_client.post(
        f"/analysis/datasets/{created.json()['id']}/publish",
        json={"license_id": "CC-BY-4.0"},
    )
    assert published.status_code == 200, published.text
    return published.json()


def _smuggle_member(db_session, dataset_id, spectrum_id, position=99):
    """Attach a spectrum straight through the model layer.

    Stands in for a membership row written before the guard below existed —
    the read and fork paths must cope with data already in that shape, not
    just refuse to create more of it.
    """
    from app.models.analysis import AnalysisDatasetSpectrum

    db_session.add(
        AnalysisDatasetSpectrum(
            dataset_id=dataset_id, spectrum_id=spectrum_id, position=position
        )
    )
    db_session.commit()


# --- the write is refused ------------------------------------------------


def test_a_draft_cannot_be_added_to_a_published_dataset(
    lab_client, db_session, make_user, make_raw_file
):
    owner = _handled(db_session, make_user, "ada", "Ada")
    lab_client.set_current_user(owner)
    member = _published_spectrum(lab_client, make_raw_file(owner))
    dataset = _published_dataset(lab_client, [member["id"]])

    draft = _draft_spectrum(lab_client, make_raw_file(owner))
    resp = lab_client.post(
        f"/analysis/datasets/{dataset['id']}/spectra",
        json={"spectrum_ids": [draft["id"]]},
    )

    assert resp.status_code == 422, resp.text
    assert "published" in str(resp.json()["detail"]).lower()
    # Refused whole, not partially applied.
    after = lab_client.get(f"/analysis/datasets/{dataset['id']}").json()
    assert [s["id"] for s in after["spectra"]] == [member["id"]]


def test_a_published_spectrum_can_still_be_added_to_a_published_dataset(
    lab_client, db_session, make_user, make_raw_file
):
    """The guard must not freeze a published folder outright."""
    owner = _handled(db_session, make_user, "ada", "Ada")
    lab_client.set_current_user(owner)
    first = _published_spectrum(lab_client, make_raw_file(owner), title="One")
    dataset = _published_dataset(lab_client, [first["id"]])

    second = _published_spectrum(lab_client, make_raw_file(owner), title="Two")
    resp = lab_client.post(
        f"/analysis/datasets/{dataset['id']}/spectra",
        json={"spectrum_ids": [second["id"]]},
    )

    assert resp.status_code == 200, resp.text
    assert len(resp.json()["spectra"]) == 2


def test_a_draft_folder_still_accepts_drafts(
    lab_client, db_session, make_user, make_raw_file
):
    """A private working folder is the normal place for unpublished data."""
    owner = _handled(db_session, make_user, "ada", "Ada")
    lab_client.set_current_user(owner)
    created = lab_client.post(
        "/analysis/datasets", json={"name": "Workbench", "spectrum_ids": []}
    )
    assert created.status_code == 201, created.text
    draft = _draft_spectrum(lab_client, make_raw_file(owner))

    resp = lab_client.post(
        f"/analysis/datasets/{created.json()['id']}/spectra",
        json={"spectrum_ids": [draft["id"]]},
    )

    assert resp.status_code == 200, resp.text
    assert len(resp.json()["spectra"]) == 1


# --- the read filters ----------------------------------------------------


def test_a_stranger_does_not_see_a_smuggled_draft_member(
    lab_client, db_session, make_user, make_raw_file
):
    owner = _handled(db_session, make_user, "ada", "Ada")
    stranger = _handled(db_session, make_user, "lin", "Lin")

    lab_client.set_current_user(owner)
    member = _published_spectrum(lab_client, make_raw_file(owner))
    dataset = _published_dataset(lab_client, [member["id"]])
    draft = _draft_spectrum(lab_client, make_raw_file(owner), title="Unreleased")
    _smuggle_member(db_session, dataset["id"], draft["id"])

    # The owner still sees their own draft in their own folder.
    owner_view = lab_client.get(f"/analysis/datasets/{dataset['id']}").json()
    assert {s["id"] for s in owner_view["spectra"]} == {member["id"], draft["id"]}

    lab_client.set_current_user(stranger)
    stranger_view = lab_client.get(f"/analysis/datasets/{dataset['id']}").json()

    assert [s["id"] for s in stranger_view["spectra"]] == [member["id"]]
    # Neither the id nor the title of the draft leaks.
    assert "Unreleased" not in str(stranger_view)


# --- the fork only copies what the caller could read ---------------------


def test_forking_a_published_folder_does_not_copy_the_owners_draft(
    lab_client, db_session, make_user, make_raw_file
):
    owner = _handled(db_session, make_user, "ada", "Ada")
    stranger = _handled(db_session, make_user, "lin", "Lin")

    lab_client.set_current_user(owner)
    member = _published_spectrum(lab_client, make_raw_file(owner))
    dataset = _published_dataset(lab_client, [member["id"]])
    draft = _draft_spectrum(lab_client, make_raw_file(owner), title="Unreleased")
    _smuggle_member(db_session, dataset["id"], draft["id"])

    lab_client.set_current_user(stranger)
    forked = lab_client.post(f"/analysis/datasets/{dataset['id']}/fork")

    assert forked.status_code == 201, forked.text
    copies = forked.json()["spectra"]
    # One fork, of the published member only — the draft is not copied.
    assert len(copies) == 1
    assert copies[0]["parent_spectrum_id"] == member["id"]
    assert "Unreleased" not in str(forked.json())


def test_forking_a_folder_you_can_read_nothing_in_is_refused(
    lab_client, db_session, make_user, make_raw_file
):
    owner = _handled(db_session, make_user, "ada", "Ada")
    stranger = _handled(db_session, make_user, "lin", "Lin")

    lab_client.set_current_user(owner)
    member = _published_spectrum(lab_client, make_raw_file(owner))
    dataset = _published_dataset(lab_client, [member["id"]])
    # Remove the only readable member, leaving just a draft behind.
    removed = lab_client.delete(
        f"/analysis/datasets/{dataset['id']}/spectra/{member['id']}"
    )
    assert removed.status_code == 204, removed.text
    draft = _draft_spectrum(lab_client, make_raw_file(owner))
    _smuggle_member(db_session, dataset["id"], draft["id"])

    lab_client.set_current_user(stranger)
    resp = lab_client.post(f"/analysis/datasets/{dataset['id']}/fork")

    assert resp.status_code == 422, resp.text
    assert "fork" in resp.json()["detail"].lower()
