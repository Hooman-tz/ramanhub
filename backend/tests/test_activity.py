"""M6.3: GET /users/{handle}/activity — the contribution chart feed.

Creates published spectra / findings / comments across distinct UTC days and
asserts the per-day buckets, the totals, the streak logic, the `days` window
cap, and the 422 for an out-of-range `days`.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.auth.deps import get_current_user, get_current_user_optional
from app.db.session import get_db
from app.models.enums import FindingState, Modality, SpectrumState
from app.models.finding import Finding
from app.models.social import Comment
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


def _mk_user(db_session, handle: str) -> User:
    user = User(
        email=f"{uuid.uuid4().hex[:10]}@example.com",
        display_name="Dr Streak",
        is_profile_public=True,
        profile_handle=handle,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def test_activity_buckets_totals_and_streaks(client, db_session, make_raw_file):
    user = _mk_user(db_session, "streaky")
    today = datetime.now(UTC).date()
    # Anchor every event at noon UTC of its day, so the bucket a row lands in
    # can't flip across a midnight boundary while the test runs.
    noon = datetime(today.year, today.month, today.day, 12, tzinfo=UTC)

    raw = make_raw_file(user)
    spec = Spectrum(
        raw_file_id=raw.id,
        owner_id=user.id,
        modality=Modality.raman,
        title="today spectrum",
        state=SpectrumState.published,
        published_at=noon,
    )
    db_session.add(spec)
    db_session.add(
        Finding(
            owner_id=user.id,
            title="yesterday finding",
            state=FindingState.published,
            published_at=noon - timedelta(days=1),
            accession=f"RH-F-{uuid.uuid4().hex[:8]}",
        )
    )
    db_session.flush()
    # Comment targets the spectrum (the CHECK needs exactly one target); its
    # created_at is forced onto a distinct earlier UTC day.
    comment = Comment(spectrum_id=spec.id, user_id=user.id, body="three days ago")
    db_session.add(comment)
    db_session.flush()
    comment.created_at = noon - timedelta(days=3)
    db_session.commit()

    resp = client.get("/users/streaky/activity", params={"days": 10})
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert len(body["days"]) == 10
    assert body["days"][0]["date"] == str(today - timedelta(days=9))
    assert body["days"][-1]["date"] == str(today)

    by_date = {d["date"]: d for d in body["days"]}
    assert by_date[str(today)]["spectra"] == 1
    assert by_date[str(today - timedelta(days=1))]["findings"] == 1
    assert by_date[str(today - timedelta(days=3))]["comments"] == 1

    assert body["total"] == 3
    # today + yesterday are consecutive and active; three-days-ago is alone.
    assert body["current_streak"] == 2
    assert body["longest_streak"] == 2


def test_activity_window_is_capped_to_days_param(client, db_session):
    _mk_user(db_session, "windowed")
    body = client.get("/users/windowed/activity", params={"days": 30}).json()
    assert len(body["days"]) == 30
    assert body["total"] == 0
    assert body["current_streak"] == 0


def test_activity_rejects_out_of_range_days(client, db_session):
    _mk_user(db_session, "rangecheck")
    assert client.get("/users/rangecheck/activity", params={"days": 731}).status_code == 422
    assert client.get("/users/rangecheck/activity", params={"days": 0}).status_code == 422


def test_activity_404_for_unknown_handle(client, db_session):
    assert client.get("/users/who-dis/activity").status_code == 404
