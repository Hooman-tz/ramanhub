"""Follows, shares, and the public profile numbers derived from them.

The stakes here are higher than for votes, because these counts are shown
publicly on a profile AND feed into feed/search visibility. A count that can
be inflated is therefore not merely cosmetic — it buys reach. Several tests
below exist specifically to pin the anti-inflation rules.
"""
from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from app.auth.deps import get_current_user, get_current_user_optional
from app.db.session import get_db
from app.models.enums import FindingState, SpectrumState
from app.models.finding import Finding, FindingSpectrum
from app.profile_stats import compute_profile_stats
from app.routers import findings, follows, shares, spectra, users, votes


@pytest.fixture()
def graph_client(db_session):
    test_app = FastAPI()
    for module in (spectra, findings, votes, shares, users, follows):
        test_app.include_router(module.router)

    def _override_get_db():
        yield db_session

    current = {"user": None}

    def _override_get_current_user():
        if current["user"] is None:
            raise HTTPException(status_code=401, detail="Not authenticated")
        return current["user"]

    test_app.dependency_overrides[get_db] = _override_get_db
    test_app.dependency_overrides[get_current_user] = _override_get_current_user
    test_app.dependency_overrides[get_current_user_optional] = lambda: current["user"]

    client = TestClient(test_app)
    client.set_current_user = lambda user: current.__setitem__("user", user)
    return client


@pytest.fixture()
def make_handled_user(make_user, db_session):
    """`make_user` doesn't assign a handle, and every route here looks users
    up by one."""

    def _make(handle: str | None = None):
        user = make_user()
        user.handle = handle or f"u{uuid.uuid4().hex[:10]}"
        db_session.add(user)
        db_session.commit()
        db_session.refresh(user)
        return user

    return _make


def _publish_spectrum(client, raw_file, db_session):
    resp = client.post("/spectra", json={"raw_file_id": str(raw_file.id)})
    assert resp.status_code == 201, resp.text
    from app.models.spectrum import Spectrum

    spectrum = db_session.get(Spectrum, uuid.UUID(resp.json()["id"]))
    spectrum.state = SpectrumState.published
    db_session.add(spectrum)
    db_session.commit()
    return spectrum


# ---------------------------------------------------------------------------
# Follows
# ---------------------------------------------------------------------------


def test_follow_is_a_toggle(graph_client, make_handled_user):
    alice, bob = make_handled_user(), make_handled_user()
    graph_client.set_current_user(alice)

    first = graph_client.post(f"/users/{bob.handle}/follow").json()
    assert first == {"following": True, "follower_count": 1}

    second = graph_client.post(f"/users/{bob.handle}/follow").json()
    assert second == {"following": False, "follower_count": 0}


def test_following_is_asymmetric(graph_client, make_handled_user):
    """The whole point of choosing follow over a symmetric connect flow: no
    approval, and following someone does not make them follow you."""
    alice, bob = make_handled_user(), make_handled_user()
    graph_client.set_current_user(alice)
    graph_client.post(f"/users/{bob.handle}/follow")

    assert graph_client.get(f"/users/{bob.handle}/followers").json()[0]["handle"] == alice.handle
    assert graph_client.get(f"/users/{alice.handle}/followers").json() == []


def test_you_cannot_follow_yourself(graph_client, make_handled_user):
    """A public, comparable follower count you can raise by clicking your own
    profile is not a number that means anything."""
    alice = make_handled_user()
    graph_client.set_current_user(alice)

    assert graph_client.post(f"/users/{alice.handle}/follow").status_code == 400
    assert graph_client.get(f"/users/{alice.handle}/followers").json() == []


