"""M6.3: GET /users/by-handle/{handle} — the public profile surface.

Seeds one user with a published spectrum, a published finding, a follower and
some received engagement, then asserts the aggregate counts on the public
profile payload. Also covers the 404 rules (missing / inactive / guest) and
the `orcid_verified` derivation from `orcid_verified_at`.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.auth.deps import get_current_user, get_current_user_optional
from app.db.session import get_db
from app.models.enums import FindingState, Modality, SpectrumState
from app.models.finding import Finding
from app.models.graph import Follow
from app.models.social import Comment, Vote
from app.models.spectrum import Spectrum
from app.models.user import User
from app.routers import users as users_router


@pytest.fixture()
def client(db_session):
    app = FastAPI()
    app.include_router(users_router.router)

    state = {"user": None}

    def _override_get_db():
        yield db_session

    def _override_current_user():
        if state["user"] is None:
            raise HTTPException(status_code=401, detail="Not authenticated")
        return state["user"]

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_current_user] = _override_current_user
    app.dependency_overrides[get_current_user_optional] = lambda: state["user"]

    tc = TestClient(app)
    tc.set_current_user = lambda u: state.__setitem__("user", u)
    return tc


def _mk_user(db_session, handle: str | None = None, **kw) -> User:
    defaults = {
        "email": f"{uuid.uuid4().hex[:10]}@example.com",
        "google_sub": None,
        "display_name": "Dr Test",
        "is_profile_public": True,
        "profile_handle": handle or f"h-{uuid.uuid4().hex[:8]}",
    }
    defaults.update(kw)
    user = User(**defaults)
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def _published_spectrum(db_session, make_raw_file, owner, **kw) -> Spectrum:
    raw = make_raw_file(owner)
    spec = Spectrum(
        raw_file_id=raw.id,
        owner_id=owner.id,
        modality=Modality.raman,
        title=kw.pop("title", "Published spectrum"),
        state=SpectrumState.published,
        published_at=kw.pop("published_at", datetime.now(UTC)),
        **kw,
    )
    db_session.add(spec)
    db_session.commit()
    db_session.refresh(spec)
    return spec


def _published_finding(db_session, owner, **kw) -> Finding:
    finding = Finding(
        owner_id=owner.id,
        title=kw.pop("title", "Published finding"),
        state=FindingState.published,
        published_at=kw.pop("published_at", datetime.now(UTC)),
        accession=kw.pop("accession", f"RH-F-{uuid.uuid4().hex[:8]}"),
        **kw,
    )
    db_session.add(finding)
    db_session.commit()
    db_session.refresh(finding)
    return finding


def test_by_handle_aggregate_counts(client, db_session, make_user, make_raw_file):
    author = _mk_user(db_session, handle="dr-aggregate")
    follower = make_user()
    voter = make_user()
    commenter = make_user()

    spec = _published_spectrum(db_session, make_raw_file, author)
    _published_finding(db_session, author)
    # A draft finding must not be counted.
    db_session.add(
        Finding(owner_id=author.id, title="wip", state=FindingState.draft)
    )
    db_session.add(Follow(follower_id=follower.id, followee_id=author.id))
    db_session.add(Vote(spectrum_id=spec.id, user_id=voter.id))
    db_session.add(Comment(spectrum_id=spec.id, user_id=commenter.id, body="nice"))
    db_session.commit()

    resp = client.get("/users/by-handle/dr-aggregate")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["profile_handle"] == "dr-aggregate"
    assert body["followers"] == 1
    assert body["following"] == 0
    assert body["spectrum_count"] == 1
    assert body["finding_count"] == 1  # draft excluded
    assert body["votes_received"] == 1
    assert body["doi_linked"] == 0
    # The web client's PublicProfile contract fields are all present.
    for key in (
        "id",
        "display_name",
        "avatar_url",
        "orcid_id",
        "orcid_verified",
        "bio",
        "affiliation",
        "research_interests",
        "shares_received",
        "comments_written",
        "reuse_findings",
        "reuse_groups",
        "created_at",
    ):
        assert key in body
    assert "email" not in body


def test_by_handle_orcid_verified_flag(client, db_session):
    _mk_user(db_session, handle="no-orcid")
    _mk_user(
        db_session,
        handle="yes-orcid",
        orcid_id="0000-0002-1825-0097",
        orcid_verified_at=datetime.now(UTC),
    )

    assert client.get("/users/by-handle/no-orcid").json()["orcid_verified"] is False
    assert client.get("/users/by-handle/yes-orcid").json()["orcid_verified"] is True


def test_by_handle_handle_is_normalized(client, db_session):
    _mk_user(db_session, handle="casecheck")
    assert client.get("/users/by-handle/CaseCheck").status_code == 200


def test_by_handle_404_for_missing_inactive_and_guest(client, db_session):
    assert client.get("/users/by-handle/nobody-here").status_code == 404

    _mk_user(db_session, handle="gone", is_active=False)
    assert client.get("/users/by-handle/gone").status_code == 404

    _mk_user(db_session, handle="ghost", is_guest=True)
    assert client.get("/users/by-handle/ghost").status_code == 404
