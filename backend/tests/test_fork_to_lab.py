"""Tests for the bulk "fork it to my lab" paths and the lineage breadcrumb.

`POST /spectra/{id}/fork` (covered in test_fork.py) copies one spectrum.
These cover the two callers that copy a whole working set in one request —
`POST /analysis/datasets/{id}/fork` and `POST /v1/findings/{id}/fork-data` —
plus `GET /spectra/{id}/lineage`, which is what lets a reader see that the
thing they're looking at is a copy and find the original.
"""

from __future__ import annotations

import uuid


def _published_spectrum(lab_client, raw_file, title="Source") -> dict:
    spectrum = lab_client.post(
        "/spectra", json={"raw_file_id": str(raw_file.id), "title": title}
    ).json()
    published = lab_client.post(
        f"/spectra/{spectrum['id']}/publish", json={"license_id": "CC-BY-4.0"}
    )
    assert published.status_code == 200, published.text
    return published.json()


def _published_dataset(lab_client, make_raw_file, owner, titles) -> dict:
    members = [
        _published_spectrum(lab_client, make_raw_file(owner), title=title) for title in titles
    ]
    created = lab_client.post(
        "/analysis/datasets",
        json={"name": "Degradation series", "spectrum_ids": [m["id"] for m in members]},
    )
    assert created.status_code == 201, created.text
    dataset = created.json()
    published = lab_client.post(
        f"/analysis/datasets/{dataset['id']}/publish", json={"license_id": "CC-BY-4.0"}
    )
    assert published.status_code == 200, published.text
    return published.json()


# --- dataset fork ---------------------------------------------------------


def test_forking_a_published_dataset_copies_every_member(lab_client, make_user, make_raw_file):
    owner = make_user()
    lab_client.set_current_user(owner)
    source = _published_dataset(lab_client, make_raw_file, owner, ["Control", "24h UV"])

    forker = make_user()
    lab_client.set_current_user(forker)
    resp = lab_client.post(f"/analysis/datasets/{source['id']}/fork")

    assert resp.status_code == 201, resp.text
    fork = resp.json()
    assert fork["state"] == "draft"
    assert fork["accession"] is None
    assert fork["parent_dataset_id"] == source["id"]
    assert fork["owner_id"] == str(forker.id)
    assert len(fork["spectra"]) == 2
    # Order is preserved, and every member is a fresh draft copy.
    assert [s["title"] for s in fork["spectra"]] == ["Control (fork)", "24h UV (fork)"]
    assert {s["state"] for s in fork["spectra"]} == {"draft"}
    source_ids = {s["id"] for s in source["spectra"]}
    assert not source_ids & {s["id"] for s in fork["spectra"]}


def test_dataset_fork_sets_parent_on_each_spectrum(lab_client, make_user, make_raw_file):
    owner = make_user()
    lab_client.set_current_user(owner)
    source = _published_dataset(lab_client, make_raw_file, owner, ["A", "B"])

    forker = make_user()
    lab_client.set_current_user(forker)
    fork = lab_client.post(f"/analysis/datasets/{source['id']}/fork").json()

    parents = {s["parent_spectrum_id"] for s in fork["spectra"]}
    assert parents == {s["id"] for s in source["spectra"]}


def test_forking_the_same_dataset_twice_suffixes_the_name(lab_client, make_user, make_raw_file):
    """The unique (owner, name) constraint must not turn a second fork into
    the user's problem to solve."""
    owner = make_user()
    lab_client.set_current_user(owner)
    source = _published_dataset(lab_client, make_raw_file, owner, ["A"])

    forker = make_user()
    lab_client.set_current_user(forker)
    first = lab_client.post(f"/analysis/datasets/{source['id']}/fork")
    second = lab_client.post(f"/analysis/datasets/{source['id']}/fork")

    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    assert first.json()["name"] == "Degradation series (fork)"
    assert second.json()["name"] == "Degradation series (fork 2)"


def test_cannot_fork_someone_elses_draft_dataset(lab_client, make_user, make_raw_file):
    owner = make_user()
    lab_client.set_current_user(owner)
    member = _published_spectrum(lab_client, make_raw_file(owner))
    draft = lab_client.post(
        "/analysis/datasets", json={"name": "Private", "spectrum_ids": [member["id"]]}
    ).json()

    stranger = make_user()
    lab_client.set_current_user(stranger)
    assert lab_client.post(f"/analysis/datasets/{draft['id']}/fork").status_code == 404