def test_a_concurrent_duplicate_follow_is_rejected_by_the_database(
    graph_client, make_handled_user, db_session
):
    """Two clients racing past the router's toggle must not both insert.

    The duplicate insert runs inside a SAVEPOINT — the same containment the
    router uses — so the constraint violation rolls back only this attempt
    and leaves the surrounding session usable. Committing it directly would
    poison the test transaction instead of demonstrating anything.
    """
    alice, bob = make_handled_user(), make_handled_user()
    graph_client.set_current_user(alice)
    graph_client.post(f"/users/{bob.handle}/follow")

    from app.models.graph import Follow

    with pytest.raises(IntegrityError), db_session.begin_nested():
        db_session.add(Follow(follower_id=alice.id, followee_id=bob.id))
        db_session.flush()

    assert graph_client.get(f"/users/{bob.handle}/follow").json()["follower_count"] == 1


def test_guests_have_no_profile_to_follow(graph_client, make_handled_user, make_user, db_session):
    alice = make_handled_user()
    guest = make_user()
    guest.is_guest = True
    guest.handle = "guesty"
    db_session.add(guest)
    db_session.commit()

    graph_client.set_current_user(alice)
    assert graph_client.post("/users/guesty/follow").status_code == 404


def test_follow_status_reports_the_viewers_own_state(graph_client, make_handled_user):
    alice, bob = make_handled_user(), make_handled_user()
    graph_client.set_current_user(alice)
    graph_client.post(f"/users/{bob.handle}/follow")

    assert graph_client.get(f"/users/{bob.handle}/follow").json()["following"] is True

    graph_client.set_current_user(None)
    anon = graph_client.get(f"/users/{bob.handle}/follow").json()
    assert anon["following"] is False
    assert anon["follower_count"] == 1


def test_unknown_handle_is_404(graph_client, make_handled_user):
    graph_client.set_current_user(make_handled_user())
    assert graph_client.post("/users/nobody-here/follow").status_code == 404


# ---------------------------------------------------------------------------
# Shares
# ---------------------------------------------------------------------------


def test_share_is_a_toggle(graph_client, make_handled_user, make_raw_file, db_session):
    owner = make_handled_user()
    graph_client.set_current_user(owner)
    spectrum = _publish_spectrum(graph_client, make_raw_file(owner), db_session)

    sharer = make_handled_user()
    graph_client.set_current_user(sharer)

    assert graph_client.post(f"/spectra/{spectrum.id}/shares").json() == {
        "shared": True,
        "count": 1,
    }
    assert graph_client.post(f"/spectra/{spectrum.id}/shares").json() == {
        "shared": False,
        "count": 0,
    }


def test_a_share_can_carry_a_comment(graph_client, make_handled_user, make_raw_file, db_session):
    owner = make_handled_user()
    graph_client.set_current_user(owner)
    spectrum = _publish_spectrum(graph_client, make_raw_file(owner), db_session)

    sharer = make_handled_user()
    graph_client.set_current_user(sharer)
    resp = graph_client.post(
        f"/spectra/{spectrum.id}/shares", json={"comment": "matches our 785 nm data"}
    )
    assert resp.status_code == 200

    from app.models.social import Share

    stored = db_session.query(Share).filter(Share.user_id == sharer.id).one()
    assert stored.comment == "matches our 785 nm data"


def test_a_draft_cannot_be_shared_into_other_peoples_feeds(
    graph_client, make_handled_user, make_raw_file
):
    """The access rule that matters most here: sharing is a broadcast, so
    anything a non-owner cannot read must not be shareable by them either."""
    owner = make_handled_user()
    graph_client.set_current_user(owner)
    resp = graph_client.post("/spectra", json={"raw_file_id": str(make_raw_file(owner).id)})
    draft_id = resp.json()["id"]

    graph_client.set_current_user(make_handled_user())
    assert graph_client.post(f"/spectra/{draft_id}/shares").status_code == 404


def test_share_status_is_per_viewer(graph_client, make_handled_user, make_raw_file, db_session):
    owner = make_handled_user()
    graph_client.set_current_user(owner)
    spectrum = _publish_spectrum(graph_client, make_raw_file(owner), db_session)

    sharer = make_handled_user()
    graph_client.set_current_user(sharer)
    graph_client.post(f"/spectra/{spectrum.id}/shares")

    mine = graph_client.get(f"/spectra/{spectrum.id}/shares").json()
    assert mine == {"count": 1, "shared_by_me": True}

    graph_client.set_current_user(owner)
    theirs = graph_client.get(f"/spectra/{spectrum.id}/shares").json()
    assert theirs == {"count": 1, "shared_by_me": False}


