"""Findings: threads, entries, member spectra, publishing, and the feed.

The draft-visibility block near the bottom is the highest-stakes part. A
Finding's abstract can describe unpublished results and its entries name
private spectra, so a leak here is the same class of failure the
architecture doc calls "the one bug that would matter most".
"""
from __future__ import annotations


def _spectrum(client, make_raw_file, owner, publish=True) -> dict:
    raw_file = make_raw_file(owner)
    resp = client.post("/spectra", json={"raw_file_id": str(raw_file.id)})
    assert resp.status_code == 201, resp.text
    body = resp.json()
    if publish:
        pub = client.post(f"/spectra/{body['id']}/publish", json={"license_id": "CC-BY-4.0"})
        assert pub.status_code == 200, pub.text
        body = pub.json()
    return body


def _finding(client, title="A finding", **fields) -> dict:
    resp = client.post("/findings", json={"title": title, **fields})
    assert resp.status_code == 201, resp.text
    return resp.json()


def _publishable(client, make_raw_file, owner, n=1) -> dict:
    """A finding with n published spectra attached — ready to publish."""
    finding = _finding(client)
    for _ in range(n):
        spectrum = _spectrum(client, make_raw_file, owner)
        resp = client.post(
            f"/findings/{finding['id']}/spectra", json={"spectrum_id": spectrum["id"]}
        )
        assert resp.status_code == 201, resp.text
        finding = resp.json()
    return finding


# ------------------------------------------------------------------- basics


def test_create_assigns_an_accession_and_draft_state(fclient, make_user):
    fclient.set_current_user(make_user())
    finding = _finding(fclient)

    assert finding["accession"].startswith("RH-F-")
    assert finding["state"] == "draft"


def test_finding_and_spectrum_accessions_do_not_collide(fclient, make_user, make_raw_file):
    owner = make_user()
    fclient.set_current_user(owner)
    spectrum = _spectrum(fclient, make_raw_file, owner)
    finding = _finding(fclient)

    assert spectrum["accession"].startswith("RH-S-")
    assert finding["accession"].startswith("RH-F-")
    assert spectrum["accession"] != finding["accession"]


def test_owner_identity_is_exposed_for_attribution(fclient, make_user):
    user = make_user()
    user.handle = "ada"
    user.orcid_id = "0000-0002-1825-0097"
    fclient.set_current_user(user)

    finding = _finding(fclient)

    assert finding["owner_handle"] == "ada"
    assert finding["owner_orcid"] == "0000-0002-1825-0097"