def test_fork_of_unknown_dataset_is_404(lab_client, make_user):
    lab_client.set_current_user(make_user())
    assert lab_client.post(f"/analysis/datasets/{uuid.uuid4()}/fork").status_code == 404


# --- finding fork-data ----------------------------------------------------


def _finding_with_spectra(lab_client, spectra) -> dict:
    finding = lab_client.post(
        "/v1/findings", json={"title": "Photodegradation of PET", "abstract_md": "Body"}
    )
    assert finding.status_code == 201, finding.text
    finding = finding.json()
    for spectrum in spectra:
        attached = lab_client.post(
            f"/v1/findings/{finding['id']}/spectra", json={"spectrum_id": spectrum["id"]}
        )
        assert attached.status_code == 201, attached.text
    return attached.json()


def test_fork_data_bundles_a_posts_spectra_into_one_new_dataset(
    lab_client, make_user, make_raw_file
):
    owner = make_user()
    lab_client.set_current_user(owner)
    members = [
        _published_spectrum(lab_client, make_raw_file(owner), title=t)
        for t in ("Control", "Treated")
    ]
    finding = _finding_with_spectra(lab_client, members)
    published = lab_client.post(
        f"/v1/findings/{finding['id']}/publish", json={"license_id": "CC-BY-4.0"}
    )
    assert published.status_code == 200, published.text

    reader = make_user()
    lab_client.set_current_user(reader)
    resp = lab_client.post(f"/v1/findings/{finding['id']}/fork-data")

    assert resp.status_code == 201, resp.text
    dataset = resp.json()
    # Named after the post, owned by the reader, holding their own copies.
    assert dataset["name"].startswith("Photodegradation of PET")
    assert dataset["owner_id"] == str(reader.id)
    assert dataset["state"] == "draft"
    assert len(dataset["spectra"]) == 2
    assert {s["state"] for s in dataset["spectra"]} == {"draft"}


def test_fork_data_works_on_a_post_that_names_no_dataset(lab_client, make_user, make_raw_file):
    """Posts written before datasets became publishable attach loose spectra;
    their readers must still be able to take the data."""
    owner = make_user()
    lab_client.set_current_user(owner)
    member = _published_spectrum(lab_client, make_raw_file(owner))
    finding = _finding_with_spectra(lab_client, [member])
    lab_client.post(f"/v1/findings/{finding['id']}/publish", json={"license_id": "CC-BY-4.0"})

    assert finding["dataset_id"] is None

    reader = make_user()
    lab_client.set_current_user(reader)
    resp = lab_client.post(f"/v1/findings/{finding['id']}/fork-data")
    assert resp.status_code == 201, resp.text
    assert len(resp.json()["spectra"]) == 1


def test_fork_data_on_a_post_with_no_spectra_is_422(lab_client, make_user):
    owner = make_user()
    lab_client.set_current_user(owner)
    finding = lab_client.post("/v1/findings", json={"title": "Empty post"}).json()

    resp = lab_client.post(f"/v1/findings/{finding['id']}/fork-data")
    assert resp.status_code == 422
    assert "no attached spectra" in resp.json()["detail"]


def test_cannot_fork_data_from_someone_elses_draft_post(lab_client, make_user, make_raw_file):
    owner = make_user()
    lab_client.set_current_user(owner)
    member = _published_spectrum(lab_client, make_raw_file(owner))
    finding = _finding_with_spectra(lab_client, [member])

    stranger = make_user()
    lab_client.set_current_user(stranger)
    assert lab_client.post(f"/v1/findings/{finding['id']}/fork-data").status_code == 404


def test_linking_a_dataset_to_a_post_surfaces_it_on_the_response(
    lab_client, make_user, make_raw_file
):
    owner = make_user()
    lab_client.set_current_user(owner)
    dataset = _published_dataset(lab_client, make_raw_file, owner, ["A"])
    finding = lab_client.post("/v1/findings", json={"title": "About that data"}).json()

    patched = lab_client.patch(f"/v1/findings/{finding['id']}", json={"dataset_id": dataset["id"]})

    assert patched.status_code == 200, patched.text
    body = patched.json()
    assert body["dataset_id"] == dataset["id"]
    assert body["dataset_accession"] == dataset["accession"]
    assert body["dataset_name"] == "Degradation series"
    assert body["dataset_state"] == "published"


