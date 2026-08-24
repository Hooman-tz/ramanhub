"""The `/feed` discovery surface, plus votes and comments on Findings.

The vote tests here guard the partial-unique-index design in
`app.models.social`: a naive UNIQUE(spectrum_id, user_id) would not
constrain finding-votes at all, because every one of them has a NULL
spectrum_id and Postgres treats NULLs as distinct.
"""
from __future__ import annotations

from tests.test_findings import _finding, _publishable, _spectrum


def _publish_finding(client, make_raw_file, owner, title="A finding", **fields) -> dict:
    finding = _finding(client, title=title, **fields)
    spectrum = _spectrum(client, make_raw_file, owner)
    client.post(f"/findings/{finding['id']}/spectra", json={"spectrum_id": spectrum["id"]})
    resp = client.post(f"/findings/{finding['id']}/publish", json={"license_id": "CC-BY-4.0"})
    assert resp.status_code == 200, resp.text
    return resp.json()


# --------------------------------------------------------------------- feed


def test_feed_shows_published_findings_and_spectra(fclient, make_user, make_raw_file):
    owner = make_user()
    fclient.set_current_user(owner)
    _publish_finding(fclient, make_raw_file, owner)

    fclient.set_current_user(None)
    kinds = {item["kind"] for item in fclient.get("/feed").json()}

    assert kinds == {"finding", "spectrum"}


def test_feed_excludes_drafts(fclient, make_user, make_raw_file):
    owner = make_user()
    fclient.set_current_user(owner)
    draft = _finding(fclient, title="Unpublished")
    _spectrum(fclient, make_raw_file, owner, publish=False)

    fclient.set_current_user(None)
    ids = [item["id"] for item in fclient.get("/feed").json()]

    assert draft["id"] not in ids
    assert ids == []


def test_feed_includes_zero_vote_items(fclient, make_user, make_raw_file):
    """A discovery feed that only showed already-popular things would never
    surface anything new."""
    owner = make_user()
    fclient.set_current_user(owner)
    _publish_finding(fclient, make_raw_file, owner)

    fclient.set_current_user(None)
    items = fclient.get("/feed").json()

    assert items
    assert all(item["vote_count"] == 0 for item in items)


def test_feed_can_filter_to_one_kind(fclient, make_user, make_raw_file):
    owner = make_user()
    fclient.set_current_user(owner)
    _publish_finding(fclient, make_raw_file, owner)

    fclient.set_current_user(None)
    findings_only = fclient.get("/feed", params={"kind": "findings"}).json()
    spectra_only = fclient.get("/feed", params={"kind": "spectra"}).json()

    assert {i["kind"] for i in findings_only} == {"finding"}
    assert {i["kind"] for i in spectra_only} == {"spectrum"}


def test_feed_cards_carry_author_attribution(fclient, make_user, make_raw_file):
    owner = make_user()
    owner.handle = "ada"
    owner.orcid_id = "0000-0002-1825-0097"
    fclient.set_current_user(owner)
    _publish_finding(fclient, make_raw_file, owner)

    fclient.set_current_user(None)
    item = next(i for i in fclient.get("/feed").json() if i["kind"] == "finding")

    assert item["author"]["handle"] == "ada"
    assert item["author"]["orcid_id"] == "0000-0002-1825-0097"


def test_feed_reports_member_spectrum_count(fclient, make_user, make_raw_file):
    owner = make_user()
    fclient.set_current_user(owner)
    finding = _publishable(fclient, make_raw_file, owner, n=3)
    fclient.post(f"/findings/{finding['id']}/publish", json={"license_id": "CC-BY-4.0"})

    fclient.set_current_user(None)
    item = next(i for i in fclient.get("/feed").json() if i["kind"] == "finding")

    assert item["spectrum_count"] == 3


def test_feed_summary_is_truncated_on_a_word_boundary(fclient, make_user, make_raw_file):
    owner = make_user()
    fclient.set_current_user(owner)
    finding = _finding(fclient, abstract_md="wordy " * 200)
    spectrum = _spectrum(fclient, make_raw_file, owner)
    fclient.post(f"/findings/{finding['id']}/spectra", json={"spectrum_id": spectrum["id"]})
    fclient.post(f"/findings/{finding['id']}/publish", json={"license_id": "CC-BY-4.0"})

    fclient.set_current_user(None)
    item = next(i for i in fclient.get("/feed").json() if i["kind"] == "finding")

    assert item["summary"].endswith("...")
    assert len(item["summary"]) <= 284