def test_update_edits_title_abstract_and_tags(fclient, make_user):
    fclient.set_current_user(make_user())
    finding = _finding(fclient)

    resp = fclient.patch(
        f"/findings/{finding['id']}",
        json={"title": "Better title", "abstract_md": "# Results", "tags": ["Cellulose", "785nm"]},
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["title"] == "Better title"
    assert body["abstract_md"] == "# Results"
    assert body["tags"] == ["cellulose", "785nm"]


def test_tags_are_deduplicated_and_capped(fclient, make_user):
    fclient.set_current_user(make_user())
    finding = _finding(fclient)

    resp = fclient.patch(
        f"/findings/{finding['id']}",
        json={"tags": ["a", "A", " a ", *[f"t{i}" for i in range(30)]]},
    )

    tags = resp.json()["tags"]
    assert tags.count("a") == 1
    assert len(tags) <= 10


def test_list_returns_only_my_findings(fclient, make_user):
    mine_owner, other_owner = make_user(), make_user()
    fclient.set_current_user(other_owner)
    _finding(fclient, title="Theirs")

    fclient.set_current_user(mine_owner)
    _finding(fclient, title="Mine")

    titles = [f["title"] for f in fclient.get("/findings").json()]
    assert titles == ["Mine"]


# ------------------------------------------------------------------ entries


def test_entries_append_in_order(fclient, make_user):
    fclient.set_current_user(make_user())
    finding = _finding(fclient)

    for text in ("first", "second", "third"):
        resp = fclient.post(
            f"/findings/{finding['id']}/entries", json={"kind": "note", "body_md": text}
        )
        assert resp.status_code == 201, resp.text

    entries = resp.json()["entries"]
    assert [e["body_md"] for e in entries] == ["first", "second", "third"]
    assert [e["position"] for e in entries] == [0, 1, 2]


def test_analysis_entry_stores_parameters_not_an_image(fclient, make_user):
    """The reproducibility bet: a figure is recomputed from recorded
    parameters, so it can't drift from the data it claims to show."""
    fclient.set_current_user(make_user())
    finding = _finding(fclient)

    config = {"spectrum_ids": ["a", "b"], "n_components": 3, "mean_center": True}
    resp = fclient.post(
        f"/findings/{finding['id']}/entries", json={"kind": "pca", "config": config}
    )

    assert resp.status_code == 201, resp.text
    assert resp.json()["entries"][0]["config"] == config


def test_entries_can_be_reordered(fclient, make_user):
    fclient.set_current_user(make_user())
    finding = _finding(fclient)
    for text in ("a", "b", "c"):
        resp = fclient.post(
            f"/findings/{finding['id']}/entries", json={"kind": "note", "body_md": text}
        )
    ids = [e["id"] for e in resp.json()["entries"]]

    resp = fclient.post(
        f"/findings/{finding['id']}/entries/reorder",
        json={"entry_ids": [ids[2], ids[0], ids[1]]},
    )

    assert resp.status_code == 200, resp.text
    assert [e["body_md"] for e in resp.json()["entries"]] == ["c", "a", "b"]


def test_partial_reorder_is_rejected(fclient, make_user):
    """A partial list would leave gaps or duplicate positions."""
    fclient.set_current_user(make_user())
    finding = _finding(fclient)
    for text in ("a", "b"):
        resp = fclient.post(
            f"/findings/{finding['id']}/entries", json={"kind": "note", "body_md": text}
        )
    ids = [e["id"] for e in resp.json()["entries"]]

    resp = fclient.post(f"/findings/{finding['id']}/entries/reorder", json={"entry_ids": [ids[0]]})
    assert resp.status_code == 422


def test_entry_can_be_edited_and_deleted(fclient, make_user):
    fclient.set_current_user(make_user())
    finding = _finding(fclient)
    resp = fclient.post(
        f"/findings/{finding['id']}/entries", json={"kind": "note", "body_md": "draft text"}
    )
    entry_id = resp.json()["entries"][0]["id"]

    resp = fclient.patch(
        f"/findings/{finding['id']}/entries/{entry_id}", json={"body_md": "final text"}
    )
    assert resp.json()["entries"][0]["body_md"] == "final text"

    resp = fclient.delete(f"/findings/{finding['id']}/entries/{entry_id}")
    assert resp.json()["entries"] == []


def test_cannot_touch_entries_of_someone_elses_finding(fclient, make_user):
    owner, attacker = make_user(), make_user()
    fclient.set_current_user(owner)
    finding = _finding(fclient)

    fclient.set_current_user(attacker)
    resp = fclient.post(
        f"/findings/{finding['id']}/entries", json={"kind": "note", "body_md": "hi"}
    )
    assert resp.status_code == 404


# ------------------------------------------------------------ member spectra


def test_attach_and_detach_spectra(fclient, make_user, make_raw_file):
    owner = make_user()
    fclient.set_current_user(owner)
    finding = _publishable(fclient, make_raw_file, owner, n=2)

    assert len(finding["spectra"]) == 2
    assert [s["position"] for s in finding["spectra"]] == [0, 1]

    target = finding["spectra"][0]["spectrum_id"]
    resp = fclient.delete(f"/findings/{finding['id']}/spectra/{target}")
    assert resp.status_code == 200
    assert len(resp.json()["spectra"]) == 1


def test_attaching_the_same_spectrum_twice_conflicts(fclient, make_user, make_raw_file):
    owner = make_user()
    fclient.set_current_user(owner)
    finding = _finding(fclient)
    spectrum = _spectrum(fclient, make_raw_file, owner)

    first = fclient.post(
        f"/findings/{finding['id']}/spectra", json={"spectrum_id": spectrum["id"]}
    )
    second = fclient.post(
        f"/findings/{finding['id']}/spectra", json={"spectrum_id": spectrum["id"]}
    )

    assert first.status_code == 201
    assert second.status_code == 409


def test_can_attach_someone_elses_published_spectrum(fclient, make_user, make_raw_file):
    """The commons working as intended: comparing your data against a
    published reference is the point."""
    stranger, author = make_user(), make_user()
    fclient.set_current_user(stranger)
    reference = _spectrum(fclient, make_raw_file, stranger)

    fclient.set_current_user(author)
    finding = _finding(fclient)
    resp = fclient.post(
        f"/findings/{finding['id']}/spectra", json={"spectrum_id": reference["id"]}
    )

    assert resp.status_code == 201


def test_cannot_attach_someone_elses_draft_spectrum(fclient, make_user, make_raw_file):
    stranger, attacker = make_user(), make_user()
    fclient.set_current_user(stranger)
    private = _spectrum(fclient, make_raw_file, stranger, publish=False)

    fclient.set_current_user(attacker)
    finding = _finding(fclient)
    resp = fclient.post(
        f"/findings/{finding['id']}/spectra", json={"spectrum_id": private["id"]}
    )

    assert resp.status_code == 404


def test_custom_label_overrides_the_spectrum_title(fclient, make_user, make_raw_file):
    owner = make_user()
    fclient.set_current_user(owner)
    finding = _finding(fclient)
    spectrum = _spectrum(fclient, make_raw_file, owner)

    resp = fclient.post(
        f"/findings/{finding['id']}/spectra",
        json={"spectrum_id": spectrum["id"], "label": "Treated 24h"},
    )

    assert resp.json()["spectra"][0]["label"] == "Treated 24h"


# --------------------------------------------------------------- publishing


def test_publish_requires_a_license(fclient, make_user, make_raw_file):
    owner = make_user()
    fclient.set_current_user(owner)
    finding = _publishable(fclient, make_raw_file, owner)

    resp = fclient.post(f"/findings/{finding['id']}/publish", json={"license_id": ""})
    assert resp.status_code == 422


def test_publish_requires_at_least_one_spectrum(fclient, make_user):
    fclient.set_current_user(make_user())
    finding = _finding(fclient)

    resp = fclient.post(f"/findings/{finding['id']}/publish", json={"license_id": "CC-BY-4.0"})

    assert resp.status_code == 422
    assert "at least one spectrum" in resp.json()["detail"]


def test_publish_is_blocked_while_a_member_spectrum_is_private(
    fclient, make_user, make_raw_file
):
    """A public write-up whose figures point at private data renders as a
    wall of 404s for every reader but the author."""
    owner = make_user()
    fclient.set_current_user(owner)
    finding = _finding(fclient)
    draft = _spectrum(fclient, make_raw_file, owner, publish=False)
    fclient.post(f"/findings/{finding['id']}/spectra", json={"spectrum_id": draft["id"]})

    resp = fclient.post(f"/findings/{finding['id']}/publish", json={"license_id": "CC-BY-4.0"})

    assert resp.status_code == 422
    assert draft["accession"] in resp.json()["detail"]


def test_publish_succeeds_once_everything_is_public(fclient, make_user, make_raw_file):
    owner = make_user()
    fclient.set_current_user(owner)
    finding = _publishable(fclient, make_raw_file, owner)

    resp = fclient.post(f"/findings/{finding['id']}/publish", json={"license_id": "CC-BY-4.0"})

    assert resp.status_code == 200, resp.text
    assert resp.json()["state"] == "published"
    assert resp.json()["published_at"] is not None


def test_published_findings_cannot_be_deleted(fclient, make_user, make_raw_file):
    """Others may already cite it."""
    owner = make_user()
    fclient.set_current_user(owner)
    finding = _publishable(fclient, make_raw_file, owner)
    fclient.post(f"/findings/{finding['id']}/publish", json={"license_id": "CC-BY-4.0"})

    assert fclient.delete(f"/findings/{finding['id']}").status_code == 409


def test_draft_findings_can_be_deleted(fclient, make_user):
    fclient.set_current_user(make_user())
    finding = _finding(fclient)

    assert fclient.delete(f"/findings/{finding['id']}").status_code == 204
    assert fclient.get(f"/findings/{finding['id']}").status_code == 404


# ----------------------------------------------------------- access control


def test_draft_findings_are_invisible_to_everyone_else(fclient, make_user):
    """Highest-stakes case: an abstract can describe unpublished results."""
    owner, other = make_user(), make_user()
    fclient.set_current_user(owner)
    finding = _finding(fclient, title="Secret result")

    for viewer in (other, None):
        fclient.set_current_user(viewer)
        assert fclient.get(f"/findings/{finding['id']}").status_code == 404

    fclient.set_current_user(owner)
    assert fclient.get(f"/findings/{finding['id']}").status_code == 200


def test_published_findings_are_readable_anonymously(fclient, make_user, make_raw_file):
    owner = make_user()
    fclient.set_current_user(owner)
    finding = _publishable(fclient, make_raw_file, owner)
    fclient.post(f"/findings/{finding['id']}/publish", json={"license_id": "CC-BY-4.0"})

    fclient.set_current_user(None)
    assert fclient.get(f"/findings/{finding['id']}").status_code == 200


def test_others_cannot_edit_or_publish_my_finding(fclient, make_user):
    owner, attacker = make_user(), make_user()
    fclient.set_current_user(owner)
    finding = _finding(fclient)

    fclient.set_current_user(attacker)
    assert fclient.patch(f"/findings/{finding['id']}", json={"title": "hijacked"}).status_code == 404
    assert (
        fclient.post(f"/findings/{finding['id']}/publish", json={"license_id": "CC-BY-4.0"}).status_code
        == 404
    )
    assert fclient.delete(f"/findings/{finding['id']}").status_code == 404