# ---------------------------------------------------------------------------
# Profile stats
# ---------------------------------------------------------------------------


def test_stats_start_at_zero(make_handled_user, db_session):
    stats = compute_profile_stats(make_handled_user().id, db_session)
    assert stats.model_dump() == dict.fromkeys(stats.model_dump(), 0)


def test_engagement_received_is_counted(
    graph_client, make_handled_user, make_raw_file, db_session
):
    owner = make_handled_user()
    graph_client.set_current_user(owner)
    spectrum = _publish_spectrum(graph_client, make_raw_file(owner), db_session)

    fan = make_handled_user()
    graph_client.set_current_user(fan)
    graph_client.post(f"/spectra/{spectrum.id}/votes")
    graph_client.post(f"/spectra/{spectrum.id}/shares")
    graph_client.post(f"/users/{owner.handle}/follow")

    stats = compute_profile_stats(owner.id, db_session)
    assert stats.votes_received == 1
    assert stats.shares_received == 1
    assert stats.followers == 1
    assert stats.spectra_published == 1


def test_drafts_never_appear_in_public_counts(
    graph_client, make_handled_user, make_raw_file, db_session
):
    """Publishing state is what the whole draft/published split protects.
    A count that includes drafts leaks how much unpublished work someone has."""
    owner = make_handled_user()
    graph_client.set_current_user(owner)
    graph_client.post("/spectra", json={"raw_file_id": str(make_raw_file(owner).id)})

    stats = compute_profile_stats(owner.id, db_session)
    assert stats.spectra_published == 0


def test_reuse_excludes_writing_about_your_own_data(
    graph_client, make_handled_user, make_raw_file, db_session
):
    """The anti-inflation rule for the number this design treats as the most
    meaningful one. Reuse must be earned by OTHER people using your data —
    a figure you can raise by writing about yourself measures writing."""
    owner = make_handled_user()
    graph_client.set_current_user(owner)
    spectrum = _publish_spectrum(graph_client, make_raw_file(owner), db_session)

    def _finding(author):
        finding = Finding(
            owner_id=author.id, title="F", state=FindingState.published
        )
        db_session.add(finding)
        db_session.commit()
        db_session.add(FindingSpectrum(finding_id=finding.id, spectrum_id=spectrum.id, position=0))
        db_session.commit()
        return finding

    _finding(owner)
    assert compute_profile_stats(owner.id, db_session).reuse_findings == 0

    other_a, other_b = make_handled_user(), make_handled_user()
    _finding(other_a)
    _finding(other_b)

    stats = compute_profile_stats(owner.id, db_session)
    assert stats.reuse_findings == 2
    # Two distinct groups reused it — that is a different claim from "two
    # Findings", and one lab publishing twice must not read as two groups.
    assert stats.reuse_groups == 2


def test_reuse_groups_counts_people_not_findings(
    graph_client, make_handled_user, make_raw_file, db_session
):
    owner = make_handled_user()
    graph_client.set_current_user(owner)
    spectrum = _publish_spectrum(graph_client, make_raw_file(owner), db_session)

    reuser = make_handled_user()
    for _ in range(3):
        finding = Finding(owner_id=reuser.id, title="F", state=FindingState.published)
        db_session.add(finding)
        db_session.commit()
        db_session.add(FindingSpectrum(finding_id=finding.id, spectrum_id=spectrum.id, position=0))
        db_session.commit()

    stats = compute_profile_stats(owner.id, db_session)
    assert stats.reuse_findings == 3
    assert stats.reuse_groups == 1


