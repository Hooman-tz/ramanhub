"""A project's colour/symbol identity, and who gets credit inside it.

Two features share this file because they share a subject — the project
folder as something a person recognises and a group contributes to.

The contributor list is *derived*: there is no dataset membership table, and
this deliberately does not add one. A folder already accumulates other
people's work through `POST /datasets/{id}/spectra` (which admits anyone's
published spectrum) and through Findings that point at the folder or cite one
of its spectra. The rule that carries the most weight here is the visibility
one: an item counts only if it is published or the requester owns it, because
counting someone else's draft would leak its existence through an integer.
"""

from __future__ import annotations

from app.models.analysis import AnalysisDatasetSpectrum


def _handled(db_session, make_user, handle: str, name: str):
    user = make_user()
    user.profile_handle = handle
    user.display_name = name
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def _published_spectrum(lab_client, raw_file, title="Member") -> dict:
    spectrum = lab_client.post(
        "/spectra", json={"raw_file_id": str(raw_file.id), "title": title}
    ).json()
    published = lab_client.post(
        f"/spectra/{spectrum['id']}/publish", json={"license_id": "CC-BY-4.0"}
    )
    assert published.status_code == 200, published.text
    return published.json()


def _draft_spectrum(lab_client, raw_file, title="Draft") -> dict:
    resp = lab_client.post(
        "/spectra", json={"raw_file_id": str(raw_file.id), "title": title}
    )
    assert resp.status_code in (200, 201), resp.text
    return resp.json()