def test_feed_filters_by_tag(fclient, make_user, make_raw_file):
    owner = make_user()
    fclient.set_current_user(owner)
    tagged = _publish_finding(fclient, make_raw_file, owner, title="Tagged", tags=["cellulose"])
    _publish_finding(fclient, make_raw_file, owner, title="Untagged")

    fclient.set_current_user(None)
    items = fclient.get("/feed", params={"tag": "cellulose"}).json()

    assert [i["id"] for i in items] == [tagged["id"]]


def test_feed_filters_by_author_handle(fclient, make_user, make_raw_file):
    ada, grace = make_user(), make_user()
    ada.handle = "ada"
    grace.handle = "grace"

    fclient.set_current_user(ada)
    mine = _publish_finding(fclient, make_raw_file, ada, title="Ada's")
    fclient.set_current_user(grace)
    _publish_finding(fclient, make_raw_file, grace, title="Grace's")

    fclient.set_current_user(None)
    items = fclient.get("/feed", params={"kind": "findings", "author": "ada"}).json()

    assert [i["id"] for i in items] == [mine["id"]]


def test_feed_filters_by_trust_tier(fclient, make_user, make_raw_file):
    owner = make_user()
    fclient.set_current_user(owner)
    verified = _finding(fclient, title="With DOI")
    spectrum = _spectrum(fclient, make_raw_file, owner)
    fclient.post(f"/findings/{verified['id']}/spectra", json={"spectrum_id": spectrum["id"]})
    fclient.patch(f"/findings/{verified['id']}", json={"doi": "10.1021/example"})
    fclient.post(f"/findings/{verified['id']}/publish", json={"license_id": "CC-BY-4.0"})
    _publish_finding(fclient, make_raw_file, owner, title="No DOI")

    fclient.set_current_user(None)
    items = fclient.get(
        "/feed", params={"kind": "findings", "trust_tier": "doi_verified"}
    ).json()

    assert [i["id"] for i in items] == [verified["id"]]


def test_feed_respects_limit(fclient, make_user, make_raw_file):
    owner = make_user()
    fclient.set_current_user(owner)
    for i in range(3):
        _publish_finding(fclient, make_raw_file, owner, title=f"F{i}")

    fclient.set_current_user(None)
    assert len(fclient.get("/feed", params={"limit": 2}).json()) == 2


# ------------------------------------------------------- votes on findings


def test_vote_on_a_finding_toggles(fclient, make_user, make_raw_file):
    owner, voter = make_user(), make_user()
    fclient.set_current_user(owner)
    finding = _publish_finding(fclient, make_raw_file, owner)

    fclient.set_current_user(voter)
    first = fclient.post(f"/findings/{finding['id']}/votes").json()
    assert first == {"voted": True, "count": 1}

    second = fclient.post(f"/findings/{finding['id']}/votes").json()
    assert second == {"voted": False, "count": 0}


def test_voting_twice_cannot_double_count(fclient, make_user, make_raw_file):
    """Guards the partial unique index: a plain UNIQUE(spectrum_id,
    user_id) would not constrain finding-votes at all, since every one has
    a NULL spectrum_id."""
    owner = make_user()
    fclient.set_current_user(owner)
    finding = _publish_finding(fclient, make_raw_file, owner)

    for voter in (make_user(), make_user(), make_user()):
        fclient.set_current_user(voter)
        fclient.post(f"/findings/{finding['id']}/votes")
        # An immediate repeat toggles off, then on again — the count must
        # never exceed one per user.
        fclient.post(f"/findings/{finding['id']}/votes")
        fclient.post(f"/findings/{finding['id']}/votes")

    assert fclient.get(f"/findings/{finding['id']}/votes").json()["count"] == 3