def test_cannot_point_a_post_at_someone_elses_dataset(lab_client, make_user, make_raw_file):
    owner = make_user()
    lab_client.set_current_user(owner)
    dataset = _published_dataset(lab_client, make_raw_file, owner, ["A"])

    stranger = make_user()
    lab_client.set_current_user(stranger)
    finding = lab_client.post("/v1/findings", json={"title": "Not mine"}).json()
    resp = lab_client.patch(f"/v1/findings/{finding['id']}", json={"dataset_id": dataset["id"]})
    assert resp.status_code == 404


# --- lineage --------------------------------------------------------------


def test_lineage_is_empty_for_an_original_spectrum(lab_client, make_user, make_raw_file):
    owner = make_user()
    lab_client.set_current_user(owner)
    source = _published_spectrum(lab_client, make_raw_file(owner))

    resp = lab_client.get(f"/spectra/{source['id']}/lineage")
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"ancestors": [], "fork_count": 0, "truncated": False}


def test_lineage_returns_the_chain_root_first(lab_client, make_user, make_raw_file):
    owner = make_user()
    lab_client.set_current_user(owner)
    root = _published_spectrum(lab_client, make_raw_file(owner), title="Origin")

    first = make_user()
    lab_client.set_current_user(first)
    child = lab_client.post(f"/spectra/{root['id']}/fork").json()
    published_child = lab_client.post(
        f"/spectra/{child['id']}/publish", json={"license_id": "CC-BY-4.0"}
    )
    assert published_child.status_code == 200, published_child.text

    second = make_user()
    lab_client.set_current_user(second)
    grandchild = lab_client.post(f"/spectra/{child['id']}/fork").json()

    resp = lab_client.get(f"/spectra/{grandchild['id']}/lineage")
    assert resp.status_code == 200, resp.text
    ancestors = resp.json()["ancestors"]
    # Origin first, immediate parent last — the order a breadcrumb reads in.
    assert [a["id"] for a in ancestors] == [root["id"], child["id"]]
    assert ancestors[0]["title"] == "Origin"
    assert ancestors[0]["state"] == "published"


def test_lineage_counts_forks_of_this_spectrum(lab_client, make_user, make_raw_file):
    owner = make_user()
    lab_client.set_current_user(owner)
    source = _published_spectrum(lab_client, make_raw_file(owner))

    for _ in range(3):
        lab_client.set_current_user(make_user())
        assert lab_client.post(f"/spectra/{source['id']}/fork").status_code == 201

    lab_client.set_current_user(owner)
    assert lab_client.get(f"/spectra/{source['id']}/lineage").json()["fork_count"] == 3


def test_an_ancestor_pulled_back_to_draft_is_redacted_not_leaked(
    lab_client, make_user, make_raw_file, db_session
):
    """Forking requires a public source, but a source can be unpublished
    afterwards. The chain keeps its shape without leaking the title/owner to
    someone who could no longer read that spectrum directly."""
    from app.models.enums import SpectrumState
    from app.models.spectrum import Spectrum

    owner = make_user()
    lab_client.set_current_user(owner)
    source = _published_spectrum(lab_client, make_raw_file(owner), title="Secret method")

    forker = make_user()
    lab_client.set_current_user(forker)
    fork = lab_client.post(f"/spectra/{source['id']}/fork").json()
    # Published so the source's owner can read the fork at all; the redaction
    # under test is about the *ancestor*, not the spectrum being asked about.
    assert (
        lab_client.post(
            f"/spectra/{fork['id']}/publish", json={"license_id": "CC-BY-4.0"}
        ).status_code
        == 200
    )

    row = db_session.get(Spectrum, uuid.UUID(source["id"]))
    row.state = SpectrumState.draft
    db_session.add(row)
    db_session.commit()

    resp = lab_client.get(f"/spectra/{fork['id']}/lineage")
    assert resp.status_code == 200, resp.text
    (ancestor,) = resp.json()["ancestors"]
    assert ancestor["redacted"] is True
    assert ancestor["id"] is None
    assert ancestor["title"] is None
    assert ancestor["accession"] is None

    # The source's owner still sees their own spectrum in the chain.
    lab_client.set_current_user(owner)
    (visible,) = lab_client.get(f"/spectra/{fork['id']}/lineage").json()["ancestors"]
    assert visible["title"] == "Secret method"


def test_lineage_of_an_unreadable_spectrum_is_404(lab_client, make_user, make_raw_file):
    owner = make_user()
    lab_client.set_current_user(owner)
    draft = lab_client.post("/spectra", json={"raw_file_id": str(make_raw_file(owner).id)}).json()

    lab_client.set_current_user(make_user())
    assert lab_client.get(f"/spectra/{draft['id']}/lineage").status_code == 404