def _dataset(lab_client, name, spectrum_ids=(), **extra) -> dict:
    resp = lab_client.post(
        "/analysis/datasets",
        json={"name": name, "spectrum_ids": [str(s) for s in spectrum_ids], **extra},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _contributors(lab_client, dataset_id) -> dict[str, dict]:
    resp = lab_client.get(f"/analysis/datasets/{dataset_id}/contributors")
    assert resp.status_code == 200, resp.text
    return {row["handle"]: row for row in resp.json()}


# --- identity ------------------------------------------------------------


def test_colour_and_icon_round_trip_through_create_and_update(lab_client, make_user):
    owner = make_user()
    lab_client.set_current_user(owner)

    created = _dataset(lab_client, "Perovskites", color="rose", icon="flask")
    assert created["color"] == "rose"
    assert created["icon"] == "flask"

    resp = lab_client.patch(
        f"/analysis/datasets/{created['id']}", json={"color": "violet", "icon": "dna"}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["color"] == "violet"
    assert resp.json()["icon"] == "dna"

    # And it is persisted, not just echoed back.
    assert lab_client.get(f"/analysis/datasets/{created['id']}").json()["color"] == "violet"


def test_an_off_palette_value_is_refused(lab_client, make_user):
    owner = make_user()
    lab_client.set_current_user(owner)

    resp = lab_client.post(
        "/analysis/datasets", json={"name": "Bad", "spectrum_ids": [], "color": "#ff0000"}
    )
    assert resp.status_code == 422


def test_consecutive_projects_get_distinct_identities(lab_client, make_user):
    """The default has to rotate: eight identical teal folders would make the
    palette look broken to the user who never opens the picker."""
    owner = make_user()
    lab_client.set_current_user(owner)

    made = [_dataset(lab_client, f"Project {i}") for i in range(4)]

    assert len({d["color"] for d in made}) == 4
    assert len({d["icon"] for d in made}) == 4


def test_a_rename_leaves_the_identity_alone(lab_client, make_user):
    owner = make_user()
    lab_client.set_current_user(owner)
    created = _dataset(lab_client, "Before", color="cyan", icon="atom")

    resp = lab_client.patch(f"/analysis/datasets/{created['id']}", json={"name": "After"})

    assert resp.status_code == 200, resp.text
    assert resp.json()["name"] == "After"
    assert (resp.json()["color"], resp.json()["icon"]) == ("cyan", "atom")


# --- contributors --------------------------------------------------------


def test_the_owner_is_listed_even_on_an_empty_folder(lab_client, db_session, make_user):
    owner = _handled(db_session, make_user, "ada", "Ada")
    lab_client.set_current_user(owner)
    dataset = _dataset(lab_client, "Empty")

    rows = _contributors(lab_client, dataset["id"])

    assert list(rows) == ["ada"]
    assert rows["ada"]["is_owner"] is True
    assert (rows["ada"]["spectra"], rows["ada"]["findings"]) == (0, 0)


def test_a_second_owners_published_spectrum_credits_them(
    lab_client, db_session, make_user, make_raw_file
):
    owner = _handled(db_session, make_user, "ada", "Ada")
    guest = _handled(db_session, make_user, "lin", "Lin")

    # Lin publishes two spectra of their own.
    lab_client.set_current_user(guest)
    theirs = [
        _published_spectrum(lab_client, make_raw_file(guest), title=f"Lin {i}") for i in range(2)
    ]

    # Ada builds a folder out of one of her own plus both of Lin's.
    lab_client.set_current_user(owner)
    mine = _published_spectrum(lab_client, make_raw_file(owner), title="Ada 1")
    dataset = _dataset(
        lab_client, "Shared", [mine["id"], theirs[0]["id"], theirs[1]["id"]]
    )

    rows = _contributors(lab_client, dataset["id"])

    assert rows["ada"]["spectra"] == 1
    assert rows["ada"]["is_owner"] is True
    assert rows["lin"]["spectra"] == 2
    assert rows["lin"]["is_owner"] is False
    assert rows["lin"]["display_name"] == "Lin"
    # Most work first, so Lin outranks the owner here.
    assert [r["handle"] for r in lab_client.get(
        f"/analysis/datasets/{dataset['id']}/contributors"
    ).json()] == ["lin", "ada"]


def test_a_finding_credits_its_author_and_co_authors(
    lab_client, db_session, make_user, make_raw_file
):
    owner = _handled(db_session, make_user, "ada", "Ada")
    coauthor = _handled(db_session, make_user, "lin", "Lin")
    lab_client.set_current_user(owner)
    member = _published_spectrum(lab_client, make_raw_file(owner))
    dataset = _dataset(lab_client, "Write-up", [member["id"]])

    created = lab_client.post(
        "/v1/findings",
        json={
            "title": "Ageing at 90% RH",
            "dataset_id": dataset["id"],
            "co_author_handles": ["lin"],
        },
    )
    assert created.status_code == 201, created.text

    rows = _contributors(lab_client, dataset["id"])

    assert rows["ada"]["findings"] == 1
    assert rows["lin"]["findings"] == 1
    # Credit for writing is not credit for depositing data.
    assert rows["lin"]["spectra"] == 0


def test_a_finding_reaches_the_project_through_a_member_spectrum(
    lab_client, db_session, make_user, make_raw_file
):
    """No `dataset_id` on the Finding — the only link is that it cites a
    spectrum which happens to sit in the folder."""
    owner = _handled(db_session, make_user, "ada", "Ada")
    author = _handled(db_session, make_user, "lin", "Lin")

    lab_client.set_current_user(owner)
    member = _published_spectrum(lab_client, make_raw_file(owner))
    dataset = _dataset(lab_client, "Cited", [member["id"]])
    # Published, so Lin can read the folder at all.
    assert lab_client.post(
        f"/analysis/datasets/{dataset['id']}/publish", json={"license_id": "CC-BY-4.0"}
    ).status_code == 200

    lab_client.set_current_user(author)
    finding = lab_client.post("/v1/findings", json={"title": "Reuse of Ada's data"})
    assert finding.status_code == 201, finding.text
    attached = lab_client.post(
        f"/v1/findings/{finding.json()['id']}/spectra",
        json={"spectrum_id": member["id"]},
    )
    assert attached.status_code == 201, attached.text

    lab_client.set_current_user(owner)
    rows = _contributors(lab_client, dataset["id"])

    # Lin's finding is still a draft and Ada does not own it, so Ada must not
    # see it counted.
    assert "lin" not in rows

    lab_client.set_current_user(author)
    assert _contributors(lab_client, dataset["id"])["lin"]["findings"] == 1


def test_a_non_owner_is_not_told_about_the_owners_drafts(
    lab_client, db_session, make_user, make_raw_file
):
    owner = _handled(db_session, make_user, "ada", "Ada")
    reader = _handled(db_session, make_user, "lin", "Lin")

    lab_client.set_current_user(owner)
    published = _published_spectrum(lab_client, make_raw_file(owner), title="Public")
    dataset = _dataset(lab_client, "Mixed", [published["id"]])
    assert lab_client.post(
        f"/analysis/datasets/{dataset['id']}/publish", json={"license_id": "CC-BY-4.0"}
    ).status_code == 200

    # Both the publish and the add-member routes now refuse a draft in a
    # published folder (see `test_dataset_member_visibility.py`), so the row is
    # written straight through the model layer: this stands in for data created
    # before that guard existed, which the counts still have to handle.
    draft = _draft_spectrum(lab_client, make_raw_file(owner), title="Private")
    db_session.add(
        AnalysisDatasetSpectrum(
            dataset_id=dataset["id"], spectrum_id=draft["id"], position=99
        )
    )
    db_session.commit()

    assert _contributors(lab_client, dataset["id"])["ada"]["spectra"] == 2

    lab_client.set_current_user(reader)
    assert _contributors(lab_client, dataset["id"])["ada"]["spectra"] == 1


def test_a_draft_project_is_404_to_a_stranger(
    lab_client, db_session, make_user, make_raw_file
):
    """404 and not 403, matching every other dataset read — a stranger must
    not be able to tell "private" from "does not exist"."""
    owner = _handled(db_session, make_user, "ada", "Ada")
    stranger = _handled(db_session, make_user, "lin", "Lin")
    lab_client.set_current_user(owner)
    dataset = _dataset(lab_client, "Secret")

    lab_client.set_current_user(stranger)
    assert lab_client.get(
        f"/analysis/datasets/{dataset['id']}/contributors"
    ).status_code == 404