def test_finding_votes_do_not_leak_into_spectrum_counts(fclient, make_user, make_raw_file):
    """The shared-table risk: a finding-vote must never be counted in a
    spectrum's tally."""
    owner, voter = make_user(), make_user()
    fclient.set_current_user(owner)
    finding = _publish_finding(fclient, make_raw_file, owner)
    spectrum_id = fclient.get(f"/findings/{finding['id']}").json()["spectra"][0]["spectrum_id"]

    fclient.set_current_user(voter)
    fclient.post(f"/findings/{finding['id']}/votes")

    assert fclient.get(f"/findings/{finding['id']}/votes").json()["count"] == 1
    assert fclient.get(f"/spectra/{spectrum_id}/votes").json()["count"] == 0


def test_cannot_vote_on_a_draft_finding(fclient, make_user):
    owner, other = make_user(), make_user()
    fclient.set_current_user(owner)
    finding = _finding(fclient)

    fclient.set_current_user(other)
    assert fclient.post(f"/findings/{finding['id']}/votes").status_code == 404


# ---------------------------------------------------- comments on findings


def test_comment_on_a_finding(fclient, make_user, make_raw_file):
    owner, reader = make_user(), make_user()
    reader.handle = "grace"
    fclient.set_current_user(owner)
    finding = _publish_finding(fclient, make_raw_file, owner)

    fclient.set_current_user(reader)
    resp = fclient.post(
        f"/findings/{finding['id']}/comments", json={"body": "Nice baseline choice."}
    )

    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["finding_id"] == finding["id"]
    assert body["spectrum_id"] is None
    assert body["author_handle"] == "grace"


def test_replies_are_threaded_one_level(fclient, make_user, make_raw_file):
    owner, reader = make_user(), make_user()
    fclient.set_current_user(owner)
    finding = _publish_finding(fclient, make_raw_file, owner)

    fclient.set_current_user(reader)
    parent = fclient.post(f"/findings/{finding['id']}/comments", json={"body": "Question?"}).json()
    reply = fclient.post(
        f"/findings/{finding['id']}/comments", json={"body": "Answer.", "parent_id": parent["id"]}
    )

    assert reply.status_code == 201
    assert reply.json()["parent_id"] == parent["id"]

    # A reply to a reply is refused — deep nesting makes threads unreadable.
    nested = fclient.post(
        f"/findings/{finding['id']}/comments",
        json={"body": "Too deep.", "parent_id": reply.json()["id"]},
    )
    assert nested.status_code == 422


def test_reply_cannot_cross_targets(fclient, make_user, make_raw_file):
    """The security-relevant half of parent validation: without the
    same-target check, a reply could hang off a comment on a private
    spectrum and be read back through a public Finding."""
    owner, reader = make_user(), make_user()
    fclient.set_current_user(owner)
    finding = _publish_finding(fclient, make_raw_file, owner)
    spectrum_id = fclient.get(f"/findings/{finding['id']}").json()["spectra"][0]["spectrum_id"]

    fclient.set_current_user(reader)
    on_spectrum = fclient.post(
        f"/spectra/{spectrum_id}/comments", json={"body": "On the spectrum"}
    ).json()

    crossed = fclient.post(
        f"/findings/{finding['id']}/comments",
        json={"body": "Crossed over", "parent_id": on_spectrum["id"]},
    )

    assert crossed.status_code == 422


def test_comments_on_a_draft_finding_are_blocked(fclient, make_user):
    owner, other = make_user(), make_user()
    fclient.set_current_user(owner)
    finding = _finding(fclient)

    fclient.set_current_user(other)
    assert fclient.post(f"/findings/{finding['id']}/comments", json={"body": "hi"}).status_code == 404
    assert fclient.get(f"/findings/{finding['id']}/comments").status_code == 404


def test_comment_counts_appear_on_the_finding(fclient, make_user, make_raw_file):
    owner, reader = make_user(), make_user()
    fclient.set_current_user(owner)
    finding = _publish_finding(fclient, make_raw_file, owner)

    fclient.set_current_user(reader)
    fclient.post(f"/findings/{finding['id']}/comments", json={"body": "one"})
    fclient.post(f"/findings/{finding['id']}/comments", json={"body": "two"})

    assert fclient.get(f"/findings/{finding['id']}").json()["comment_count"] == 2
