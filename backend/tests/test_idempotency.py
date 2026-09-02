"""Request idempotency — the fix for duplicate drafts / posts / votes.

A slow backend plus a retrying proxy (or an HTTP/2 stream reset) replays a
`POST` transparently, carrying the same client `Idempotency-Key`. The backend
must run the handler once and replay its response for the retry.

Covers the three cases the milestone owns:
  - same key twice  -> one row created, identical response,
  - different keys   -> two rows,
  - no header        -> behaviour completely unchanged.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.auth.deps import get_current_user, get_current_user_optional
from app.db.session import get_db
from app.models.finding import Finding
from app.models.idempotency import IdempotencyRecord
from app.models.social import Vote
from app.routers import findings, votes


@pytest.fixture()
def client(db_session):
    app = FastAPI()
    app.include_router(findings.router)
    app.include_router(votes.router)

    current: dict[str, object] = {"user": None}

    def _get_db():
        yield db_session

    app.dependency_overrides[get_db] = _get_db
    app.dependency_overrides[get_current_user] = lambda: current["user"]
    app.dependency_overrides[get_current_user_optional] = lambda: current["user"]

    c = TestClient(app)
    c.set_current_user = lambda u: current.__setitem__("user", u)
    return c


def _count(db, model) -> int:
    return db.execute(select(func.count()).select_from(model)).scalar_one()


# --------------------------------------------------------------- findings create


def test_same_key_twice_creates_one_finding_and_replays_response(client, db_session, make_user):
    client.set_current_user(make_user())
    before = _count(db_session, Finding)

    headers = {"Idempotency-Key": "replay-me-0001"}
    first = client.post("/v1/findings", json={"title": "Only once"}, headers=headers)
    second = client.post("/v1/findings", json={"title": "Only once"}, headers=headers)

    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    # Byte-for-byte the same answer — the retry got the stored response.
    assert first.json() == second.json()
    assert first.json()["id"] == second.json()["id"]

    # Exactly one new Finding, and one bookkeeping row.
    assert _count(db_session, Finding) == before + 1
    assert (
        db_session.execute(
            select(func.count())
            .select_from(IdempotencyRecord)
            .where(IdempotencyRecord.idem_key == "replay-me-0001")
        ).scalar_one()
        == 1
    )


def test_different_keys_create_two_findings(client, db_session, make_user):
    client.set_current_user(make_user())
    before = _count(db_session, Finding)

    a = client.post(
        "/v1/findings", json={"title": "First"}, headers={"Idempotency-Key": "k-a"}
    )
    b = client.post(
        "/v1/findings", json={"title": "Second"}, headers={"Idempotency-Key": "k-b"}
    )

    assert a.status_code == 201 and b.status_code == 201
    assert a.json()["id"] != b.json()["id"]
    assert _count(db_session, Finding) == before + 2


def test_no_header_is_unchanged_behaviour(client, db_session, make_user):
    client.set_current_user(make_user())
    before = _count(db_session, Finding)

    a = client.post("/v1/findings", json={"title": "One"})
    b = client.post("/v1/findings", json={"title": "One"})

    assert a.status_code == 201 and b.status_code == 201
    # No idempotency -> two distinct drafts, exactly as before this change.
    assert a.json()["id"] != b.json()["id"]
    assert _count(db_session, Finding) == before + 2
    assert _count(db_session, IdempotencyRecord) == 0


# --------------------------------------------------------------- finding votes


def test_replayed_vote_does_not_toggle_twice(client, db_session, make_user):
    user = make_user()
    client.set_current_user(user)
    fid = client.post("/v1/findings", json={"title": "Votable"}).json()["id"]

    headers = {"Idempotency-Key": "vote-key-1"}
    first = client.post(f"/findings/{fid}/votes", headers=headers)
    second = client.post(f"/findings/{fid}/votes", headers=headers)

    assert first.status_code == 200, first.text
    assert first.json() == {"voted": True, "count": 1}
    # Replay must NOT flip the vote back off.
    assert second.json() == first.json()

    assert (
        db_session.execute(
            select(func.count()).select_from(Vote).where(Vote.finding_id == fid)
        ).scalar_one()
        == 1
    )


def test_vote_without_header_still_toggles(client, db_session, make_user):
    user = make_user()
    client.set_current_user(user)
    fid = client.post("/v1/findings", json={"title": "Toggle"}).json()["id"]

    on = client.post(f"/findings/{fid}/votes")
    off = client.post(f"/findings/{fid}/votes")

    assert on.json() == {"voted": True, "count": 1}
    assert off.json() == {"voted": False, "count": 0}