def test_public_profile_exposes_the_engagement_numbers(
    graph_client, make_handled_user, make_raw_file, db_session
):
    owner = make_handled_user()
    graph_client.set_current_user(owner)
    spectrum = _publish_spectrum(graph_client, make_raw_file(owner), db_session)

    fan = make_handled_user()
    graph_client.set_current_user(fan)
    graph_client.post(f"/spectra/{spectrum.id}/votes")
    graph_client.post(f"/users/{owner.handle}/follow")

    body = graph_client.get(f"/users/by-handle/{owner.handle}").json()
    assert body["followers"] == 1
    assert body["votes_received"] == 1
    assert body["spectrum_count"] == 1
    # Still no email, and still no ORCID verification badge.
    assert "email" not in body
    assert body["orcid_verified"] is False


# ---------------------------------------------------------------------------
# filter=following, and shares moving visibility
# ---------------------------------------------------------------------------


@pytest.fixture()
def feed_client(db_session):
    from app.routers import feed

    test_app = FastAPI()
    for module in (spectra, findings, shares, follows, feed):
        test_app.include_router(module.router)

    def _override_get_db():
        yield db_session

    current = {"user": None}

    def _override_get_current_user():
        if current["user"] is None:
            raise HTTPException(status_code=401, detail="Not authenticated")
        return current["user"]

    test_app.dependency_overrides[get_db] = _override_get_db
    test_app.dependency_overrides[get_current_user] = _override_get_current_user
    test_app.dependency_overrides[get_current_user_optional] = lambda: current["user"]

    client = TestClient(test_app)
    client.set_current_user = lambda user: current.__setitem__("user", user)
    return client


def test_following_filter_restricts_the_feed(
    feed_client, make_handled_user, make_raw_file, db_session
):
    followed, stranger, viewer = (
        make_handled_user(),
        make_handled_user(),
        make_handled_user(),
    )
    for owner in (followed, stranger):
        feed_client.set_current_user(owner)
        _publish_spectrum(feed_client, make_raw_file(owner), db_session)

    feed_client.set_current_user(viewer)
    everything = feed_client.get("/feed?kind=spectra").json()
    assert len(everything) >= 2

    feed_client.post(f"/users/{followed.handle}/follow")
    only_followed = feed_client.get("/feed?kind=spectra&filter=following").json()

    owners = {item["author"]["handle"] for item in only_followed}
    assert owners == {followed.handle}


def test_following_filter_is_empty_rather_than_an_error_when_signed_out(
    feed_client, make_handled_user, make_raw_file, db_session
):
    """A coherent question with an honest answer. Returning 401 would make the
    client handle an error for what is really just 'you follow nobody yet'."""
    owner = make_handled_user()
    feed_client.set_current_user(owner)
    _publish_spectrum(feed_client, make_raw_file(owner), db_session)

    feed_client.set_current_user(None)
    resp = feed_client.get("/feed?filter=following")
    assert resp.status_code == 200
    assert resp.json() == []


def test_following_nobody_yields_an_empty_feed(feed_client, make_handled_user):
    feed_client.set_current_user(make_handled_user())
    assert feed_client.get("/feed?filter=following").json() == []


def test_a_share_raises_an_items_feed_score(
    feed_client, make_handled_user, make_raw_file, db_session
):
    """Shares feed visibility — the product decision this build implements.
    Two spectra published in the same moment; the shared one must rank
    higher, otherwise sharing is a button that does nothing."""
    owner = make_handled_user()
    feed_client.set_current_user(owner)
    quiet = _publish_spectrum(feed_client, make_raw_file(owner), db_session)
    popular = _publish_spectrum(feed_client, make_raw_file(owner), db_session)

    sharer = make_handled_user()
    feed_client.set_current_user(sharer)
    assert feed_client.post(f"/spectra/{popular.id}/shares").status_code == 200

    scores = {
        item["id"]: item["score"] for item in feed_client.get("/feed?kind=spectra").json()
    }
    assert scores[str(popular.id)] > scores[str(quiet.id)]
